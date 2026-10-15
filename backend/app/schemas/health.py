"""Health, capability and roadmap schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CapabilityOut(BaseModel):
    key: str
    label: str
    category: str
    status: str = Field(description="available | unavailable | not_implemented")
    version: str | None = None
    location: str | None = None
    mode: str | None = None
    remediation: str | None = None
    detail: str | None = None


class PhaseOut(BaseModel):
    id: str
    name: str
    status: str
    summary: str
    pending: list[str] = Field(default_factory=list)


class HealthOut(BaseModel):
    status: str
    application: str
    version: str
    environment: str
    scientificBackendMode: str
    database: str
    dataDirectory: str
    capabilities: list[CapabilityOut]
    phases: list[PhaseOut]
    handlers: dict[str, str] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
