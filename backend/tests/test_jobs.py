"""Background job pipeline: submission, progress, cancellation, timeout, logs.

The job layer is real (isolated child processes, a durable queue in the database
and a polling dispatcher), so it is tested as such rather than mocked.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.errors import MolDockError
from app.services.jobs.manager import get_job_manager

TERMINAL = {"completed", "failed", "cancelled"}
ACTIVE = {"queued", "preparing", "running"}


def wait_terminal(client, job_id: str, *, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["state"] in TERMINAL:
            return last
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s; last state {last}")


def wait_for_state(client, job_id: str, states: set[str], *, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] in states:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {states}")


# --- submission and completion ---------------------------------------------
def test_self_test_job_completes_and_reports_progress(client, project) -> None:
    response = client.post(
        "/api/jobs/self-test",
        json={"projectId": project["id"], "steps": 3, "secondsPerStep": 0.05},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["state"] in ACTIVE
    assert job["kind"] == "pipeline_self_test"

    finished = wait_terminal(client, job["id"])
    assert finished["state"] == "completed"
    assert finished["progress"] == pytest.approx(1.0)
    assert finished["result"]["steps"] == 3
    assert finished["error"] == {}
    assert finished["finishedAt"]
    # The child process really ran: provenance names the handler.
    assert finished["provenance"]["handler"].endswith("pipeline_self_test_job")


def test_job_log_is_captured(client, project) -> None:
    job = client.post(
        "/api/jobs/self-test",
        json={"projectId": project["id"], "steps": 2, "secondsPerStep": 0.02},
    ).json()
    wait_terminal(client, job["id"])

    log = client.get(f"/api/jobs/{job['id']}/log")
    assert log.status_code == 200
    body = log.json()
    assert body["available"] is True
    assert isinstance(body["text"], str)
    assert body["truncated"] is False


def test_job_appears_in_the_listing(client, project) -> None:
    job = client.post(
        "/api/jobs/self-test",
        json={"projectId": project["id"], "steps": 1, "secondsPerStep": 0.0},
    ).json()
    wait_terminal(client, job["id"])

    listing = client.get("/api/jobs", params={"projectId": project["id"]}).json()
    assert listing["total"] >= 1
    assert any(item["id"] == job["id"] for item in listing["items"])


def test_job_handlers_are_lists(client) -> None:
    handlers = client.get("/api/jobs/handlers").json()
    assert "generate_surface" in handlers
    assert "pipeline_self_test" in handlers


# --- cancellation -----------------------------------------------------------
def test_cancel_a_running_job(client, project) -> None:
    job = client.post(
        "/api/jobs/self-test",
        json={"projectId": project["id"], "steps": 60, "secondsPerStep": 0.5},
    ).json()

    # Wait until the worker process is actually running before cancelling.
    wait_for_state(client, job["id"], {"running", "preparing"})
    cancelled = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["jobId"] == job["id"]

    finished = wait_terminal(client, job["id"])
    assert finished["state"] == "cancelled"
    assert finished["cancelRequested"] is True


def test_cancelling_a_finished_job_is_a_conflict(client, project) -> None:
    job = client.post(
        "/api/jobs/self-test",
        json={"projectId": project["id"], "steps": 1, "secondsPerStep": 0.0},
    ).json()
    wait_terminal(client, job["id"])

    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


# --- timeout ----------------------------------------------------------------
def test_a_job_that_overruns_its_timeout_is_stopped(client, project) -> None:
    manager = get_job_manager()
    original = manager.settings
    manager.settings = original.model_copy(update={"job_timeout_seconds": 1})
    try:
        job = client.post(
            "/api/jobs/self-test",
            json={"projectId": project["id"], "steps": 60, "secondsPerStep": 0.5},
        ).json()
        finished = wait_terminal(client, job["id"], timeout=30.0)
    finally:
        manager.settings = original

    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "job_timeout"
    assert "timeout" in finished["error"]["message"].lower()


# --- validation -------------------------------------------------------------
def test_unknown_job_kind_is_rejected_by_the_manager() -> None:
    with pytest.raises(MolDockError):
        get_job_manager().submit(kind="not_a_real_job", params={})


def test_self_test_validates_its_parameters(client, project) -> None:
    assert (
        client.post(
            "/api/jobs/self-test",
            json={"projectId": project["id"], "steps": 0, "secondsPerStep": 0.1},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/jobs/self-test",
            json={"projectId": project["id"], "steps": 9999, "secondsPerStep": 0.1},
        ).status_code
        == 422
    )


def test_unknown_job_returns_404(client) -> None:
    response = client.get("/api/jobs/job_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- the real heavy job -----------------------------------------------------
@pytest.mark.slow
def test_surface_job_produces_a_mesh(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "1UBQ.pdb", kind="protein")
    structure_id = body["structure"]["id"]

    response = client.post(
        f"/api/structures/{structure_id}/surface/jobs",
        json={"mode": "vdw", "gridSpacing": 1.2, "useCache": False},
    )
    assert response.status_code == 202, response.text
    job = response.json()

    finished = wait_terminal(client, job["id"], timeout=300.0)
    assert finished["state"] == "completed", finished
    assert finished["result"]["cachePath"]
    assert finished["result"]["stats"]["mode"] == "vdw"
    assert finished["result"]["stats"]["triangles"] > 0


@pytest.mark.slow
def test_synchronous_surface_matches_the_job_result(
    client, project, sample_data: Path, import_structure
) -> None:
    body = import_structure(project["id"], sample_data / "1UBQ.pdb", kind="protein")
    structure_id = body["structure"]["id"]

    sync = client.get(
        f"/api/structures/{structure_id}/surface",
        params={"mode": "vdw", "gridSpacing": 1.2},
    )
    assert sync.status_code == 200, sync.text
    payload = sync.json()

    import base64

    import numpy as np

    vertices = np.frombuffer(base64.b64decode(payload["positions"]), dtype="<f4")
    indices = np.frombuffer(base64.b64decode(payload["indices"]), dtype="<u4")
    normals = np.frombuffer(base64.b64decode(payload["normals"]), dtype="<f4")
    assert payload["encoding"] == "base64"
    assert vertices.size == payload["vertexCount"] * 3
    assert indices.size == payload["triangleCount"] * 3
    assert normals.size == payload["vertexCount"] * 3
    assert indices.max() < payload["vertexCount"]
    assert payload["stats"]["triangles"] == payload["triangleCount"]
