"""Preparation endpoints: receptor prep, ligand prep, binding-site definition."""

from __future__ import annotations

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import DbSession, StoreDep
from app.db.models import LigandPrep, ReceptorPrep, Structure
from app.schemas.preparation import (
    LigandPrepOut,
    ReceptorPrepOut,
)
from app.services.preparation import (
    prepare_ligand,
    prepare_receptor,
)

router = APIRouter(prefix="/preparation", tags=["preparation"])


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
