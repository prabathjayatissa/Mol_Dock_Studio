"""Job schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel

JobState = Literal["queued", "preparing", "running", "completed", "failed", "cancelled"]


class JobOut(ORMModel):
    id: str
    projectId: str | None = None
    kind: str
    state: JobState
    progress: float
    message: str
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    logPath: str | None = None
    cancelRequested: bool
    pid: int | None = None
    queuedAt: dt.datetime | None = None
    startedAt: dt.datetime | None = None
    finishedAt: dt.datetime | None = None
    createdAt: dt.datetime
    provenance: dict[str, Any] = Field(default_factory=dict)


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    running: int


class JobLogOut(BaseModel):
    jobId: str
    available: bool
    text: str
    truncated: bool


class SelfTestRequest(BaseModel):
    projectId: str | None = None
    steps: int = Field(default=5, ge=1, le=60)
    secondsPerStep: float = Field(default=0.4, ge=0.0, le=30.0)


class CancelOut(BaseModel):
    jobId: str
    state: str
    message: str
