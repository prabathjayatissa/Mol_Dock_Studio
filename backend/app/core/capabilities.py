"""Scientific-tool capability detection.

The application must never pretend that a scientific backend is present. Every
optional tool (AutoDock Vina, Meeko, Open Babel, PDB2PQR) is probed once and
reported through ``/api/health``; endpoints that need a missing tool respond
with HTTP 503 and an actionable remediation string.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Literal

from app.core.config import Settings, get_settings

CapabilityStatus = Literal["available", "unavailable", "not_implemented"]


@dataclass(frozen=True)
class Capability:
    """Result of probing one scientific tool."""

    key: str
    label: str
    category: str
    status: CapabilityStatus
    version: str | None = None
    location: str | None = None
    mode: str | None = None
    remediation: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _module_version(module_name: str, distribution: str | None = None) -> str | None:
    """Best-effort version lookup for an installed module."""
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - any import failure means "unavailable"
        return None
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    for dist in filter(None, (distribution, module_name.split(".")[0])):
        try:
            return importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "unknown"


def _probe_module(
    key: str,
    label: str,
    category: str,
    module: str,
    remediation: str,
    distribution: str | None = None,
) -> Capability:
    version = _module_version(module, distribution)
    if version is None:
        return Capability(
            key=key, label=label, category=category, status="unavailable", remediation=remediation
        )
    return Capability(
        key=key,
        label=label,
        category=category,
        status="available",
        version=version,
        mode="native-python",
    )


def _probe_binary(key: str, label: str, configured: str, name: str, remediation: str) -> Capability:
    path = configured.strip() or shutil.which(name) or ""
    if not path:
        return Capability(
            key=key, label=label, category="executable", status="unavailable", remediation=remediation
        )
    resolved = shutil.which(path) or path
    return Capability(
        key=key,
        label=label,
        category="executable",
        status="available",
        location=resolved,
        mode="external-binary",
    )


def detect_capabilities(settings: Settings | None = None) -> list[Capability]:
    """Probe every tool the application can use. Cheap enough to call per request."""
    settings = settings or get_settings()
    capabilities: list[Capability] = [
        Capability(
            key="python",
            label=f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            category="runtime",
            status="available",
            version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            location=sys.executable,
            mode=settings.scientific_backend_mode,
        ),
        _probe_module(
            "rdkit",
            "RDKit",
            "cheminformatics",
            "rdkit",
            "Install with: uv sync (RDKit wheels are published for macOS arm64 and manylinux).",
            distribution="rdkit",
        ),
        _probe_module(
            "gemmi",
            "gemmi",
            "structure-io",
            "gemmi",
            "Install with: uv sync.",
            distribution="gemmi",
        ),
        _probe_module(
            "biopython",
            "Biopython",
            "bioinformatics",
            "Bio",
            "Install with: uv sync.",
            distribution="biopython",
        ),
        _probe_module(
            "numpy",
            "NumPy",
            "numerics",
            "numpy",
            "Install with: uv sync.",
            distribution="numpy",
        ),
        _probe_module(
            "scipy",
            "SciPy",
            "numerics",
            "scipy",
            "Install with: uv sync.",
            distribution="scipy",
        ),
        _probe_module(
            "scikit-image",
            "scikit-image",
            "geometry",
            "skimage",
            "Install with: uv sync.",
            distribution="scikit-image",
        ),
        _probe_module(
            "meeko",
            "Meeko",
            "preparation",
            "meeko",
            "Phase 2 needs Meeko for ligand/receptor PDBQT preparation: uv sync --extra docking.",
            distribution="meeko",
        ),
        _probe_module(
            "pdb2pqr",
            "PDB2PQR",
            "preparation",
            "pdb2pqr",
            "Phase 2 protonation states: uv sync --extra protein-prep.",
            distribution="pdb2pqr",
        ),
    ]

    vina_python = _probe_module(
        "vina-python",
        "AutoDock Vina (Python bindings)",
        "docking",
        "vina",
        "No macOS arm64 wheel exists for AutoDock Vina. Use the linux/amd64 container "
        "(MOLDOCK_PLATFORM=linux/amd64 MOLDOCK_INSTALL_VINA=1 docker compose up --build) "
        "or set MOLDOCK_VINA_BINARY to a locally built binary.",
        distribution="vina",
    )
    vina_cli = _probe_binary(
        "vina-cli",
        "AutoDock Vina (vina executable)",
        settings.vina_binary,
        "vina",
        "Build AutoDock Vina 1.2.x from source (brew install boost swig cmake) or run the "
        "linux/amd64 container, then set MOLDOCK_VINA_BINARY.",
    )
    capabilities.extend([vina_python, vina_cli])

    capabilities.append(
        _probe_binary(
            "obabel",
            "Open Babel (obabel)",
            settings.obabel_binary,
            "obabel",
            "Optional, used only for extra format conversions: brew install open-babel.",
        )
    )

    if vina_python.status != "available" and vina_cli.status != "available":
        capabilities.append(
            Capability(
                key="docking",
                label="Molecular docking (AutoDock Vina)",
                category="feature",
                status="not_implemented",
                remediation=(
                    "Docking is scheduled for Phase 3 and additionally requires AutoDock Vina, "
                    "which has no macOS arm64 wheel."
                ),
                detail="Engine adapter and job submission arrive in Phase 3.",
            )
        )
    else:
        capabilities.append(
            Capability(
                key="docking",
                label="Molecular docking (AutoDock Vina)",
                category="feature",
                status="not_implemented",
                remediation="AutoDock Vina is present. The engine adapter is delivered in Phase 3.",
                detail="Vina detected; Phase 3 wires it into the job queue.",
            )
        )

    return capabilities


def capability_map(settings: Settings | None = None) -> dict[str, Capability]:
    return {cap.key: cap for cap in detect_capabilities(settings)}


def require_capability(key: str, *, feature: str, settings: Settings | None = None) -> Capability:
    """Return a capability or raise a 503 with remediation."""
    from app.core.errors import CapabilityUnavailableError

    capability = capability_map(settings).get(key)
    if capability is None or capability.status != "available":
        remediation = (
            capability.remediation
            if capability and capability.remediation
            else f"Install the dependency required for {feature} (see docs/dependency-matrix.md)."
        )
        raise CapabilityUnavailableError(
            f"{feature} requires {capability.label if capability else key}, which is not available.",
            detail={"capability": key, "status": capability.status if capability else "unknown"},
            remediation=remediation,
        )
    return capability
