"""Project endpoints."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, StoreDep
from app.core.errors import NotFoundError
from app.db.models import Job, Ligand, Project, Structure
from app.schemas.projects import (
    ProjectCounts,
    ProjectCreate,
    ProjectExportOut,
    ProjectListOut,
    ProjectOut,
    ProjectUpdate,
)
from app.services.provenance import record, software_identity, tool_versions

router = APIRouter(prefix="/projects", tags=["projects"])


def _counts(session: DbSession, project_id: str) -> ProjectCounts:
    return ProjectCounts(
        structures=session.scalar(
            select(func.count()).select_from(Structure).where(Structure.project_id == project_id)
        )
        or 0,
        ligands=session.scalar(
            select(func.count()).select_from(Ligand).where(Ligand.project_id == project_id)
        )
        or 0,
        jobs=session.scalar(select(func.count()).select_from(Job).where(Job.project_id == project_id)) or 0,
    )


def _to_out(session: DbSession, project: Project, *, with_counts: bool = True) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description or "",
        settings=project.settings or {},
        createdAt=project.created_at,
        updatedAt=project.updated_at,
        counts=_counts(session, project.id) if with_counts else None,
    )


def _get_project(session: DbSession, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED, summary="Create a project")
def create_project(payload: ProjectCreate, session: DbSession) -> ProjectOut:
    project = Project(
        name=payload.name.strip(),
        description=payload.description,
        settings=payload.settings,
        origin={"software": software_identity()},
    )
    session.add(project)
    session.flush()
    record(
        session,
        action="create",
        entity_type="project",
        entity_id=project.id,
        project_id=project.id,
        outputs={"name": project.name},
    )
    session.commit()
    session.refresh(project)
    return _to_out(session, project, with_counts=False)


@router.get("", response_model=ProjectListOut, summary="List projects")
def list_projects(
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ProjectListOut:
    total = session.scalar(select(func.count()).select_from(Project)) or 0
    projects = session.scalars(
        select(Project).order_by(Project.updated_at.desc()).limit(limit).offset(offset)
    ).all()
    return ProjectListOut(items=[_to_out(session, project) for project in projects], total=total)


@router.get("/{project_id}", response_model=ProjectOut, summary="Get a project")
def get_project(project_id: str, session: DbSession) -> ProjectOut:
    return _to_out(session, _get_project(session, project_id))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Update a project")
def update_project(project_id: str, payload: ProjectUpdate, session: DbSession) -> ProjectOut:
    project = _get_project(session, project_id)
    if payload.name is not None:
        project.name = payload.name.strip()
    if payload.description is not None:
        project.description = payload.description
    if payload.settings is not None:
        project.settings = payload.settings
    record(
        session,
        action="update",
        entity_type="project",
        entity_id=project.id,
        project_id=project.id,
        params=payload.model_dump(exclude_none=True),
    )
    session.commit()
    session.refresh(project)
    return _to_out(session, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a project")
def delete_project(project_id: str, session: DbSession, store: StoreDep) -> None:
    project = _get_project(session, project_id)
    session.delete(project)
    session.commit()
    store.delete_project(project_id)


@router.get("/{project_id}/export", response_model=ProjectExportOut, summary="Export a project archive")
def export_project(project_id: str, session: DbSession, store: StoreDep) -> ProjectExportOut:
    """Write a portable ``.moldock.zip`` with metadata and every stored artefact."""
    project = _get_project(session, project_id)
    structures = session.scalars(
        select(Structure).where(Structure.project_id == project_id).order_by(Structure.created_at)
    ).all()
    ligands = session.scalars(select(Ligand).where(Ligand.project_id == project_id)).all()

    manifest = {
        "format": "moldock-project",
        "formatVersion": 1,
        "software": software_identity(),
        "toolVersions": tool_versions(),
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "createdAt": project.created_at.isoformat(),
            "settings": project.settings,
        },
        "structures": [
            {
                "id": structure.id,
                "name": structure.name,
                "kind": structure.kind,
                "format": structure.format,
                "source": structure.source,
                "sha256": structure.file_sha256,
                "atoms": structure.atoms_count,
                "file": structure.file_path,
                "warnings": structure.warnings,
                "provenance": structure.provenance,
            }
            for structure in structures
        ],
        "ligands": [
            {
                "id": ligand.id,
                "name": ligand.name,
                "smiles": ligand.smiles,
                "formula": ligand.formula,
                "molecularWeight": ligand.molecular_weight,
                "structureId": ligand.structure_id,
                "descriptorSource": ligand.descriptor_source,
            }
            for ligand in ligands
        ],
    }

    buffer = io.BytesIO()
    contents: list[str] = ["manifest.json"]
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        for structure in structures:
            try:
                path = store.absolute(structure.file_path)
            except Exception:  # noqa: BLE001 - never fail an export on one bad path
                continue
            if path.exists():
                member = f"structures/{Path(structure.file_path).name}"
                archive.write(path, member)
                contents.append(member)

    artifact = store.store_bytes(project_id, "exports", f"{project.name[:40] or 'project'}.moldock.zip", buffer.getvalue())
    record(
        session,
        action="export",
        entity_type="project",
        entity_id=project.id,
        project_id=project.id,
        outputs={"archive": artifact.relative_path, "contents": contents, "bytes": artifact.size_bytes},
    )
    session.commit()
    return ProjectExportOut(
        projectId=project.id,
        archivePath=artifact.relative_path,
        sizeBytes=artifact.size_bytes,
        contents=contents,
        manifest=manifest,
    )
