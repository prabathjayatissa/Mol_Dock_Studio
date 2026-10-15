"""API router aggregation.

Every route lives under ``/api`` so the SPA can be served from a different origin
(or a static host) without path rewriting.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import health, jobs, ligands, projects, structures

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(structures.router)
api_router.include_router(ligands.router)
api_router.include_router(jobs.router)

__all__ = ["api_router"]
