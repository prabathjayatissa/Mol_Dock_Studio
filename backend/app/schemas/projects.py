"""Project schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    settings: dict[str, Any] | None = None


class ProjectCounts(BaseModel):
    structures: int = 0
    ligands: int = 0
    jobs: int = 0


class ProjectOut(ORMModel):
    id: str
    name: str
    description: str
    settings: dict[str, Any]
    createdAt: dt.datetime
    updatedAt: dt.datetime
    counts: ProjectCounts | None = None


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int


class ProjectExportOut(BaseModel):
    """Result of exporting a project as a portable archive."""

    projectId: str
    archivePath: str
    sizeBytes: int
    contents: list[str]
    manifest: dict[str, Any]
