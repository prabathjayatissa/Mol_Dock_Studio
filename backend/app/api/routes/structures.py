"""Structure endpoints: import, inspect, surface, export."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession, StoreDep
from app.core.errors import UploadRejectedError
from app.db.models import Structure
from app.schemas.jobs import JobOut
from app.schemas.structures import (
    FetchRequest,
    ImportResultOut,
    StructureDetailOut,
    StructureListOut,
    StructureOut,
    SurfaceOut,
    SurfaceParams,
)
from app.services.io.rcsb import fetch_entry
from app.services.jobs.manager import get_job_manager
from app.services.structures import (
    build_packet_for,
    delete_structure,
    export_structure_content,
    get_structure,
    import_structure,
    load_parsed,
    structure_detail_payload,
)
from app.services.surfaces import SurfaceRequest, generate_and_cache, mesh_payload_from_stats

router = APIRouter(prefix="/structures", tags=["structures"])


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload with a hard size ceiling (never trust Content-Length)."""
    chunk_size = 1 << 20
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise UploadRejectedError(
                f"'{file.filename}' exceeds the {max_bytes / 1e6:.0f} MB upload limit.",
                detail={"limitBytes": max_bytes},
                remediation="Raise MOLDOCK_MAX_UPLOAD_MB in .env, or import a smaller file.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/import",
    response_model=ImportResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Import a structure file",
)
async def import_structure_endpoint(
    session: DbSession,
    store: StoreDep,
    settings: AppSettings,
    file: UploadFile = File(..., description="PDB, mmCIF, SDF, MOL, MOL2, PDBQT, XYZ or FASTA file"),
    projectId: str = Form(...),
    name: str | None = Form(None),
    kind: str | None = Form(None, description="protein | ligand | complex | receptor | pose | library"),
    format: str | None = Form(None, description="Override format detection"),
) -> ImportResultOut:
    data = await _read_upload(file, settings.max_upload_bytes)
    outcome = import_structure(
        session,
        project_id=projectId,
        data=data,
        filename=file.filename or "structure",
        declared_format=format,
        name=name,
        kind=kind,
        source="uploaded",
        store=store,
    )
    detail = structure_detail_payload(session, outcome.record.id)
    return ImportResultOut(
        structure=detail,
        warnings=outcome.record.warnings or [],
        statistics=outcome.parsed.summary(),
        ligand=detail.get("ligand"),
        packetUrl=f"/api/structures/{outcome.record.id}/packet",
        provenance=outcome.record.provenance or {},
    )


@router.post(
    "/fetch-rcsb",
    response_model=ImportResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Fetch a structure from the RCSB PDB by identifier",
)
async def fetch_rcsb(
    payload: FetchRequest,
    session: DbSession,
    store: StoreDep,
) -> ImportResultOut:
    entry = await fetch_entry(payload.entryId, fmt=payload.format)
    display_name = payload.name or (entry.title or entry.entry_id)
    outcome = import_structure(
        session,
        project_id=payload.projectId,
        data=entry.data,
        filename=entry.filename,
        declared_format=entry.format,
        name=display_name[:200],
        source="rcsb",
        store=store,
        source_metadata={
            "entryId": entry.entry_id,
            "url": entry.url,
            "title": entry.title,
            "classification": entry.classification,
            "retrievedAt": None,
        },
    )
    detail = structure_detail_payload(session, outcome.record.id)
    return ImportResultOut(
        structure=detail,
        warnings=outcome.record.warnings or [],
        statistics=outcome.parsed.summary(),
        ligand=detail.get("ligand"),
        packetUrl=f"/api/structures/{outcome.record.id}/packet",
        provenance=outcome.record.provenance or {},
    )


@router.get("", response_model=StructureListOut, summary="List structures in a project")
def list_structures(
    session: DbSession,
    projectId: str = Query(...),
    kind: str | None = Query(default=None),
) -> StructureListOut:
    query = select(Structure).where(Structure.project_id == projectId)
    if kind:
        query = query.where(Structure.kind == kind)
    rows = session.scalars(query.order_by(Structure.created_at)).all()
    return StructureListOut(
        items=[StructureOut.model_validate(row, from_attributes=True) for row in rows],
        total=len(rows),
    )


@router.get("/{structure_id}", response_model=StructureDetailOut, summary="Structure detail with warnings")
def structure_detail(structure_id: str, session: DbSession) -> StructureDetailOut:
    return StructureDetailOut(**structure_detail_payload(session, structure_id))


@router.get("/{structure_id}/packet", summary="Viewer packet (typed-array payload)")
def structure_packet(structure_id: str, session: DbSession, store: StoreDep) -> dict:
    return build_packet_for(session, structure_id, store=store)


@router.get("/{structure_id}/surface", response_model=SurfaceOut, summary="Generate a molecular surface")
def structure_surface(
    structure_id: str,
    session: DbSession,
    store: StoreDep,
    settings: AppSettings,
    mode: str = Query("sas", pattern="^(vdw|sas)$"),
    probeRadius: float = Query(1.4, ge=0.0, le=5.0),
    gridSpacing: float | None = Query(None, ge=0.35, le=3.0),
    includeHydrogens: bool = Query(False),
    useCache: bool = Query(True),
) -> SurfaceOut:
    """Synchronous surface generation (cached on disk by structure hash + parameters).

    Use ``POST /api/structures/{id}/surface/jobs`` for very large structures.
    """
    record_row, parsed = load_parsed(session, structure_id, store=store)
    request = SurfaceRequest(
        structure_path=record_row.file_path,
        structure_format=record_row.format,
        structure_sha256=record_row.file_sha256,
        mode=mode,  # type: ignore[arg-type]
        probe_radius=probeRadius,
        grid_spacing=gridSpacing or settings.surface_grid_spacing,
        include_hydrogens=includeHydrogens,
        use_cache=useCache,
    )
    stats, _cache_path = generate_and_cache(parsed, request, store)
    payload = mesh_payload_from_stats(stats)
    return SurfaceOut(
        structureId=structure_id,
        encoding=payload["encoding"],
        vertexCount=payload["vertexCount"],
        triangleCount=payload["triangleCount"],
        positions=payload["positions"],
        normals=payload["normals"],
        indices=payload["indices"],
        stats=stats,
    )


@router.post(
    "/{structure_id}/surface/jobs",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a molecular surface in the background",
)
def structure_surface_job(
    structure_id: str,
    session: DbSession,
    settings: AppSettings,
    payload: SurfaceParams,
) -> JobOut:
    record_row = get_structure(session, structure_id)
    request = SurfaceRequest(
        structure_path=record_row.file_path,
        structure_format=record_row.format,
        structure_sha256=record_row.file_sha256,
        mode=payload.mode,
        probe_radius=payload.probeRadius,
        grid_spacing=payload.gridSpacing or settings.surface_grid_spacing,
        include_hydrogens=payload.includeHydrogens,
        use_cache=payload.useCache,
    )
    job = get_job_manager().submit(
        kind="generate_surface",
        params=request.__dict__,
        project_id=record_row.project_id,
        session=session,
    )
    return JobOut.model_validate(job, from_attributes=True)


@router.get("/{structure_id}/export", summary="Export a structure in another format")
def export_structure_endpoint(
    structure_id: str,
    session: DbSession,
    store: StoreDep,
    format: str = Query("pdb", pattern="^(pdb|mmcif|sdf|mol|mol2|xyz)$"),
) -> PlainTextResponse:
    content, filename = export_structure_content(session, structure_id, format, store=store)
    return PlainTextResponse(
        content,
        media_type="chemical/x-pdb" if format == "pdb" else "text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-MolDock-Filename": filename,
        },
    )


@router.delete("/{structure_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a structure")
def delete_structure_endpoint(structure_id: str, session: DbSession, store: StoreDep) -> None:
    delete_structure(session, structure_id, store=store)
