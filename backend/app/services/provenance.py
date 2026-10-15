"""Reproducibility: software identity and the provenance audit trail."""

from __future__ import annotations

import platform
import sys
from typing import Any

from sqlalchemy.orm import Session

from app import __version__
from app.core.capabilities import detect_capabilities
from app.db.models import ProvenanceRecord


def software_identity() -> dict[str, Any]:
    return {
        "application": "MolDock Studio",
        "version": __version__,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def tool_versions(*, only_available: bool = True) -> dict[str, str]:
    """Version numbers of the scientific tools actually in use."""
    versions: dict[str, str] = {}
    for capability in detect_capabilities():
        if capability.category in {"runtime", "feature"}:
            continue
        if only_available and capability.status != "available":
            continue
        versions[capability.key] = capability.version or capability.location or "unknown"
    return versions


def record(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    project_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> ProvenanceRecord:
    """Append one provenance row. Callers commit with their transaction."""
    entry = ProvenanceRecord(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        inputs=inputs or {},
        outputs=outputs or {},
        params=params or {},
        tool_versions=tool_versions(),
        software=software_identity(),
    )
    session.add(entry)
    return entry


def record_and_commit(session: Session, **kwargs: Any) -> ProvenanceRecord:
    entry = record(session, **kwargs)
    session.commit()
    return entry
