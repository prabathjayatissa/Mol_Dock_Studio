"""Shared pytest fixtures.

Two rules make this suite safe and reproducible:

* Tests never touch a real data directory. ``MOLDOCK_DATA_DIR`` points at a
  fresh temporary directory created before the application is imported, so the
  database, artefacts and caches are per-run and disposable.
* Sample structures are the redistributable files committed under
  ``backend/app/data`` (RCSB PDB entries, public domain, plus RDKit-generated
  ligands). If they are missing the suite says exactly how to fetch them instead
  of silently skipping the scientific checks.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# --- environment (must be set before importing the application) -------------
_TEMP_DATA = Path(tempfile.mkdtemp(prefix="moldock-tests-"))
os.environ["MOLDOCK_ENV"] = "test"
os.environ["MOLDOCK_DATA_DIR"] = str(_TEMP_DATA)
os.environ["MOLDOCK_LOG_LEVEL"] = "WARNING"
os.environ["MOLDOCK_MAX_CONCURRENT_JOBS"] = "2"

from app.core.config import BACKEND_ROOT, get_settings  # noqa: E402

get_settings.cache_clear()

SAMPLE_DATA = BACKEND_ROOT / "app" / "data"

REQUIRED_SAMPLES = ("1UBQ.pdb", "3PTB.pdb", "benzamidine.sdf")


@pytest.fixture(scope="session")
def temp_data_dir() -> Path:
    return _TEMP_DATA


@pytest.fixture(scope="session")
def sample_data() -> Path:
    """Directory holding the redistributable sample structures."""
    missing = [name for name in REQUIRED_SAMPLES if not (SAMPLE_DATA / name).exists()]
    if missing:
        pytest.fail(
            "Sample structures are missing: "
            + ", ".join(missing)
            + f".\nFetch them with:  cd backend && .venv/bin/python -m app.cli fetch-test-data\n"
            f"(expected in {SAMPLE_DATA})"
        )
    return SAMPLE_DATA


@pytest.fixture(scope="session")
def client() -> Iterator[object]:
    """A TestClient with the application lifespan running (DB + job manager)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project(client) -> dict:
    """A fresh project per test, created through the public API."""
    response = client.post("/api/projects", json={"name": "Test project", "description": "pytest"})
    assert response.status_code == 201, response.text
    return response.json()


def _import_structure(client, project_id: str, path: Path, *, kind: str | None = None) -> dict:
    """Import a file from disk through the public API and return the JSON body."""
    data = {"projectId": project_id}
    if kind:
        data["kind"] = kind
    with path.open("rb") as handle:
        response = client.post(
            "/api/structures/import",
            files={"file": (path.name, handle, "chemical/x-pdb")},
            data=data,
        )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def import_structure(client):
    """``import_structure(project_id, path, kind=None) -> response body``."""

    def _import(project_id: str, path: Path, *, kind: str | None = None) -> dict:
        return _import_structure(client, project_id, path, kind=kind)

    return _import
