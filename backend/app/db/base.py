"""SQLAlchemy declarative base and shared column mixins."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def new_id(prefix: str) -> str:
    """Stable, prefixed identifier (e.g. ``prj_3f8a1c0d9e2b``)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def id_factory(prefix: str):
    """Return a zero-argument callable suitable for a column ``default``."""

    def _make() -> str:
        return new_id(prefix)

    return _make


class Base(DeclarativeBase):
    """Declarative base for every MolDock Studio table."""

    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class IdMixin:
    id: Mapped[str] = mapped_column(String(48), primary_key=True)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
