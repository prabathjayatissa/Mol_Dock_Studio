"""System endpoints: health, capabilities and roadmap."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import AppSettings
from app.core.capabilities import detect_capabilities
from app.core.roadmap import PHASES
from app.schemas.health import HealthOut
from app.services.jobs.registry import registered_handlers

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthOut,
    response_model_exclude_none=True,
    summary="Service health and scientific capabilities",
)
def health(settings: AppSettings) -> HealthOut:
    """Report exactly which scientific tools are available on this machine.

    The frontend uses this to enable or disable workflows and to show the user a
    concrete remediation when something is missing (for example AutoDock Vina on
    macOS arm64). ``None`` fields are omitted so that ``remediation`` only appears
    when there is actually something to remediate.
    """
    capabilities = detect_capabilities(settings)
    database = settings.resolved_database_url.split("://", 1)[0]
    return HealthOut(
        status="ok",
        application="MolDock Studio",
        version=__version__,
        environment=settings.env,
        scientificBackendMode=settings.scientific_backend_mode,
        database=database,
        dataDirectory=str(settings.resolved_data_dir),
        capabilities=[capability.as_dict() for capability in capabilities],  # type: ignore[arg-type]
        phases=PHASES,  # type: ignore[arg-type]
        handlers={kind: spec.description for kind, spec in registered_handlers().items()},
        limits={
            "maxUploadMb": settings.max_upload_mb,
            "maxAtoms": settings.max_atoms,
            "jobTimeoutSeconds": settings.job_timeout_seconds,
            "maxConcurrentJobs": settings.max_concurrent_jobs,
            "defaultProbeRadius": settings.default_probe_radius,
            "surfaceGridSpacing": settings.surface_grid_spacing,
        },
    )
