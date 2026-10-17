"""Preparation and binding-site schemas (Phase 2).

All computed quantities (conformer count, box centre/size) are derived from
the structure geometry, never measured.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class ReceptorPrepRequest(BaseModel):
    structureId: str
    name: str | None = Field(default=None, max_length=200)
    keepWaters: bool = Field(default=False, description="Retain crystallographic waters.")
    keepCofactors: bool = Field(
        default=False, description="Retain non-polymer hetero residues (cofactors, ions, metals)."
    )
    keepChains: list[str] | None = Field(
        default=None, description="Chain ids to keep. None keeps every polymer chain."
    )


class ReceptorPrepOut(ORMModel):
    id: str
    projectId: str
    inputStructureId: str
    outputStructureId: str | None = None
    status: str
    name: str
    kind: str = "receptor"
    atomsKept: int
    atomsRemoved: int
    residuesKept: int
    chainsKept: int
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    toolVersions: dict[str, str] = Field(default_factory=dict)
    createdAt: datetime


class LigandPrepRequest(BaseModel):
    structureId: str
    name: str | None = Field(default=None, max_length=200)
    embed3d: bool = Field(default=True, description="Generate an ETKDGv3 3D conformer.")
    seed: int = Field(default=42, ge=0, description="Random seed for conformer embedding.")
    optimize: bool = Field(default=True, description="MMFF94-optimise the conformer.")
    maxConformers: int = Field(default=1, ge=1, le=10, description="Conformers to embed (1 stored).")


class LigandPrepOut(ORMModel):
    id: str
    projectId: str
    inputStructureId: str
    outputStructureId: str | None = None
    status: str
    name: str
    kind: str = "ligand"
    conformers: int
    embedding: str | None = None
    optimization: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    toolVersions: dict[str, str] = Field(default_factory=dict)
    createdAt: datetime


class BindingSiteRequest(BaseModel):
    projectId: str
    receptorStructureId: str
    name: str | None = Field(default=None, max_length=160)
    method: Literal["manual", "ligand", "residues"] = Field(
        default="manual",
        description="manual: explicit centre/size; ligand: from a reference ligand's bounds; residues: from named residues.",
    )
    centerX: float | None = None
    centerY: float | None = None
    centerZ: float | None = None
    sizeX: float = Field(default=22.0, gt=0)
    sizeY: float = Field(default=22.0, gt=0)
    sizeZ: float = Field(default=22.0, gt=0)
    referenceLigandStructureId: str | None = None
    residues: list[str] | None = Field(
        default=None, description="Residue labels like ['A:123', 'B:45'] when method='residues'."
    )


class BindingSiteOut(ORMModel):
    id: str
    projectId: str
    receptorStructureId: str
    name: str
    method: str
    centerX: float
    centerY: float
    centerZ: float
    sizeX: float
    sizeY: float
    sizeZ: float
    sourceLigandStructureId: str | None = None
    residues: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


__all__ = [
    "ReceptorPrepRequest",
    "ReceptorPrepOut",
    "LigandPrepRequest",
    "LigandPrepOut",
    "BindingSiteRequest",
    "BindingSiteOut",
]
