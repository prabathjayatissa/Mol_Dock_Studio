"""Job handler registry.

Handlers are referenced by ``"module:function"`` strings rather than by
callable, so they survive the ``spawn`` start method used by the job runner (the
child process imports the module itself).

Handler signature::

    def handler(params: dict, progress: ProgressReporter) -> dict

The returned dictionary is stored on the job as its result. Raise
:class:`app.core.errors.MolDockError` for expected failures (the code,
remediation and detail are preserved for the UI).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.errors import MolDockError


class Handler(Protocol):
    def __call__(self, params: dict[str, Any], progress: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HandlerSpec:
    kind: str
    target: str
    description: str
    phase: str


_HANDLERS: dict[str, HandlerSpec] = {}


def register_handler(kind: str, target: str, *, description: str = "", phase: str = "phase-1") -> HandlerSpec:
    if ":" not in target:
        raise ValueError(f"Handler target must be 'module:function', got '{target}'")
    spec = HandlerSpec(kind=kind, target=target, description=description, phase=phase)
    _HANDLERS[kind] = spec
    return spec


def registered_handlers() -> dict[str, HandlerSpec]:
    return dict(_HANDLERS)


def resolve_handler(kind: str) -> Callable[..., dict[str, Any]]:
    spec = _HANDLERS.get(kind)
    if spec is None:
        raise MolDockError(
            f"No job handler is registered for kind '{kind}'.",
            detail={"registered": sorted(_HANDLERS)},
        )
    module_name, function_name = spec.target.split(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, function_name)
    except AttributeError as exc:  # pragma: no cover - developer error
        raise MolDockError(f"Handler '{spec.target}' does not exist.") from exc


# --- built-in handlers ------------------------------------------------------
register_handler(
    "generate_surface",
    "app.services.jobs.handlers:generate_surface_job",
    description="Compute a van der Waals or solvent-accessible surface mesh for a structure.",
)
register_handler(
    "pipeline_self_test",
    "app.services.jobs.handlers:pipeline_self_test_job",
    description="Diagnostic: verify the background job pipeline (progress, cancel, timeout) works.",
    phase="phase-0",
)
