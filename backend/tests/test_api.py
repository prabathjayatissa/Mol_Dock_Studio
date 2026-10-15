"""End-to-end API flows through the real HTTP layer.

These tests exercise the contract the frontend depends on: create a project,
import a structure, download its packet, export it, and remove it. They run
against a real TestClient with the real database, artefact store and job
manager.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

NETWORK_ENABLED = os.environ.get("MOLDOCK_TEST_NETWORK") == "1"


# --- projects ---------------------------------------------------------------
def test_create_and_read_a_project(client) -> None:
    created = client.post("/api/projects", json={"name": "Kinase study", "description": "EGFR"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Kinase study"
    assert body["description"] == "EGFR"
    assert body["id"].startswith("prj_")
    assert body["counts"] is None  # counts are not computed on create

    fetched = client.get(f"/api/projects/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["counts"] == {"structures": 0, "ligands": 0, "jobs": 0}


def test_list_projects_reports_totals(client, project) -> None:
    listing = client.get("/api/projects")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] >= 1
    assert any(item["id"] == project["id"] for item in body["items"])


def test_update_project(client, project) -> None:
    updated = client.patch(f"/api/projects/{project['id']}", json={"name": "Renamed"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"


def test_delete_project(client, project) -> None:
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_project_name_is_required_and_bounded(client) -> None:
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.post("/api/projects", json={"name": "x" * 300}).status_code == 422


def test_unknown_project_returns_404(client) -> None:
    response = client.get("/api/projects/prj_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- structure import -------------------------------------------------------
def test_import_protein_and_inspect_it(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "1UBQ.pdb", kind="protein")
    structure = body["structure"]
    assert structure["kind"] == "protein"
    assert structure["format"] == "pdb"
    assert structure["atomsCount"] == 660
    assert structure["residuesCount"] == 134
    assert structure["chainsCount"] == 1
    assert structure["source"] == "uploaded"
    assert body["statistics"]["waters"] == 58
    assert body["packetUrl"] == f"/api/structures/{structure['id']}/packet"

    detail = client.get(f"/api/structures/{structure['id']}")
    assert detail.status_code == 200
    assert detail.json()["provenance"]["format"] == "pdb"
    assert detail.json()["provenance"]["importedAt"]


def test_import_complex_detects_bound_ligand(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "3PTB.pdb")
    assert body["structure"]["kind"] == "complex"
    chains = body["structure"]["chains"]
    assert len(chains) == 1
    assert chains[0]["kind"] == "polymer"


def test_import_ligand_creates_a_ligand_record(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "benzamidine.sdf")
    assert body["ligand"] is not None
    assert body["ligand"]["formula"] == "C7H8N2"

    ligands = client.get("/api/ligands", params={"projectId": project["id"]}).json()
    assert ligands["total"] == 1


def test_packet_endpoint_matches_the_import(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "1UBQ.pdb", kind="protein")
    structure_id = body["structure"]["id"]

    packet = client.get(f"/api/structures/{structure_id}/packet")
    assert packet.status_code == 200
    payload = packet.json()
    assert payload["packetVersion"] == 1
    assert payload["structure"]["atoms"] == 660
    assert len(payload["atoms"]["x"]) == 660
    assert len(payload["atoms"]["element"]) == 660
    assert payload["structure"]["bonds"] == len(payload["bonds"]["a"])


def test_list_structures_filters_by_kind(client, project, sample_data: Path, import_structure) -> None:
    import_structure(project["id"], sample_data / "1UBQ.pdb", kind="protein")
    import_structure(project["id"], sample_data / "benzamidine.sdf", kind="ligand")

    everything = client.get("/api/structures", params={"projectId": project["id"]}).json()
    assert everything["total"] == 2

    ligands = client.get(
        "/api/structures", params={"projectId": project["id"], "kind": "ligand"}
    ).json()
    assert ligands["total"] == 1
    assert ligands["items"][0]["kind"] == "ligand"


def test_import_rejects_unsupported_content(client, project) -> None:
    response = client.post(
        "/api/structures/import",
        files={"file": ("mystery.bin", b"\x89PNG\r\n\x1a\n\x00\x00", "application/octet-stream")},
        data={"projectId": project["id"]},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"


def test_import_into_a_missing_project_returns_404(client, sample_data: Path) -> None:
    with (sample_data / "1UBQ.pdb").open("rb") as handle:
        response = client.post(
            "/api/structures/import",
            files={"file": ("1UBQ.pdb", handle, "chemical/x-pdb")},
            data={"projectId": "prj_missing"},
        )
    assert response.status_code == 404


def test_import_rejects_an_invalid_kind(client, project, sample_data: Path) -> None:
    with (sample_data / "1UBQ.pdb").open("rb") as handle:
        response = client.post(
            "/api/structures/import",
            files={"file": ("1UBQ.pdb", handle, "chemical/x-pdb")},
            data={"projectId": project["id"], "kind": "sandwich"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failure"


# --- export -----------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["pdb", "mmcif", "xyz"])
def test_export_download_headers_and_content(
    client, project, sample_data: Path, import_structure, fmt: str
) -> None:
    body = import_structure(project["id"], sample_data / "benzamidine.sdf")
    structure_id = body["structure"]["id"]

    response = client.get(f"/api/structures/{structure_id}/export", params={"format": fmt})
    assert response.status_code == 200
    assert f".{fmt if fmt != 'mmcif' else 'cif'}" in response.headers["content-disposition"]
    assert response.headers["x-moldock-filename"]
    assert len(response.text) > 0


def test_export_rejects_an_unknown_format(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "benzamidine.sdf")
    response = client.get(
        f"/api/structures/{body['structure']['id']}/export", params={"format": "docx"}
    )
    # The query parameter is validated by FastAPI before the handler runs.
    assert response.status_code == 422


# --- deletion ---------------------------------------------------------------
def test_delete_structure_removes_it(client, project, sample_data: Path, import_structure) -> None:
    body = import_structure(project["id"], sample_data / "benzamidine.sdf")
    structure_id = body["structure"]["id"]

    assert client.delete(f"/api/structures/{structure_id}").status_code == 204
    assert client.get(f"/api/structures/{structure_id}").status_code == 404
    assert client.get(f"/api/structures/{structure_id}/packet").status_code == 404


def test_packet_for_unknown_structure_returns_404(client) -> None:
    response = client.get("/api/structures/str_missing/packet")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- project export ---------------------------------------------------------
def test_project_export_produces_a_portable_archive(client, project, sample_data: Path, import_structure) -> None:
    import_structure(project["id"], sample_data / "benzamidine.sdf")

    response = client.get(f"/api/projects/{project['id']}/export")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest"]["format"] == "moldock-project"
    assert body["manifest"]["formatVersion"] == 1
    assert len(body["manifest"]["structures"]) == 1
    assert len(body["manifest"]["ligands"]) == 1
    assert "manifest.json" in body["contents"]
    assert body["sizeBytes"] > 0


# --- RCSB fetch (opt-in; requires internet) ---------------------------------
@pytest.mark.network
@pytest.mark.skipif(not NETWORK_ENABLED, reason="set MOLDOCK_TEST_NETWORK=1 to run network tests")
def test_fetch_from_rcsb(client, project) -> None:
    response = client.post(
        "/api/structures/fetch-rcsb",
        json={"projectId": project["id"], "entryId": "1UBQ", "format": "pdb"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["structure"]["source"] == "rcsb"
    assert body["structure"]["atomsCount"] == 660
    assert body["provenance"]["sourceMetadata"]["entryId"] == "1UBQ"


@pytest.mark.network
@pytest.mark.skipif(not NETWORK_ENABLED, reason="set MOLDOCK_TEST_NETWORK=1 to run network tests")
def test_fetch_from_rcsb_rejects_a_bad_identifier(client, project) -> None:
    response = client.post(
        "/api/structures/fetch-rcsb",
        json={"projectId": project["id"], "entryId": "NOTANID", "format": "pdb"},
    )
    assert response.status_code in {404, 422, 502}


# --- OpenAPI ----------------------------------------------------------------
def test_openapi_document_is_valid(client) -> None:
    schema = json.loads(client.get("/openapi.json").text)
    assert schema["info"]["title"] == "MolDock Studio API"
    paths = schema["paths"]
    for expected in (
        "/api/health",
        "/api/projects",
        "/api/structures/import",
        "/api/structures/{structure_id}/packet",
        "/api/structures/{structure_id}/export",
        "/api/ligands/import",
        "/api/jobs/self-test",
    ):
        assert expected in paths, expected
