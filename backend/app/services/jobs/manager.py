"""Background job manager.

Design
------
* Jobs are rows in the ``jobs`` table; the queue *is* the table, so a restart
  never loses track of work.
* Execution happens in an isolated child process (``spawn``), with stdout/stderr
  captured to a per-job log file, so a scientific backend cannot take the API
  process down with it.
* A single dispatcher thread inside the API process polls queued and running
  jobs, enforces the concurrency limit, applies cancellation and timeouts, and
  records the terminal state.

State machine::

    queued -> preparing -> running -> completed | failed | cancelled
"""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, JobError, MolDockError, NotFoundError
from app.db.models import Job
from app.db.session import session_scope
from app.services.jobs.progress import read_progress
from app.services.jobs.registry import registered_handlers
from app.services.provenance import software_identity, tool_versions
from app.services.store import ArtifactStore

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"completed", "failed", "cancelled"}
ACTIVE_STATES = {"preparing", "running"}
QUEUED = "queued"
TERMINATE_GRACE_SECONDS = 5.0


@dataclass
class RunningJob:
    job_id: str
    process: mp.process.BaseProcess
    started_at: float
    log_path: Path
    progress_path: Path
    result_path: Path
    last_progress: float
    last_message: str
    terminating: bool = False
    terminate_deadline: float = 0.0


class JobManager:
    """Owns the dispatcher thread and every running child process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = ArtifactStore(self.settings)
        self._lock = threading.RLock()
        self._running: dict[str, RunningJob] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ctx = mp.get_context("spawn")

    # --- lifecycle --------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="moldock-job-dispatcher", daemon=True)
            self._thread.start()
        self._recover_interrupted_jobs()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout=timeout)

    def _recover_interrupted_jobs(self) -> None:
        """Mark jobs that were running when the server stopped."""
        with session_scope() as session:
            stale = session.scalars(
                select(Job).where(Job.state.in_(ACTIVE_STATES | {QUEUED}))
            ).all()
            for job in stale:
                if job.state == QUEUED:
                    continue
                job.state = "failed"
                job.error = {
                    "code": "interrupted",
                    "message": "The server stopped while this job was running.",
                    "remediation": "Resubmit the job.",
                }
                job.finished_at = job.updated_at

    # --- submission -------------------------------------------------------
    def submit(
        self,
        *,
        kind: str,
        params: dict[str, Any],
        project_id: str | None = None,
        session=None,
    ) -> Job:
        """Create a queued job. The dispatcher picks it up automatically."""
        if kind not in registered_handlers():
            raise MolDockError(
                f"Unknown job kind '{kind}'.",
                detail={"registered": sorted(registered_handlers())},
            )
        job = Job(
            project_id=project_id,
            kind=kind,
            state=QUEUED,
            params=params,
            provenance={
                "software": software_identity(),
                "toolVersions": tool_versions(),
                "handler": registered_handlers()[kind].target,
            },
        )
        job.queued_at = job.created_at
        if session is not None:
            session.add(job)
            session.commit()
        else:
            with session_scope() as inner:
                inner.add(job)
        logger.info("queued job %s (%s)", job.id, kind)
        return job

    def cancel(self, job_id: str, *, session=None) -> Job:
        """Request cancellation. Queued jobs are cancelled immediately."""
        def _apply(session_) -> Job:
            job = session_.get(Job, job_id)
            if job is None:
                raise NotFoundError(f"Job '{job_id}' does not exist.")
            if job.state in TERMINAL_STATES:
                raise ConflictError(
                    f"Job '{job_id}' is already {job.state}.",
                    detail={"state": job.state},
                )
            job.cancel_requested = True
            if job.state == QUEUED:
                job.state = "cancelled"
                job.finished_at = job.updated_at
                job.message = "Cancelled before starting."
            return job

        if session is not None:
            job = _apply(session)
            session.commit()
        else:
            with session_scope() as inner:
                job = _apply(inner)
            job = job  # detached copy carries the fields we need

        if job.state != "cancelled":
            self._terminate(job_id)
        return job

    # --- dispatch loop ----------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the dispatcher must never die
                logger.exception("job dispatcher tick failed")
            self._stop.wait(0.4)

    def tick(self) -> None:
        """One dispatcher iteration (also used directly by tests)."""
        self._poll_running()
        self._dispatch_queued()

    def _dispatch_queued(self) -> None:
        with self._lock:
            capacity = max(0, self.settings.max_concurrent_jobs - len(self._running))
        if capacity == 0:
            return
        with session_scope() as session:
            queued = session.scalars(
                select(Job).where(Job.state == QUEUED).order_by(Job.created_at).limit(capacity)
            ).all()
            job_ids = [job.id for job in queued]
        for job_id in job_ids:
            self._start(job_id)

    def _start(self, job_id: str) -> None:
        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is None or job.state != QUEUED or job.cancel_requested:
                if job is not None and job.cancel_requested:
                    job.state = "cancelled"
                    job.finished_at = job.updated_at
                return
            job.state = "preparing"
            job.started_at = job.updated_at
            kind = job.kind
            params = dict(job.params or {})
            job.message = "Starting worker process"
            job.pid = None

        directory = self.store.job_dir(job_id)
        log_path = directory / "job.log"
        progress_path = directory / "progress.jsonl"
        result_path = directory / "result.json"
        for path in (progress_path, result_path):
            if path.exists():
                path.unlink()

        process = self._ctx.Process(
            target=_child_entry,
            args=(job_id, kind, params, str(log_path), str(progress_path), str(result_path)),
            name=f"moldock-job-{job_id}",
            daemon=True,
        )
        process.start()

        with self._lock:
            self._running[job_id] = RunningJob(
                job_id=job_id,
                process=process,
                started_at=time.monotonic(),
                log_path=log_path,
                progress_path=progress_path,
                result_path=result_path,
                last_progress=0.0,
                last_message="",
            )

        with session_scope() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.state = "running"
                job.pid = process.pid
                job.log_path = str(log_path)
                job.message = "Worker process started"
        logger.info("job %s started (pid=%s)", job_id, process.pid)

    def _poll_running(self) -> None:
        with self._lock:
            active = list(self._running.values())

        for entry in active:
            progress = read_progress(entry.progress_path)
            self._update_from_progress(entry, progress)

            with session_scope() as session:
                job = session.get(Job, entry.job_id)
                if job is None:
                    continue
                cancel_requested = job.cancel_requested
                timeout = self.settings.job_timeout_seconds
                started_at = job.started_at

            elapsed = time.monotonic() - entry.started_at
            if cancel_requested and not entry.terminating:
                logger.info("job %s cancel requested; terminating child", entry.job_id)
                self._terminate(entry.job_id, reason="cancelled")
                continue
            if timeout and elapsed > timeout and not entry.terminating:
                logger.warning("job %s exceeded timeout of %ss", entry.job_id, timeout)
                self._terminate(entry.job_id, reason="timeout")
                continue

            if entry.terminating:
                if time.monotonic() > entry.terminate_deadline and entry.process.is_alive():
                    entry.process.kill()
                    entry.process.join(timeout=2.0)
                continue

            if not entry.process.is_alive():
                entry.process.join(timeout=1.0)
                self._finalise(entry)
            del started_at

    def _update_from_progress(self, entry: RunningJob, progress: dict[str, Any]) -> None:
        value = progress.get("progress")
        message = progress.get("message") or ""
        state = progress.get("state")
        if value is None and not message and not state:
            return
        if value is not None and abs(float(value) - entry.last_progress) < 0.005 and message == entry.last_message:
            return
        entry.last_progress = float(value) if value is not None else entry.last_progress
        entry.last_message = message or entry.last_message
        with session_scope() as session:
            job = session.get(Job, entry.job_id)
            if job is None or job.state in TERMINAL_STATES:
                return
            job.progress = entry.last_progress
            if message:
                job.message = message
            if state in {"preparing", "running"}:
                job.state = state

    def _terminate(self, job_id: str, *, reason: str = "cancelled") -> None:
        with self._lock:
            entry = self._running.get(job_id)
        if entry is None:
            return
        entry.terminating = True
        entry.terminate_deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
        if entry.process.is_alive():
            entry.process.terminate()
        entry.process.join(timeout=TERMINATE_GRACE_SECONDS)
        if entry.process.is_alive():  # pragma: no cover - SIGKILL fallback
            entry.process.kill()
            entry.process.join(timeout=2.0)
        self._finalise(entry, forced_reason=reason)

    def _finalise(self, entry: RunningJob, *, forced_reason: str | None = None) -> None:
        with self._lock:
            self._running.pop(entry.job_id, None)

        payload: dict[str, Any] | None = None
        if entry.result_path.exists():
            try:
                payload = json.loads(entry.result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = None

        log_tail = self._log_tail(entry.log_path)
        exit_code = entry.process.exitcode

        with session_scope() as session:
            job = session.get(Job, entry.job_id)
            if job is None or job.state in TERMINAL_STATES:
                return
            job.pid = None
            job.finished_at = job.updated_at
            if payload and payload.get("ok"):
                job.state = "completed"
                job.progress = 1.0
                job.result = payload.get("result", {})
                job.message = job.message or "Completed"
            elif forced_reason == "cancelled":
                job.state = "cancelled"
                job.message = "Cancelled by user."
            elif forced_reason == "timeout":
                job.state = "failed"
                job.error = {
                    "code": "job_timeout",
                    "message": f"The job exceeded the {self.settings.job_timeout_seconds}s timeout and was stopped.",
                    "remediation": "Raise MOLDOCK_JOB_TIMEOUT_SECONDS or reduce the calculation size.",
                }
            elif payload and not payload.get("ok"):
                job.state = "failed"
                job.error = payload.get("error", {"code": "job_failed", "message": "Job failed."})
            else:
                job.state = "failed"
                job.error = {
                    "code": "job_crashed",
                    "message": f"The worker process exited with code {exit_code} without a result.",
                    "detail": {"logTail": log_tail},
                    "remediation": "Inspect the job log; the scientific backend may be missing.",
                }
            if log_tail and not job.error:
                job.result.setdefault("logTail", log_tail)

        logger.info("job %s finished as %s", entry.job_id, "completed" if payload and payload.get("ok") else "failed/cancelled")

    def _log_tail(self, path: Path, *, max_bytes: int = 4000) -> str:
        if not path.exists():
            return ""
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        return data[-max_bytes:].decode("utf-8", errors="replace")

    # --- introspection ----------------------------------------------------
    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def wait_for(self, job_id: str, *, timeout: float = 30.0) -> Job:
        """Block until a job reaches a terminal state (used by tests)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with session_scope() as session:
                job = session.get(Job, job_id)
                if job is not None and job.state in TERMINAL_STATES:
                    session.expunge(job)
                    return job
            time.sleep(0.1)
        raise JobError(
            f"Job '{job_id}' did not finish within {timeout}s.",
            detail={"jobId": job_id},
        )


def _child_entry(
    job_id: str, kind: str, params: dict[str, Any], log: str, progress: str, result: str
) -> None:
    """Import indirection so ``spawn`` only needs this module's path."""
    from app.services.jobs.child import child_main

    child_main(job_id, kind, params, log, progress, result)


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def get_job_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def reset_job_manager() -> None:
    """Test helper."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.stop()
        _manager = None
