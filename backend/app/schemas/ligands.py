"""Ligand schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class DescriptorOut(BaseModel):
    smiles: str | None = None
    inchiKey: str | None = None
    formula: str | None = None
    molecularWeight: float | None = None
    exactMass: float | None = None
    logp: float | None = None
    tpsa: float | None = None
    hBondDonors: int | None = None
    hBondAcceptors: int | None = None
    rotatableBonds: int | None = None
    formalCharge: int | None = None
    heavyAtoms: int | None = None
    aromaticRings: int | None = None
    ringCount: int | None = None
    stereocenters: int | None = None
    fractionCsp3: float | None = None
    valid: bool = True
    messages: list[dict[str, Any]] = Field(default_factory=list)


class LigandOut(ORMModel):
    id: str
    projectId: str
    structureId: str
    name: str
    smiles: str | None = None
    inchiKey: str | None = None
    formula: str | None = None
    molecularWeight: float | None = None
    logp: float | None = None
    tpsa: float | None = None
    hBondDonors: int | None = None
    hBondAcceptors: int | None = None
    rotatableBonds: int | None = None
    formalCharge: int | None = None
    heavyAtoms: int | None = None
    aromaticRings: int | None = None
    stereocenters: int | None = None
    descriptorSource: str
    valid: bool
    validationMessages: list[Any] = Field(default_factory=list)
    createdAt: dt.datetime


class LigandListOut(BaseModel):
    items: list[LigandOut]
    total: int


class LigandSmilesRequest(BaseModel):
    """Create a ligand from a SMILES string (drawing/editing integration point)."""

    projectId: str
    smiles: str
    name: str = Field(default="Ligand", max_length=200)
    embed3d: bool = Field(default=True, description="Generate a 3D conformer with RDKit ETKDG.")
    seed: int = 42
