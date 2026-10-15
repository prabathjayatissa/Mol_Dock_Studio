"""Surface generation service: request model, caching and execution.

Both the synchronous API endpoint and the ``generate_surface`` background job
call into this module, so a surface computed interactively and one computed in
the job queue are bit-for-bit identical for the same parameters and are shared
through the on-disk cache.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from app.services.geometry.surface import (
    SurfaceMesh,
    load_cached_surface,
    surface_from_structure,
)
from app.services.io.types import ParsedStructure
from app.services.store import ArtifactStore

ProgressCallback = Callable[[float, str], None]


@dataclass
class SurfaceRequest:
    """Everything that determines a surface, i.e. the complete cache key."""

    structure_path: str
    structure_format: str = "pdb"
    structure_sha256: str | None = None
    mode: Literal["vdw", "sas"] = "sas"
    probe_radius: float = 1.4
    grid_spacing: float = 0.8
    include_hydrogens: bool = False
    chain_ids: list[str] = field(default_factory=list)
    use_cache: bool = True

    def cache_key(self) -> str:
        payload = {
            "sha": self.structure_sha256 or self.structure_path,
            "mode": self.mode,
            "probe": round(float(self.probe_radius), 3),
            "spacing": round(float(self.grid_spacing), 3),
            "hydrogens": bool(self.include_hydrogens),
            "chains": sorted(self.chain_ids),
        }
        return json.dumps(payload, sort_keys=True)


def mesh_to_payload(mesh: SurfaceMesh | None, stats: dict[str, Any], *, encoding: str = "base64") -> dict[str, Any]:
    """Serialise a mesh for transport.

    Coordinates are sent as little-endian float32 and indices as uint32, base64
    encoded to avoid a multi-megabyte JSON number array. The frontend decodes
    straight into ``Float32Array``/``Uint32Array`` views.
    """
    import base64

    payload: dict[str, Any] = {"encoding": encoding, "stats": stats}
    if mesh is None:
        return payload
    payload["vertexCount"] = int(mesh.vertices.shape[0])
    payload["triangleCount"] = int(mesh.faces.shape[0])
    payload["positions"] = base64.b64encode(np.ascontiguousarray(mesh.vertices, dtype="<f4").tobytes()).decode()
    payload["normals"] = base64.b64encode(np.ascontiguousarray(mesh.normals, dtype="<f4").tobytes()).decode()
    payload["indices"] = base64.b64encode(np.ascontiguousarray(mesh.faces, dtype="<u4").tobytes()).decode()
    return payload


def generate_and_cache(
    structure: ParsedStructure,
    request: SurfaceRequest,
    store: ArtifactStore | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], str]:
    """Generate (or load) a surface mesh. Returns ``(stats, cache_path)``."""
    store = store or ArtifactStore()
    key = request.cache_key()
    cache_path = store.cached("surfaces", key, ".npz")

    if request.use_cache and not force and cache_path.exists():
        _vertices, _faces, _normals, stats = load_cached_surface(cache_path)
        stats.update({"mode": request.mode, "cached": True, "cachePath": str(cache_path)})
        if on_progress:
            on_progress(0.9, "Loaded cached surface")
        return stats, str(cache_path)

    if on_progress:
        on_progress(0.2, "Building distance field")

    started = time.perf_counter()
    mesh = surface_from_structure(
        structure,
        mode=request.mode,
        probe_radius=request.probe_radius,
        grid_spacing=request.grid_spacing,
        include_hydrogens=request.include_hydrogens,
    )
    elapsed = time.perf_counter() - started

    if on_progress:
        on_progress(0.85, f"Extracted {mesh.triangle_count} triangles")

    from app.services.geometry.surface import cache_surface

    cache_surface(mesh, cache_path)
    stats = mesh.stats()
    stats.update(
        {
            "cached": False,
            "cachePath": str(cache_path),
            "computeSeconds": round(elapsed, 3),
            "request": asdict(request),
        }
    )
    return stats, str(cache_path)


def load_mesh_from_cache(cache_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    return load_cached_surface(Path(cache_path))


@dataclass(frozen=True)
class MeshArrays:
    """Typed-array view of a mesh (either freshly computed or loaded from cache)."""

    vertices: np.ndarray
    faces: np.ndarray
    normals: np.ndarray


def load_mesh(stats: dict[str, Any]) -> MeshArrays:
    """Load the mesh referenced by a stats payload (sync and background paths)."""
    cache_path = stats.get("cachePath")
    if not cache_path:
        raise ValueError("Surface stats do not reference a cached mesh.")
    vertices, faces, normals, _stats = load_cached_surface(Path(cache_path))
    return MeshArrays(vertices=vertices, faces=faces, normals=normals)


def mesh_payload_from_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Serialize a cached mesh for transport, without recomputation."""
    return mesh_to_payload(load_mesh(stats), stats)
