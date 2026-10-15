"""Job endpoints: submit diagnostics, inspect progress, read logs, cancel."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.core.errors import NotFoundError
from app.db.models import Job
from app.schemas.jobs import CancelOut, JobListOut, JobLogOut, JobOut, SelfTestRequest
from app.services.jobs.manager import JobManager, get_job_manager
from app.services.jobs.registry import registered_handlers

router = APIRouter(prefix="/jobs", tags=["jobs"])

TERMINAL = {"completed", "failed", "cancelled"}


@router.get("", response_model=JobListOut, summary="List background jobs")
def list_jobs(
    session: DbSession,
    projectId: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> JobListOut:
    query = select(Job)
    if projectId:
        query = query.where(Job.project_id == projectId)
    if kind:
        query = query.where(Job.kind == kind)
    if state:
        query = query.where(Job.state == state)
    rows = session.scalars(query.order_by(Job.created_at.desc()).limit(limit)).all()
    total = session.scalar(select(func.count()).select_from(Job)) or 0
    running = (
        session.scalar(
            select(func.count()).select_from(Job).where(Job.state.in_(["queued", "preparing", "running"]))
        )
        or 0
    )
    return JobListOut(
        items=[JobOut.model_validate(row, from_attributes=True) for row in rows],
        total=total,
        running=running,
    )


@router.get("/handlers", summary="Registered job kinds")
def job_handlers() -> dict[str, str]:
    return {kind: spec.description for kind, spec in registered_handlers().items()}


@router.post(
    "/self-test",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a background-job diagnostic",
)
def self_test(payload: SelfTestRequest, session: DbSession) -> JobOut:
    """Verify the job pipeline (worker process, progress reporting, cancellation).

    This is a real diagnostic: it exercises the same code path used by surface
    generation and, later, docking.
    """
    job = get_job_manager().submit(
        kind="pipeline_self_test",
        params={"steps": payload.steps, "seconds_per_step": payload.secondsPerStep},
        project_id=payload.projectId,
        session=session,
    )
    return JobOut.model_validate(job, from_attributes=True)


@router.get("/{job_id}", response_model=JobOut, summary="Job status")
def get_job(job_id: str, session: DbSession) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job '{job_id}' does not exist.")
    return JobOut.model_validate(job, from_attributes=True)


@router.post("/{job_id}/cancel", response_model=CancelOut, summary="Cancel a job")
def cancel_job(job_id: str, session: DbSession) -> CancelOut:
    manager: JobManager = get_job_manager()
    job = manager.cancel(job_id, session=session)
    return CancelOut(jobId=job.id, state=job.state, message=job.message or "Cancellation requested.")


@router.get("/{job_id}/log", response_model=JobLogOut, summary="Job log (stdout/stderr tail)")
def job_log(job_id: str, session: DbSession, maxBytes: int = Query(default=20000, ge=100, le=200000)) -> JobLogOut:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError(f"Job '{job_id}' does not exist.")
    if not job.log_path:
        return JobLogOut(jobId=job.id, available=False, text="", truncated=False)
    path = Path(job.log_path)
    if not path.exists():
        return JobLogOut(jobId=job.id, available=False, text="", truncated=False)
    data = path.read_bytes()
    truncated = len(data) > maxBytes
    text = data[-maxBytes:].decode("utf-8", errors="replace")
    return JobLogOut(jobId=job.id, available=True, text=text, truncated=truncated)
