"""Health and capability reporting.

The central promise of ``/api/health`` is honesty: it must report which
scientific tools are really present, and any feature that depends on a missing
tool must say so instead of failing silently or pretending to work.
"""

from __future__ import annotations

import pytest

REQUIRED_FIELDS = ("key", "label", "category", "status")


def test_health_reports_the_application(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["application"] == "MolDock Studio"
    assert body["version"]
    assert body["environment"] == "test"
    assert body["database"] == "sqlite"
    assert body["dataDirectory"]


def test_health_lists_the_capabilities_the_app_needs(client) -> None:
    capabilities = {cap["key"]: cap for cap in client.get("/api/health").json()["capabilities"]}
    for key in ("python", "rdkit", "gemmi", "numpy", "scipy", "scikit-image"):
        assert key in capabilities, key
    for capability in capabilities.values():
        for field in REQUIRED_FIELDS:
            assert capability[field], f"{capability['key']}.{field}"


def test_core_capabilities_are_available_in_the_test_environment(client) -> None:
    capabilities = {cap["key"]: cap for cap in client.get("/api/health").json()["capabilities"]}
    # These are hard dependencies; if one is missing the test environment is
    # broken and every downstream test would be meaningless.
    for key in ("rdkit", "gemmi", "numpy", "scipy", "scikit-image", "biopython"):
        assert capabilities[key]["status"] == "available", capabilities[key]
        assert "remediation" not in capabilities[key]


def test_missing_capabilities_carry_actionable_remediation(client) -> None:
    capabilities = {cap["key"]: cap for cap in client.get("/api/health").json()["capabilities"]}
    # Vina has no macOS arm64 wheel, and Meeko is an optional extra: whatever the
    # machine, an unavailable tool must explain how to get it.
    for capability in capabilities.values():
        if capability["status"] == "unavailable":
            assert capability.get("remediation"), capability["key"]


def test_docking_is_reported_as_unavailable_without_vina(client) -> None:
    capabilities = {cap["key"]: cap for cap in client.get("/api/health").json()["capabilities"]}
    docking = capabilities["docking"]
    # Docking engine adapter is implemented, but Vina binary is not installed
    # on macOS arm64, so the feature is "unavailable" with remediation.
    assert docking["status"] == "unavailable"
    assert "Vina" in docking["remediation"]


def test_roadmap_phases_are_reported(client) -> None:
    phases = client.get("/api/health").json()["phases"]
    assert len(phases) >= 6
    ids = [phase["id"] for phase in phases]
    assert ids[0] == "phase-0"
    for phase in phases:
        assert phase["name"]
        assert phase["status"] in {"implemented", "in_progress", "pending"}
        assert phase["summary"]
        assert isinstance(phase["pending"], list)


def test_phases_report_what_is_actually_finished(client) -> None:
    phases = {phase["id"]: phase for phase in client.get("/api/health").json()["phases"]}
    assert phases["phase-0"]["status"] == "implemented"
    assert phases["phase-1"]["status"] == "implemented"
    # Nothing past Phase 1 may claim to be implemented.
    for phase_id in ("phase-2", "phase-3", "phase-4", "phase-5", "phase-6"):
        assert phases[phase_id]["status"] == "pending", phase_id


def test_job_handlers_are_advertised(client) -> None:
    handlers = client.get("/api/health").json()["handlers"]
    assert "generate_surface" in handlers
    assert "pipeline_self_test" in handlers
    assert all(description for description in handlers.values())


def test_limits_reflect_configuration(client) -> None:
    limits = client.get("/api/health").json()["limits"]
    assert limits["maxConcurrentJobs"] == 2  # set by conftest
    assert limits["maxUploadMb"] > 0
    assert limits["maxAtoms"] > 0
    assert limits["jobTimeoutSeconds"] > 0


@pytest.mark.parametrize("path", ["/api/health", "/openapi.json", "/docs"])
def test_public_endpoints_are_reachable(client, path: str) -> None:
    assert client.get(path).status_code == 200
