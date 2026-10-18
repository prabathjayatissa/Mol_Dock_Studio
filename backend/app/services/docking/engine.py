"""MolDock Studio: docking engine interface and AutoDock Vina adapter.

This module defines the :class:`DockingEngine` interface and a concrete
:class:`VinaEngine` that drives AutoDock Vina via its command-line interface.

Design notes
------------
* AutoDock Vina ships manylinux x86_64 wheels only. On macOS arm64 there is no
  native wheel, so docking is reached through the linux/amd64 container
  (``MOLDOCK_PLATFORM=linux/amd64 MOLDOCK_INSTALL_VINA=1 docker compose up``)
  or a locally built binary pointed to by ``MOLDOCK_VINA_BINARY``.
* The engine is deliberately subprocess-based: Vina is a standalone binary,
  not a Python library. This keeps the API process isolated from Vina crashes.
* All quantities (scores in kcal/mol, RMSD in Angstrom) are approximate
  scoring-function outputs — never measured affinities.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import NotFoundError, ValidationFailure


@dataclass(frozen=True)
class DockingPoseResult:
    """One ranked pose from a docking run."""

    rank: int
    score_kcal_mol: float
    rmsd_lower_bound: float | None = None
    rmsd_upper_bound: float | None = None
    file_path: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DockingRunResult:
    """Complete result of a docking run."""

    engine: str
    engine_version: str | None
    receptor_file: str
    ligand_file: str
    box_center: tuple[float, float, float]
    box_size: tuple[float, float, float]
    num_modes: int
    energy_range: float
    exhaustiveness: int
    poses: list[DockingPoseResult]
    command: list[str]
    work_dir: str
    output_files: list[str] = field(default_factory=list)
    raw_output: str | None = None


class DockingEngine(ABC):
    """Abstract interface for a molecular docking engine.

    Implementations produce a ranked list of poses from a receptor PDBQT,
    ligand PDBQT and a search box (centre + size in Angstrom).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short engine identifier (e.g. ``"vina"``)."""

    @property
    @abstractmethod
    def version(self) -> str | None:
        """Engine version string, or ``None`` if unknown."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if the engine binary is present and executable."""

    @abstractmethod
    def dock(
        self,
        *,
        receptor_pdbqt: str | Path,
        ligand_pdbqt: str | Path,
        box_center: tuple[float, float, float],
        box_size: tuple[float, float, float],
        work_dir: str | Path,
        num_modes: int = 9,
        energy_range: float = 3.0,
        exhaustiveness: int = 8,
        seed: int | None = None,
    ) -> DockingRunResult:
        """Run a docking calculation and return ranked poses."""


class VinaEngine(DockingEngine):
    """AutoDock Vina engine adapter driven via the command line.

    Vina is invoked as::

        vina --receptor <rec.pdbqt> --ligand <lig.pdbqt>
               --center_x <x> --center_y <y> --center_z <z>
               --size_x <sx> --size_y <sy> --size_z <sz>
               --num_modes <n> --energy_range <r> --exhaustiveness <e>
               [--seed <s>] --out <out.pdbqt> --log <log.txt>

    The binary is resolved in this order:
    1. ``MOLDOCK_VINA_BINARY`` environment variable
    2. ``vina`` on ``PATH``
    3. Common platform locations
    """

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or os.environ.get("MOLDOCK_VINA_BINARY") or self._locate_binary()

    # -- engine interface ---------------------------------------------------

    @property
    def name(self) -> str:
        return "vina"

    @property
    def version(self) -> str | None:
        try:
            out = subprocess.run(
                [self._binary, "--help"], capture_output=True, text=True, timeout=15
            )
            combined = (out.stdout or "") + (out.stderr or "")
            for line in combined.splitlines():
                if "AutoDock Vina" in line:
                    # e.g. "AutoDock Vina 1.2.5"
                    parts = line.split()
                    for token in parts:
                        if token[0].isdigit():
                            return token
            return None
        except Exception:  # noqa: BLE001 - version is best-effort
            return None

    def is_available(self) -> bool:
        return bool(self._binary) and Path(self._binary).exists() and os.access(self._binary, os.X_OK)

    # -- docking ------------------------------------------------------------

    def dock(
        self,
        *,
        receptor_pdbqt: str | Path,
        ligand_pdbqt: str | Path,
        box_center: tuple[float, float, float],
        box_size: tuple[float, float, float],
        work_dir: str | Path,
        num_modes: int = 9,
        energy_range: float = 3.0,
        exhaustiveness: int = 8,
        seed: int | None = None,
    ) -> DockingRunResult:
        """Run AutoDock Vina and parse the ranked poses."""

        if not self.is_available():
            raise ValidationFailure(
                "AutoDock Vina binary is not available.",
                detail={"engine": "vina", "binary": self._binary},
                remediation=(
                    "Install AutoDock Vina (linux/amd64 via Docker, or build from source) "
                    "and set MOLDOCK_VINA_BINARY to its path."
                ),
            )

        receptor = Path(receptor_pdbqt)
        ligand = Path(ligand_pdbqt)
        if not receptor.exists():
            raise NotFoundError(f"Receptor PDBQT not found: {receptor}")
        if not ligand.exists():
            raise NotFoundError(f"Ligand PDBQT not found: {ligand}")

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        out_pdbqt = work_dir / "out.pdbqt"
        log_file = work_dir / "log.txt"

        cx, cy, cz = box_center
        sx, sy, sz = box_size

        cmd: list[str] = [
            str(self._binary),
            "--receptor", str(receptor),
            "--ligand", str(ligand),
            "--center_x", str(cx),
            "--center_y", str(cy),
            "--center_z", str(cz),
            "--size_x", str(sx),
            "--size_y", str(sy),
            "--size_z", str(sz),
            "--num_modes", str(num_modes),
            "--energy_range", str(energy_range),
            "--exhaustiveness", str(exhaustiveness),
            "--out", str(out_pdbqt),
            "--log", str(log_file),
        ]
        if seed is not None:
            cmd.extend(["--seed", str(seed)])

        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3600
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationFailure(
                "AutoDock Vina timed out.",
                detail={"engine": "vina", "command": " ".join(cmd)},
                remediation="Reduce exhaustiveness or num_modes, or raise MOLDOCK_JOB_TIMEOUT_SECONDS.",
            ) from exc

        raw_output = (completed.stdout or "") + "\n" + (completed.stderr or "")

        if completed.returncode != 0:
            raise ValidationFailure(
                f"AutoDock Vina exited with code {completed.returncode}.",
                detail={"engine": "vina", "command": " ".join(cmd), "logTail": raw_output[-2000:]},
                remediation="Check receptor/ligand PDBQT validity, box size, and Vina binary.",
            )

        poses = self._parse_vina_log(raw_output, out_pdbqt if out_pdbqt.exists() else None)

        return DockingRunResult(
            engine="vina",
            engine_version=self.version,
            receptor_file=str(receptor),
            ligand_file=str(ligand),
            box_center=box_center,
            box_size=box_size,
            num_modes=num_modes,
            energy_range=energy_range,
            exhaustiveness=exhaustiveness,
            poses=poses,
            command=cmd,
            work_dir=str(work_dir),
            output_files=[str(out_pdbqt), str(log_file)],
            raw_output=raw_output,
        )

    # -- parsing ------------------------------------------------------------

    @staticmethod
    def _parse_vina_log(raw_output: str, out_pdbqt: Path | None) -> list[DockingPoseResult]:
        """Parse Vina's log text for the ranked mode table."""

        poses: list[DockingPoseResult] = []
        in_modes = False
        for line in raw_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("-------") and "mode" in stripped.lower():
                in_modes = True
                continue
            if in_modes:
                if not stripped or stripped.startswith("-------"):
                    continue
                parts = stripped.split()
                if len(parts) < 3:
                    continue
                try:
                    rank = int(parts[0])
                    score = float(parts[1])
                    rmsd_lb = float(parts[2]) if len(parts) > 2 else None
                    rmsd_ub = float(parts[3]) if len(parts) > 3 else None
                except ValueError:
                    continue
                poses.append(
                    DockingPoseResult(
                        rank=rank,
                        score_kcal_mol=score,
                        rmsd_lower_bound=rmsd_lb,
                        rmsd_upper_bound=rmsd_ub,
                    )
                )
        return poses

    # -- binary resolution --------------------------------------------------

    @staticmethod
    def _locate_binary() -> str | None:
        """Locate the vina binary on this platform."""

        # 1. PATH
        found = shutil.which("vina")
        if found:
            return found

        # 2. Common platform locations
        candidates: list[str] = []
        if sys.platform == "win32":  # Windows
            candidates.extend([
                r"C:\Program Files\AutoDock Vina\vina.exe",
                r"C:\Program Files (x86)\AutoDock Vina\vina.exe",
                r"C:\vina\vina.exe",
            ])
        elif sys.platform == "darwin":  # macOS
            candidates.extend([
                "/usr/local/bin/vina",
                "/opt/homebrew/bin/vina",
                "/opt/vina/bin/vina",
            ])
        else:  # Linux and others
            candidates.extend([
                "/usr/bin/vina",
                "/usr/local/bin/vina",
                "/opt/vina/bin/vina",
                "/usr/lib/vina/vina",
            ])

        for candidate in candidates:
            if Path(candidate).exists() and os.access(candidate, os.X_OK):
                return candidate
        return None


def resolve_docking_engine(binary: str | None = None) -> DockingEngine:
    """Factory: return a configured docking engine (Vina today)."""

    return VinaEngine(binary=binary)


def vina_available() -> bool:
    """Convenience: is a Vina binary resolvable on this machine?"""
    return VinaEngine().is_available()


def vina_version() -> str | None:
    """Convenience: Vina version string, or None if unavailable."""
    try:
        return VinaEngine().version
    except Exception:  # noqa: BLE001 - best effort
        return None
