"""MolDock Studio: docking API routes (Phase 3).

Endpoints
---------
POST   /api/docking/run          Submit a docking job (background).
GET    /api/docking/jobs         List docking jobs for a project.
GET    /api/docking/jobs/{id}    Get a docking job's status and result.
GET    /api/docking/poses        List poses for a docking job.
GET    /api/docking/poses/{id}   Get a single pose's details.

Scientific honesty
------------------
Docking scores are approximate AutoDock Vina scoring-function outputs. They are
not measured binding affinities and must never be presented as clinical or
experimental evidence.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.db.models import DockingJob, DockingPose, Structure
from app.schemas.docking import (
    DockingJobOut,
    DockingPoseOut,
    DockingRunOut,
    DockingRunRequest,
)
from app.services.docking.engine import resolve_docking_engine
from app.services.jobs.manager import get_job_manager

router = APIRouter(prefix="/docking", tags=["docking"])


@router.post(
    "/run",
    response_model=DockingRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a molecular docking job (AutoDock Vina)",
)
def run_docking(
    payload: DockingRunRequest,
    session: DbSession,
) -> DockingRunOut:
    """Submit a docking calculation to the background job queue.

    The job runs AutoDock Vina in an isolated subprocess. Poll
    ``GET /api/docking/jobs/{id}`` for status and results.
    """
    # Resolve the project from the receptor structure.
    receptor = session.get(Structure, payload.receptorStructureId)
    if receptor is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(
            f"Receptor structure '{payload.receptorStructureId}' not found."
        )

    # Check Vina availability before queuing
    engine = resolve_docking_engine()
    if not engine.is_available():
        from app.core.errors import ValidationFailure

        raise ValidationFailure(
            "AutoDock Vina is not available on this machine.",
            detail={"engine": "vina", "binary": engine._binary},
            remediation=(
                "Install AutoDock Vina (linux/amd64 via Docker, or build from source) "
                "and set MOLDOCK_VINA_BINARY to its path."
            ),
        )

    manager = get_job_manager()
    job = manager.submit(
        kind="docking",
        params={
            "receptorStructureId": payload.receptorStructureId,
            "ligandStructureId": payload.ligandStructureId,
            "bindingSiteId": payload.bindingSiteId,
            "numModes": payload.numModes,
            "energyRange": payload.energyRange,
            "exhaustiveness": payload.exhaustiveness,
            "seed": payload.seed,
        },
        project_id=receptor.project_id,
        session=session,
    )
    return DockingRunOut(
        jobId=job.id,
        status=job.state,
        note=(
            "Docking scores are approximate AutoDock Vina scoring-function "
            "outputs, not measured binding affinities or clinical evidence."
        ),
    )


@router.get(
    "/jobs",
    response_model=list[DockingJobOut],
    summary="List docking jobs for a project",
)
def list_docking_jobs(
    session: DbSession,
    projectId: str = Query(...),
) -> list[DockingJobOut]:
    rows = (
        session.query(DockingJob)
        .filter(DockingJob.project_id == projectId)
        .order_by(DockingJob.created_at.desc())
        .all()
    )
    return [
        DockingJobOut(
            id=row.id,
            projectId=row.project_id,
            jobId=row.job_id,
            engine=row.engine,
            engineVersion=row.engine_version,
            receptorFile=row.receptor_file,
            ligandFile=row.ligand_file,
            config=row.config or {},
            command=row.command or [],
            outputFiles=row.output_files or [],
            summary=row.summary or {},
            createdAt=row.created_at,
        )
        for row in rows
    ]


@router.get(
    "/jobs/{job_id}",
    response_model=DockingJobOut,
    summary="Get a docking job's status",
)
def get_docking_job(
    job_id: str,
    session: DbSession,
) -> DockingJobOut:
    row = session.get(DockingJob, job_id)
    if row is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Docking job '{job_id}' not found.")
    return DockingJobOut(
        id=row.id,
        projectId=row.project_id,
        jobId=row.job_id,
        engine=row.engine,
        engineVersion=row.engine_version,
        receptorFile=row.receptor_file,
        ligandFile=row.ligand_file,
        config=row.config or {},
        command=row.command or [],
        outputFiles=row.output_files or [],
        summary=row.summary or {},
        createdAt=row.created_at,
    )


@router.get(
    "/poses",
    response_model=list[DockingPoseOut],
    summary="List poses for a docking job",
)
def list_docking_poses(
    session: DbSession,
    dockingJobId: str = Query(...),
) -> list[DockingPoseOut]:
    rows = (
        session.query(DockingPose)
        .filter(DockingPose.docking_job_id == dockingJobId)
        .order_by(DockingPose.rank.asc())
        .all()
    )
    return [
        DockingPoseOut(
            id=row.id,
            projectId=row.project_id,
            dockingJobId=row.docking_job_id,
            structureId=row.structure_id,
            poseIndex=row.pose_index,
            rank=row.rank,
            scoreKcalMol=row.score_kcal_mol,
            rmsdLowerBound=row.rmsd_lower_bound,
            rmsdUpperBound=row.rmsd_upper_bound,
            filePath=row.file_path,
            meta=row.meta or {},
            createdAt=row.created_at,
        )
        for row in rows
    ]


@router.get(
    "/poses/{pose_id}",
    response_model=DockingPoseOut,
    summary="Get a single pose's details",
)
def get_docking_pose(
    pose_id: str,
    session: DbSession,
) -> DockingPoseOut:
    row = session.get(DockingPose, pose_id)
    if row is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"Docking pose '{pose_id}' not found.")
    return DockingPoseOut(
        id=row.id,
        projectId=row.project_id,
        dockingJobId=row.docking_job_id,
        structureId=row.structure_id,
        poseIndex=row.pose_index,
        rank=row.rank,
        scoreKcalMol=row.score_kcal_mol,
        rmsdLowerBound=row.rmsd_lower_bound,
        rmsdUpperBound=row.rmsd_upper_bound,
        filePath=row.file_path,
        meta=row.meta or {},
        createdAt=row.created_at,
    )


__all__ = ["router"]
