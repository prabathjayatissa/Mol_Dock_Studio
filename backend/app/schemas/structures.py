"""Structure and surface schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class WarningOut(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    count: int | None = None
    detail: dict[str, Any] | None = None


class ChainOut(BaseModel):
    index: int
    id: str
    kind: str
    residueStart: int
    residueCount: int
    label: str


class StructureOut(ORMModel):
    id: str
    projectId: str
    name: str
    kind: str
    format: str
    source: str
    # `to_snake` would give `file_sha_256`; the column is `file_sha256`.
    fileSha256: str = Field(validation_alias="file_sha256")
    sizeBytes: int
    atomsCount: int
    residuesCount: int
    chainsCount: int
    parentStructureId: str | None = None
    createdAt: dt.datetime


class StructureDetailOut(StructureOut):
    warnings: list[WarningOut] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    chains: list[dict[str, Any]] = Field(default_factory=list)
    ligand: dict[str, Any] | None = None


class StructureListOut(BaseModel):
    items: list[StructureOut]
    total: int


class ImportResultOut(BaseModel):
    structure: StructureDetailOut
    warnings: list[WarningOut]
    statistics: dict[str, Any]
    ligand: dict[str, Any] | None = None
    packetUrl: str
    provenance: dict[str, Any]


class FetchRequest(BaseModel):
    projectId: str
    entryId: str = Field(description="4-character RCSB PDB identifier, e.g. 1UBQ", min_length=4, max_length=4)
    format: Literal["pdb", "mmcif"] = "pdb"
    name: str | None = None


class SurfaceParams(BaseModel):
    mode: Literal["vdw", "sas"] = "sas"
    probeRadius: float = Field(default=1.4, ge=0.0, le=5.0)
    gridSpacing: float = Field(default=0.8, ge=0.35, le=3.0)
    includeHydrogens: bool = False
    useCache: bool = True
    background: bool = Field(
        default=False,
        description="Run the computation as a background job and return a job id instead of the mesh.",
    )


class SurfaceStatsOut(BaseModel):
    mode: str
    probeRadius: float
    requestedSpacing: float | None = None
    spacingUsed: float
    vertices: int
    triangles: int
    area: float
    volume: float
    atomsUsed: int
    gridShape: list[int]
    warnings: list[str] = Field(default_factory=list)
    cached: bool | None = None
    computeSeconds: float | None = None
    cachePath: str | None = None


class SurfaceOut(BaseModel):
    structureId: str
    encoding: str
    vertexCount: int
    triangleCount: int
    positions: str
    normals: str
    indices: str
    stats: SurfaceStatsOut


class StructureExportQuery(BaseModel):
    format: Literal["pdb", "mmcif", "sdf", "mol2", "xyz"] = "pdb"
