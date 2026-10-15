"""Built-in job handlers.

``generate_surface_job`` is the real Phase 1 heavy job: surface generation is
O(grid x atoms) and is kept off the request thread for large structures.

``pipeline_self_test_job`` is a genuine diagnostic, not a placeholder: it lets a
user (and the test suite) verify that the job pipeline reports progress, honours
cancellation and enforces timeouts on their machine.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.errors import NotFoundError
from app.services.io.parsers import parse_structure_file
from app.services.store import ArtifactStore


def _load_structure(store: ArtifactStore, relative_path: str, fmt: str):
    path = store.absolute(relative_path)
    if not path.exists():
        raise NotFoundError(f"Structure file is missing from the store: {relative_path}")
    return parse_structure_file(path, fmt, name=path.stem, source="stored")


def generate_surface_job(params: dict[str, Any], progress) -> dict[str, Any]:
    """Compute a surface mesh and cache it, returning the cache path and stats."""
    from app.services.surfaces import (  # local import keeps the child light
        SurfaceRequest,
        generate_and_cache,
    )

    progress.state("running", "Reading structure")
    request = SurfaceRequest(**params)
    store = ArtifactStore()
    structure = _load_structure(store, request.structure_path, request.structure_format)
    progress.progress(0.1, f"Loaded {structure.atom_count} atoms")

    def step(fraction: float, message: str) -> None:
        progress.progress(fraction, message)

    stats, cache_path = generate_and_cache(structure, request, store, on_progress=step)
    progress.progress(1.0, "Surface ready")
    return {"cachePath": cache_path, "stats": stats}


def pipeline_self_test_job(params: dict[str, Any], progress) -> dict[str, Any]:
    """Exercise the job pipeline: report progress on a fixed schedule.

    Parameters
    ----------
    steps:
        Number of progress updates to emit.
    seconds_per_step:
        Wall-clock delay between updates. ``cancel`` and ``timeout`` tests use
        this to hold the job open.
    """
    steps = int(params.get("steps", 5))
    seconds_per_step = float(params.get("seconds_per_step", 0.4))
    progress.state("running", "Self-test running")
    for step_index in range(steps):
        time.sleep(seconds_per_step)
        progress.progress((step_index + 1) / steps, f"Step {step_index + 1}/{steps}")
    progress.state("running", "Self-test finished")
    return {
        "steps": steps,
        "secondsPerStep": seconds_per_step,
        "elapsed": round(steps * seconds_per_step, 3),
        "note": "Job pipeline executed in an isolated child process.",
    }
