"""FastAPI application factory.

Startup order matters and is deliberate:

1. Create the data directory and database tables.
2. Log the capability report so a missing scientific backend is visible in the
   console immediately, not at the moment a user clicks "Dock".
3. Start the background job manager.

There is no silent degradation anywhere: if a tool is missing, the capability
report says so and the endpoints that need it return HTTP 503 with remediation.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.core.capabilities import detect_capabilities
from app.core.config import get_settings
from app.core.errors import MolDockError
from app.core.logging import configure_logging
from app.db.session import init_db
from app.services.jobs.manager import get_job_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    init_db()

    capabilities = detect_capabilities(settings)
    unavailable = [cap for cap in capabilities if cap.status != "available"]
    for capability in capabilities:
        marker = "ok " if capability.status == "available" else "-- "
        version = capability.version or capability.location or capability.status
        logger.info("%s%-26s %s", marker, capability.label, version)
    if unavailable:
        logger.warning(
            "%d optional scientific capability(ies) unavailable; see /api/health for remediation.",
            len(unavailable),
        )
    logger.info("MolDock Studio %s ready (data: %s)", __version__, settings.resolved_data_dir)

    manager = get_job_manager()
    manager.settings = settings
    manager.start()
    app.state.job_manager = manager
    try:
        yield
    finally:
        manager.stop()
        logger.info("MolDock Studio shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="MolDock Studio API",
        version=__version__,
        description=(
            "Backend for MolDock Studio: molecular structure import and inspection, "
            "surface generation and (in later phases) preparation, docking and "
            "interaction analysis. Scoring-function outputs are computational "
            "estimates, not measured binding affinities."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-MolDock-Filename", "Content-Disposition"],
    )

    app.include_router(api_router)

    @app.exception_handler(MolDockError)
    async def _moldock_error(_request: Request, exc: MolDockError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.to_payload()})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "request_validation_error",
                    "message": "The request payload did not pass validation.",
                    "detail": {"errors": exc.errors()},
                }
            },
        )

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "application": "MolDock Studio",
            "version": __version__,
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
