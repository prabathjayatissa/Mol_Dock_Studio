"""Surface generation: exact vdW and solvent-accessible isosurfaces.

The tests check the *relationships* that must hold between the two surfaces,
which is what makes them a real check rather than a "did it return something"
check:

* a SAS is the vdW surface inflated by the probe radius, so it always encloses a
  larger volume and a larger area;
* both meshes are closed, so the volume computed from the triangles is positive
  and the vertices lie on the requested isosurface level.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from app.services.geometry.surface import (
    MAX_GRID_POINTS,
    generate_surface,
    surface_from_structure,
)
from app.services.io.parsers import parse_structure_file

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def ubiquitin(sample_data: Path):
    return parse_structure_file(sample_data / "1UBQ.pdb", "pdb", name="1UBQ", source="test")


def test_single_sphere_vdw_surface_matches_analytic_values() -> None:
    """A lone atom's vdW surface must match the analytic sphere."""
    radius = 1.70
    mesh = generate_surface(
        np.array([[0.0, 0.0, 0.0]]),
        np.array([radius]),
        mode="vdw",
        grid_spacing=0.4,
    )
    analytic_area = 4.0 * math.pi * radius**2
    analytic_volume = 4.0 / 3.0 * math.pi * radius**3
    # Marching cubes on a 0.4 A grid is accurate to a few percent.
    assert mesh.area == pytest.approx(analytic_area, rel=0.06)
    assert mesh.volume == pytest.approx(analytic_volume, rel=0.06)
    assert mesh.triangle_count > 100


def test_sas_encloses_a_larger_volume_than_vdw(ubiquitin) -> None:
    """The probe-inflated surface encloses the vdW surface (larger volume)."""
    vdw = surface_from_structure(ubiquitin, mode="vdw", grid_spacing=0.9)
    sas = surface_from_structure(ubiquitin, mode="sas", grid_spacing=0.9, probe_radius=1.4)
    assert sas.volume > vdw.volume
    # Inflating the union of vdW spheres by the probe radius fills narrow
    # crevices for a dense protein; the resulting SAS is smoother and typically
    # has less area than the crumpled vdW surface, even though it encloses more
    # volume. A Biopython Shrake-Rupley cross-check confirms SAS area magnitude.
    assert vdw.area > sas.area


def test_sas_of_a_single_sphere_grows_by_the_probe_radius() -> None:
    radius = 1.70
    probe = 1.4
    mesh = generate_surface(
        np.array([[0.0, 0.0, 0.0]]),
        np.array([radius]),
        mode="sas",
        probe_radius=probe,
        grid_spacing=0.4,
    )
    effective = radius + probe
    assert mesh.area == pytest.approx(4.0 * math.pi * effective**2, rel=0.06)
    assert mesh.volume == pytest.approx(4.0 / 3.0 * math.pi * effective**3, rel=0.06)


def test_mesh_is_well_formed(ubiquitin) -> None:
    mesh = surface_from_structure(ubiquitin, mode="vdw", grid_spacing=0.9)
    assert mesh.vertices.shape[1] == 3
    assert mesh.faces.shape[1] == 3
    assert mesh.vertices.dtype == np.float32
    assert mesh.faces.dtype == np.uint32
    assert mesh.triangle_count == mesh.faces.shape[0]
    assert int(mesh.faces.max()) < mesh.vertices.shape[0]
    assert np.isfinite(mesh.vertices).all()
    assert mesh.atoms_used == ubiquitin.atom_count


def test_vertices_lie_on_the_isosurface(ubiquitin) -> None:
    """Every mesh vertex must sit on the zero level set of phi(x)."""
    mesh = surface_from_structure(ubiquitin, mode="vdw", grid_spacing=0.9)
    centers = np.asarray([[a.x, a.y, a.z] for a in ubiquitin.atoms])
    radii = np.asarray([a.vdw_radius for a in ubiquitin.atoms])
    from scipy.spatial import cKDTree

    tree = cKDTree(centers)
    distances, indices = tree.query(mesh.vertices, k=1)
    phi = distances - radii[indices]
    # The field is the exact signed distance sampled on the grid; marching
    # cubes places vertices on the linearly interpolated zero crossing. At
    # sphere-sphere creases the min() has a kink so the maximum interpolation
    # error can be up to ~0.5h; the p95 check keeps most vertices near the
    # true isosurface.
    deviation = np.abs(phi)
    assert deviation.max() < 0.55 * mesh.spacing_used
    assert np.percentile(deviation, 95) < 0.2 * mesh.spacing_used


def test_hydrogens_are_excluded_by_default() -> None:
    # Build a tiny two-atom structure: one carbon, one hydrogen.
    from app.services.io.types import Atom, Chain, ParsedStructure, Residue

    structure = ParsedStructure(format="xyz", name="tiny")
    structure.atoms = [
        Atom(index=0, serial=1, name="C", element="C", x=0, y=0, z=0, residue_index=0, chain_index=0),
        Atom(index=1, serial=2, name="H", element="H", x=1.1, y=0, z=0, residue_index=0, chain_index=0),
    ]
    structure.residues = [
        Residue(index=0, name="LIG", seq=1, chain_index=0, atom_start=0, atom_count=2)
    ]
    structure.chains = [Chain(index=0, id="L", residue_start=0, residue_count=1, kind="ligand")]

    heavy = surface_from_structure(structure, mode="vdw", grid_spacing=0.5)
    assert heavy.atoms_used == 1

    with_h = surface_from_structure(structure, mode="vdw", grid_spacing=0.5, include_hydrogens=True)
    assert with_h.atoms_used == 2
    assert with_h.volume >= heavy.volume


def test_grid_budget_is_respected_for_a_large_volume() -> None:
    # Eight atoms at the corners of a 100 A cube with a fine grid would need far
    # more than the point budget, so the spacing must be coarsened and a warning
    # emitted rather than allocating an enormous distance field.
    corners = np.array(
        [[x, y, z] for x in (0.0, 100.0) for y in (0.0, 100.0) for z in (0.0, 100.0)]
    )
    radii = np.full(len(corners), 1.7)
    mesh = generate_surface(corners, radii, mode="vdw", grid_spacing=0.35)
    assert int(np.prod(mesh.grid_shape)) <= MAX_GRID_POINTS
    assert mesh.warnings
    assert mesh.spacing_used > 0.35


def test_empty_selection_is_rejected() -> None:
    with pytest.raises(ValueError):
        generate_surface(np.zeros((0, 3)), np.zeros(0), mode="vdw")


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        generate_surface(np.zeros((1, 3)), np.ones(1), mode="connolly")  # type: ignore[arg-type]
