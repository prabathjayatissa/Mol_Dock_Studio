"""Preparation endpoints: receptor prep, ligand prep, PDBQT generation,
binding-site definition, and end-to-end docking preparation."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, StoreDep
from app.db.models import LigandPrep, ReceptorPrep, Structure
from app.schemas.preparation import (
    DockingPrepOut,
    LigandPrepOut,
    PdbqtOut,
    ReceptorPrepOut,
)
from app.services.preparation import (
    generate_pdbqt,
    prepare_for_docking,
    prepare_ligand,
    prepare_receptor,
)

router = APIRouter(prefix="/preparation", tags=["preparation"])


class DockingPrepRequest(BaseModel):
    receptorStructureId: str
    ligandStructureId: str
    bindingSiteId: str | None = None
    receptorName: str | None = None
    ligandName: str | None = None
    keepWaters: bool = False
    keepCofactors: bool = False
    keepChains: list[str] | None = None
    addHydrogens: bool = True
    ligandEmbed3d: bool = True
    ligandSeed: int = 42
    ligandOptimize: bool = True
    ligandMaxConformers: int = 1


def _project_of(session: DbSession, structure_id: str) -> str:
    structure = session.get(Structure, structure_id)
    if structure is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Structure '{structure_id}' does not exist.")
    return structure.project_id


@router.post(
    "/receptor/{structure_id}",
    response_model=ReceptorPrepOut,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare a receptor (chain/water/cofactor policy)",
)
def prepare_receptor_route(
    structure_id: str,
    session: DbSession,
    store: StoreDep,
    keepWaters: bool = False,
    keepCofactors: bool = False,
    keepChains: list[str] | None = Query(default=None),
    addHydrogens: bool = False,
    name: str | None = None,
) -> ReceptorPrepOut:
    project_id = _project_of(session, structure_id)
    outcome = prepare_receptor(
        session,
        project_id=project_id,
        structure_id=structure_id,
        name=name,
        keep_waters=keepWaters,
        keep_cofactors=keepCofactors,
        keep_chains=keepChains,
        add_hydrogens=addHydrogens,
        store=store,
    )
    prep = outcome.receptor_prep
    return ReceptorPrepOut(
        id=prep.id,
        projectId=prep.project_id,
        inputStructureId=prep.input_structure_id,
        outputStructureId=prep.output_structure_id,
        status=prep.status,
        name=prep.config.get("name", outcome.record.name),
        kind="receptor",
        atomsKept=outcome.atoms_kept,
        atomsRemoved=outcome.atoms_removed,
        residuesKept=outcome.residues_kept,
        chainsKept=len(outcome.parsed.chains),
        warnings=prep.warnings or [],
        config=prep.config or {},
        toolVersions=prep.tool_versions or {},
        createdAt=prep.created_at,
    )


@router.post(
    "/ligand/{structure_id}",
    response_model=LigandPrepOut,
    status_code=status.HTTP_201_CREATED,
    summary="Prepare a ligand (RDKit conformer embedding)",
)
def prepare_ligand_route(
    structure_id: str,
    session: DbSession,
    store: StoreDep,
    embed3d: bool = True,
    seed: int = 42,
    optimize: bool = True,
    maxConformers: int = Query(default=1, ge=1, le=10),
    name: str | None = None,
) -> LigandPrepOut:
    project_id = _project_of(session, structure_id)
    outcome = prepare_ligand(
        session,
        project_id=project_id,
        structure_id=structure_id,
        name=name,
        embed_3d=embed3d,
        seed=seed,
        optimize=optimize,
        max_conformers=maxConformers,
        store=store,
    )
    prep = outcome.ligand_prep
    return LigandPrepOut(
        id=prep.id,
        projectId=prep.project_id,
        inputStructureId=prep.ligand_id,
        outputStructureId=prep.output_structure_id,
        status=prep.status,
        name=prep.config.get("name", outcome.record.name),
        kind="ligand",
        conformers=outcome.conformers,
        embedding=prep.config.get("embedding"),
        optimization=prep.config.get("optimization"),
        warnings=prep.warnings or [],
        config=prep.config or {},
        toolVersions=prep.tool_versions or {},
        createdAt=prep.created_at,
    )


@router.post(
    "/pdbqt/{structure_id}",
    response_model=PdbqtOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a PDBQT file from a prepared structure (Meeko)",
)
def generate_pdbqt_route(
    structure_id: str,
    session: DbSession,
    store: StoreDep,
) -> PdbqtOut:
    project_id = _project_of(session, structure_id)
    result = generate_pdbqt(
        session,
        project_id=project_id,
        structure_id=structure_id,
        store=store,
    )
    return PdbqtOut(
        structureId=result["structureId"],
        path=result["pdbqtPath"],
        sha256=result["pdbqtSha256"],
        heavyAtoms=result["heavyAtoms"],
        pdbqtAtoms=result["pdbqtAtoms"],
    )


@router.post(
    "/docking-prep",
    response_model=DockingPrepOut,
    status_code=status.HTTP_201_CREATED,
    summary="End-to-end Phase 2 preparation for docking (receptor + ligand + PDBQT)",
)
def prepare_for_docking_route(
    payload: DockingPrepRequest,
    session: DbSession,
    store: StoreDep,
) -> DockingPrepOut:
    result = prepare_for_docking(
        session,
        project_id=_project_of(session, payload.receptorStructureId),
        receptor_structure_id=payload.receptorStructureId,
        ligand_structure_id=payload.ligandStructureId,
        binding_site_id=payload.bindingSiteId,
        receptor_name=payload.receptorName,
        ligand_name=payload.ligandName,
        keep_waters=payload.keepWaters,
        keep_cofactors=payload.keepCofactors,
        keep_chains=payload.keepChains,
        add_hydrogens=payload.addHydrogens,
        ligand_embed3d=payload.ligandEmbed3d,
        ligand_seed=payload.ligandSeed,
        ligand_optimize=payload.ligandOptimize,
        ligand_max_conformers=payload.ligandMaxConformers,
        store=store,
    )
    return DockingPrepOut(
        receptorPrepId=result["receptorPrep"]["id"],
        receptorOutputStructureId=result["receptorPrep"]["outputStructureId"],
        receptorAtomsKept=result["receptorPrep"]["atomsKept"],
        receptorAtomsRemoved=result["receptorPrep"]["atomsRemoved"],
        ligandPrepId=result["ligandPrep"]["id"],
        ligandOutputStructureId=result["ligandPrep"]["outputStructureId"],
        ligandConformers=result["ligandPrep"]["conformers"],
        receptorPdbqt=PdbqtOut(
            structureId=payload.receptorStructureId,
            path=result["receptorPdbqt"]["path"],
            sha256=result["receptorPdbqt"]["sha256"],
            heavyAtoms=result["receptorPdbqt"]["heavyAtoms"],
            pdbqtAtoms=result["receptorPdbqt"]["pdbqtAtoms"],
        ),
        ligandPdbqt=PdbqtOut(
            structureId=payload.ligandStructureId,
            path=result["ligandPdbqt"]["path"],
            sha256=result["ligandPdbqt"]["sha256"],
            heavyAtoms=result["ligandPdbqt"]["heavyAtoms"],
            pdbqtAtoms=result["ligandPdbqt"]["pdbqtAtoms"],
        ),
        bindingSite=result["bindingSite"],
    )


@router.get(
    "/receptor-preps",
    response_model=list[ReceptorPrepOut],
    summary="List receptor preparations for a project",
)
def list_receptor_preps(
    session: DbSession,
    projectId: str,
) -> list[ReceptorPrepOut]:
    rows = session.scalars(
        select(ReceptorPrep)
        .where(ReceptorPrep.project_id == projectId)
        .order_by(ReceptorPrep.created_at.desc())
    ).all()
    return [
        ReceptorPrepOut(
            id=row.id,
            projectId=row.project_id,
            inputStructureId=row.input_structure_id,
            outputStructureId=row.output_structure_id,
            status=row.status,
            name=(row.config or {}).get("name", ""),
            kind="receptor",
            atomsKept=(row.config or {}).get("atomsKept", 0),
            atomsRemoved=(row.config or {}).get("atomsRemoved", 0),
            residuesKept=(row.config or {}).get("residuesKept", 0),
            chainsKept=(row.config or {}).get("chainsKept", 0),
            warnings=row.warnings or [],
            config=row.config or {},
            toolVersions=row.tool_versions or {},
            createdAt=row.created_at,
        )
        for row in rows
    ]


@router.get(
    "/ligand-preps",
    response_model=list[LigandPrepOut],
    summary="List ligand preparations for a project",
)
def list_ligand_preps(
    session: DbSession,
    projectId: str,
) -> list[LigandPrepOut]:
    rows = session.scalars(
        select(LigandPrep)
        .where(LigandPrep.project_id == projectId)
        .order_by(LigandPrep.created_at.desc())
    ).all()
    return [
        LigandPrepOut(
            id=row.id,
            projectId=row.project_id,
            inputStructureId=row.ligand_id,
            outputStructureId=row.output_structure_id,
            status=row.status,
            name=(row.config or {}).get("name", ""),
            kind="ligand",
            conformers=(row.config or {}).get("conformers", 0),
            embedding=(row.config or {}).get("embedding"),
            optimization=(row.config or {}).get("optimization"),
            warnings=row.warnings or [],
            config=row.config or {},
            toolVersions=row.tool_versions or {},
            createdAt=row.created_at,
        )
        for row in rows
    ]


__all__ = ["router"]
