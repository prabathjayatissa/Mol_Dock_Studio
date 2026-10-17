"""Binding-site definition endpoints (Phase 2/3)."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.db.models import BindingSite
from app.schemas.preparation import BindingSiteOut, BindingSiteRequest
from app.services.preparation import define_binding_site

router = APIRouter(prefix="/binding-sites", tags=["binding-sites"])


@router.post(
    "",
    response_model=BindingSiteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Define a docking search space on a receptor",
)
def define_binding_site_route(
    payload: BindingSiteRequest,
    session: DbSession,
) -> BindingSiteOut:
    site = define_binding_site(
        session,
        project_id=payload.projectId,
        receptor_structure_id=payload.receptorStructureId,
        name=payload.name,
        method=payload.method,
        center_x=payload.centerX,
        center_y=payload.centerY,
        center_z=payload.centerZ,
        size_x=payload.sizeX,
        size_y=payload.sizeY,
        size_z=payload.sizeZ,
        reference_ligand_structure_id=payload.referenceLigandStructureId,
        residues=payload.residues,
    )
    return BindingSiteOut.model_validate(site, from_attributes=True)


@router.get(
    "",
    response_model=list[BindingSiteOut],
    summary="List binding sites for a project (optionally filtered by receptor)",
)
def list_binding_sites(
    session: DbSession,
    projectId: str,
    receptorStructureId: str | None = Query(default=None),
) -> list[BindingSiteOut]:
    from sqlalchemy import select

    query = select(BindingSite).where(BindingSite.project_id == projectId)
    if receptorStructureId:
        query = query.where(BindingSite.receptor_structure_id == receptorStructureId)
    query = query.order_by(BindingSite.created_at.desc())
    rows = session.scalars(query).all()
    return [BindingSiteOut.model_validate(row, from_attributes=True) for row in rows]


__all__ = ["router"]
