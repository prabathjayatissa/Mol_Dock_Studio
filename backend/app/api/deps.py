"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.store import ArtifactStore

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_artifact_store(settings: Settings = Depends(get_settings)) -> ArtifactStore:
    return ArtifactStore(settings)


StoreDep = Annotated[ArtifactStore, Depends(get_artifact_store)]
