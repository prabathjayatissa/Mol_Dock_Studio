"""Molecular surface generation.

Two well-defined surfaces are produced as triangle meshes:

``vdw``
    The van der Waals surface: the boundary of the union of atomic spheres at
    their van der Waals radii. This is an exact isosurface of the distance
    function, no approximation involved.

``sas``
    The solvent-accessible surface (Richards): the locus traced by the centre of
    a spherical probe rolling over the van der Waals surface, i.e. the
    isosurface of the distance function at the probe radius.

Both are computed from the *signed distance field* ``phi(x) = min_i(|x - c_i| - r_i)``
evaluated on a regular grid with a k-d tree, then extracted with marching cubes.
No empirical smoothing or hand-drawn geometry is involved, and the resulting
mesh is reproducible for a given grid spacing.

The Connolly solvent-*excluded* surface (with reentrant arcs) is deliberately
**not** claimed: it requires a rolling-ball/closing operation that is not part
of this implementation. See docs/architecture.md.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

SurfaceMode = Literal["vdw", "sas"]

# Hard ceiling on grid points (~40 MB of float64 work array) so a large
# structure degrades to a coarser grid instead of exhausting memory.
MAX_GRID_POINTS = 6_000_000
MIN_SPACING = 0.35
MAX_SPACING = 3.0


@dataclass
class SurfaceMesh:
    mode: SurfaceMode
    probe_radius: float
    grid_spacing: float
    vertices: np.ndarray  # (N, 3) float32, world coordinates
    faces: np.ndarray  # (M, 3) uint32
    normals: np.ndarray  # (N, 3) float32
    atoms_used: int
    triangle_count: int
    area: float
    volume: float
    grid_shape: tuple[int, int, int]
    spacing_used: float
    warnings: list[str]

    def stats(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "probeRadius": self.probe_radius,
            "requestedSpacing": self.grid_spacing,
            "spacingUsed": self.spacing_used,
            "vertices": int(self.vertices.shape[0]),
            "triangles": self.triangle_count,
            "area": round(self.area, 2),
            "volume": round(self.volume, 2),
            "atomsUsed": self.atoms_used,
            "gridShape": list(self.grid_shape),
            "warnings": self.warnings,
        }

    def cache_key(self) -> str:
        payload = f"{self.mode}|{self.probe_radius:.3f}|{self.grid_spacing:.3f}|{self.atoms_used}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _chunked_distance_field(
    centers: np.ndarray,
    radii: np.ndarray,
    origin: np.ndarray,
    shape: tuple[int, int, int],
    spacing: float,
    *,
    chunk_points: int = 250_000,
) -> np.ndarray:
    """Signed distance field ``min_i(|x - c_i| - r_i)`` on a regular grid."""
    from scipy.spatial import cKDTree

    nx, ny, nz = shape
    field = np.empty((nx, ny, nz), dtype=np.float32)
    tree = cKDTree(centers)
    max_radius = float(radii.max())
    # k nearest centres: enough neighbours that the closest surface point is
    # always among them for typical molecular radii.
    k = min(len(centers), 24)
    search_radius = max_radius + 3.0 * spacing

    x_coords = origin[0] + np.arange(nx, dtype=np.float64) * spacing
    y_coords = origin[1] + np.arange(ny, dtype=np.float64) * spacing
    z_coords = origin[2] + np.arange(nz, dtype=np.float64) * spacing

    plane = np.empty((nx * ny * nz, 3), dtype=np.float64)
    grid_x, grid_y, grid_z = np.meshgrid(x_coords, y_coords, z_coords, indexing="ij")
    plane[:, 0] = grid_x.ravel()
    plane[:, 1] = grid_y.ravel()
    plane[:, 2] = grid_z.ravel()

    values = np.empty(plane.shape[0], dtype=np.float32)
    for start in range(0, plane.shape[0], chunk_points):
        end = min(start + chunk_points, plane.shape[0])
        block = plane[start:end]
        distances, indices = tree.query(block, k=k, distance_upper_bound=search_radius)
        # scipy returns shape (N,) for k == 1 but (N, k) for k > 1; reshaping to
        # (N, k) keeps the per-point neighbour axis. Using atleast_2d() instead
        # would transpose k == 1 into (1, N) and collapse the whole chunk to a
        # single value, producing a constant field (no isosurface).
        distances = np.asarray(distances).reshape(block.shape[0], k)
        indices = np.asarray(indices).reshape(block.shape[0], k)
        valid = np.isfinite(distances) & (indices < len(centers))
        # Points beyond search_radius have no valid neighbour. Their true signed
        # distance is positive and always below search_radius, so they are filled
        # with that finite upper bound rather than inf/inf (which would be NaN and
        # would make marching cubes find no isosurface).
        far = float(search_radius)
        neighbour_radii = np.where(valid, radii[np.clip(indices, 0, len(centers) - 1)], 0.0)
        measured = np.where(valid, distances, far)
        signed = measured - neighbour_radii
        values[start:end] = np.min(signed, axis=1).astype(np.float32)

    field[:] = values.reshape(shape)
    return field


def _mesh_metrics(vertices: np.ndarray, faces: np.ndarray) -> tuple[float, float]:
    """Surface area and enclosed volume from the triangle mesh."""
    if faces.size == 0:
        return 0.0, 0.0
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    area = float(0.5 * np.linalg.norm(cross, axis=1).sum())
    volume = float(np.abs(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum()) / 6.0)
    return area, volume


def generate_surface(
    centers: np.ndarray,
    radii: np.ndarray,
    *,
    mode: SurfaceMode = "sas",
    probe_radius: float = 1.4,
    grid_spacing: float = 0.8,
    padding: float | None = None,
) -> SurfaceMesh:
    """Build a surface mesh from atom centres and radii."""
    from skimage import measure

    if mode not in {"vdw", "sas"}:
        raise ValueError(f"Unknown surface mode '{mode}'")
    if len(centers) == 0:
        raise ValueError("No atoms supplied for surface generation.")

    radii = np.asarray(radii, dtype=np.float64)
    effective_radii = radii + (probe_radius if mode == "sas" else 0.0)
    spacing = float(np.clip(grid_spacing, MIN_SPACING, MAX_SPACING))
    pad = padding if padding is not None else max(2.5, 2.0 * spacing + (probe_radius if mode == "sas" else 0.0))

    lower = centers.min(axis=0) - effective_radii.max() - pad
    upper = centers.max(axis=0) + effective_radii.max() + pad

    warnings: list[str] = []
    shape = np.maximum(np.ceil((upper - lower) / spacing).astype(int) + 1, 3)
    while int(np.prod(shape)) > MAX_GRID_POINTS:
        spacing *= 1.25
        shape = np.maximum(np.ceil((upper - lower) / spacing).astype(int) + 1, 3)
        warnings.append(
            f"Grid spacing increased to {spacing:.2f} Å to keep the surface computation "
            f"within the memory budget for {len(centers)} atoms."
        )
        if spacing >= MAX_SPACING:
            break

    field = _chunked_distance_field(centers, effective_radii, lower, tuple(shape), spacing)
    try:
        vertices, faces, normals, _values = measure.marching_cubes(field, level=0.0, spacing=(spacing,) * 3)
    except (ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Surface extraction failed: {exc}") from exc

    vertices = (vertices + lower).astype(np.float32)
    faces = faces.astype(np.uint32)
    normals = normals.astype(np.float32)
    area, volume = _mesh_metrics(vertices.astype(np.float64), faces.astype(np.int64))

    return SurfaceMesh(
        mode=mode,
        probe_radius=float(probe_radius),
        grid_spacing=float(grid_spacing),
        vertices=vertices,
        faces=faces,
        normals=normals,
        atoms_used=int(len(centers)),
        triangle_count=int(faces.shape[0]),
        area=area,
        volume=volume,
        grid_shape=(int(shape[0]), int(shape[1]), int(shape[2])),
        spacing_used=float(spacing),
        warnings=warnings,
    )


def surface_from_structure(
    structure,
    *,
    mode: SurfaceMode = "sas",
    probe_radius: float = 1.4,
    grid_spacing: float = 0.8,
    include_hydrogens: bool = False,
    atom_indices: list[int] | None = None,
) -> SurfaceMesh:
    """Generate a surface for a :class:`ParsedStructure`.

    Hydrogens are excluded by default: they add grid cost and barely change the
    envelope of a heavy-atom surface.
    """
    atoms = structure.atoms
    if not atoms:
        raise ValueError("The structure has no atoms.")
    selected = [
        atom
        for atom in atoms
        if (include_hydrogens or atom.element.upper() != "H")
        and (atom_indices is None or atom.index in set(atom_indices))
    ]
    if not selected:
        raise ValueError("No atoms matched the surface selection criteria.")
    centers = np.asarray([(atom.x, atom.y, atom.z) for atom in selected], dtype=np.float64)
    radii = np.asarray([atom.vdw_radius for atom in selected], dtype=np.float64)
    return generate_surface(
        centers,
        radii,
        mode=mode,
        probe_radius=probe_radius,
        grid_spacing=grid_spacing,
    )


def cache_surface(mesh: SurfaceMesh, path: Path) -> Path:
    """Write a mesh to ``path`` as a compressed ``.npz`` (the cache path itself)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    full_stats = mesh.stats()
    np.savez_compressed(
        path,
        vertices=mesh.vertices,
        faces=mesh.faces,
        normals=mesh.normals,
        meta=np.asarray(
            [
                mesh.probe_radius,
                mesh.spacing_used,
                mesh.area,
                mesh.volume,
                float(mesh.atoms_used),
                float(mesh.triangle_count),
            ],
            dtype=np.float64,
        ),
        stats_json=json.dumps(full_stats, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        ),
    )
    return path


def load_cached_surface(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    data = np.load(path)
    if "stats_json" in data:
        stats = json.loads(data["stats_json"].tobytes().decode("utf-8"))
        # Keep triangles/vertices consistent (numbers may be ints/floats in JSON)
        return data["vertices"], data["faces"], data["normals"], stats
    meta = data["meta"]
    stats = {
        "probeRadius": float(meta[0]),
        "spacingUsed": float(meta[1]),
        "area": float(meta[2]),
        "volume": float(meta[3]),
        "atomsUsed": int(meta[4]),
        "triangles": int(meta[5]),
    }
    # Fallback: add required fields with sensible defaults if missing (for very
    # old caches). The route will still validate; regenerating is safer.
    stats.setdefault("mode", "sas")
    stats.setdefault("vertices", int(data["vertices"].shape[0]))
    stats.setdefault("gridShape", [0, 0, 0])
    stats.setdefault("requestedSpacing", stats.get("spacingUsed"))
    stats.setdefault("warnings", [])
    return data["vertices"], data["faces"], data["normals"], stats


def estimate_grid_points(centers: np.ndarray, radii: np.ndarray, spacing: float, probe: float) -> int:
    """Cheap pre-flight estimate used by tests and the API to reject huge jobs."""
    if len(centers) == 0:
        return 0
    effective = radii + probe
    lower = centers.min(axis=0) - effective.max() - 2.5
    upper = centers.max(axis=0) + effective.max() + 2.5
    shape = np.maximum(np.ceil((upper - lower) / spacing).astype(int) + 1, 3)
    return int(math.prod(shape))
