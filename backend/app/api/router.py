"""API router aggregation.

Every route lives under ``/api`` so the SPA can be served from a different origin
(or a static host) without path rewriting.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, jobs, ligands, projects, structures
from app.api.routes.binding_sites import router as binding_sites_router
from app.api.routes.docking import router as docking_router
from app.api.routes.preparation import router as preparation_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(jobs.router)
api_router.include_router(ligands.router)
api_router.include_router(preparation_router)
api_router.include_router(binding_sites_router)
api_router.include_router(docking_router)
api_router.include_router(projects.router)
api_router.include_router(structures.router)

__all__ = ["api_router"]
