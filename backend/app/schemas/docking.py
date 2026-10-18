"""MolDock Studio: docking schemas (Phase 3).

All computed quantities (scores in kcal/mol, RMSD in Angstrom) are approximate
scoring-function outputs — never measured binding affinities or clinical
evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class DockingPoseOut(ORMModel):
    id: str
    projectId: str
    dockingJobId: str
    structureId: str | None = None
    poseIndex: int
    rank: int
    scoreKcalMol: float | None = None
    rmsdLowerBound: float | None = None
    rmsdUpperBound: float | None = None
    filePath: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class DockingJobOut(ORMModel):
    id: str
    projectId: str
    jobId: str
    engine: str
    engineVersion: str | None = None
    receptorFile: str | None = None
    ligandFile: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    command: list[Any] = Field(default_factory=list)
    outputFiles: list[Any] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class DockingRunRequest(BaseModel):
    receptorStructureId: str
    ligandStructureId: str
    bindingSiteId: str | None = None
    numModes: int = Field(default=9, ge=1, le=100)
    energyRange: float = Field(default=3.0, gt=0)
    exhaustiveness: int = Field(default=8, ge=1, le=128)
    seed: int | None = None


class DockingRunOut(BaseModel):
    jobId: str
    status: str
    note: str


__all__ = [
    "DockingPoseOut",
    "DockingJobOut",
    "DockingRunRequest",
    "DockingRunOut",
]
