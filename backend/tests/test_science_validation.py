"""Scientific validation protocol.

This module is the acceptance test required by the development brief: it checks
that the numbers MolDock Studio produces for two well-characterised structures
agree with independent, published properties of those structures. A passing run
means the parsing, bond perception and geometry pipeline are physically
plausible — it is **not** a claim that any docking score is experimentally
validated (that is Phase 3+ work, with its own protocol).

References for the expected values:

* 1UBQ (ubiquitin, 1.8 A): 76 residues, radius of gyration ~11.8 A, one
  methionine sulfur, no disulfides, a five-stranded beta sheet and two helices.
* 3PTB (trypsin + benzamidine, 1.8 A): 223 residues, six disulfide bridges,
  a bound benzamidine in the S1 pocket and one calcium ion.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path

import numpy as np
import pytest

from app.services.io.parsers import parse_structure_file
from app.services.io.types import ParsedStructure

pytestmark = pytest.mark.scientific


@pytest.fixture(scope="module")
def ubiquitin(sample_data: Path) -> ParsedStructure:
    return parse_structure_file(sample_data / "1UBQ.pdb", "pdb", name="1UBQ", source="test")


@pytest.fixture(scope="module")
def trypsin(sample_data: Path) -> ParsedStructure:
    return parse_structure_file(sample_data / "3PTB.pdb", "pdb", name="3PTB", source="test")


def radius_of_gyration(structure: ParsedStructure) -> float:
    coords = np.asarray([[atom.x, atom.y, atom.z] for atom in structure.atoms], dtype=float)
    centered = coords - coords.mean(axis=0)
    return float(np.sqrt((centered**2).sum(axis=1).mean()))


def ca_coords(structure: ParsedStructure) -> np.ndarray:
    indices = [residue.ca_index for residue in structure.residues if residue.ca_index is not None]
    return np.asarray(
        [[structure.atoms[i].x, structure.atoms[i].y, structure.atoms[i].z] for i in indices],
        dtype=float,
    )


# --- 1UBQ -------------------------------------------------------------------
def test_ubiquitin_radius_of_gyration_is_published_value(ubiquitin: ParsedStructure) -> None:
    # All-atom radius of gyration of ubiquitin is ~11.8 A.
    assert radius_of_gyration(ubiquitin) == pytest.approx(11.8, abs=0.6)


def test_ubiquitin_sequence_matches_uniprot(ubiquitin: ParsedStructure) -> None:
    # UniProt P0CG48 (UBB) residues 1-76.
    expected = (
        "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"
    )
    assert ubiquitin.sequences["A"] == expected


def test_ubiquitin_ca_trace_is_compact(ubiquitin: ParsedStructure) -> None:
    coords = ca_coords(ubiquitin)
    assert coords.shape[0] == 76
    # Consecutive CA distance distribution: trans peptide, 3.8 A.
    steps = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    assert steps.min() > 3.5
    assert steps.max() < 4.2
    assert steps.mean() == pytest.approx(3.80, abs=0.05)


def test_ubiquitin_has_no_disulfide(ubiquitin: ParsedStructure) -> None:
    # The mature ubiquitin sequence has one methionine and no cysteine, so there
    # is exactly one sulfur atom and no disulfide bridge.
    assert ubiquitin.element_counts["S"] == 1
    assert not any(
        ubiquitin.atoms[bond.a].element == "S" and ubiquitin.atoms[bond.b].element == "S"
        for bond in ubiquitin.bonds
    )


def test_ubiquitin_secondary_structure_fractions_are_reasonable(ubiquitin: ParsedStructure) -> None:
    content = ubiquitin.secondary_structure_content
    total = content["helix"] + content["sheet"] + content["coil"]
    assert total == 76
    # Ubiquitin is ~20% helix and ~35% sheet.
    assert 0.10 < content["helix"] / total < 0.35
    assert 0.25 < content["sheet"] / total < 0.55


# --- 3PTB -------------------------------------------------------------------
def test_trypsin_radius_of_gyration(trypsin: ParsedStructure) -> None:
    # Trypsin (223 residues) has an all-atom Rg of ~15.5-16.5 A; the extras
    # (calcium, benzamidine, a shell of waters) push the whole-file value a
    # little higher, so accept a generous window.
    assert 14.0 < radius_of_gyration(trypsin) < 18.5


def test_trypsin_disulfide_geometry(trypsin: ParsedStructure) -> None:
    lengths = []
    for bond in trypsin.bonds:
        a = trypsin.atoms[bond.a]
        b = trypsin.atoms[bond.b]
        if a.element == "S" and b.element == "S":
            lengths.append(math.dist(a.coords, b.coords))
    assert len(lengths) == 6
    assert min(lengths) > 2.00
    assert max(lengths) < 2.10


def test_benzamidine_sits_in_a_protein_pocket(trypsin: ParsedStructure) -> None:
    benzamidine = next(residue for residue in trypsin.residues if residue.name == "BEN")
    ligand_atoms = [
        trypsin.atoms[index]
        for index in range(benzamidine.atom_start, benzamidine.atom_start + benzamidine.atom_count)
    ]
    protein_atoms = [atom for atom in trypsin.atoms if not atom.is_water and not atom.is_hetero]

    minimum = min(
        math.dist(ligand.coords, protein.coords)
        for ligand in ligand_atoms
        for protein in protein_atoms
    )
    # A real bound ligand makes close van der Waals contacts (< 4 A) but is not
    # covalently fused to the protein (> 1.6 A).
    assert 2.5 < minimum < 4.0


def test_benzamidine_is_planar(trypsin: ParsedStructure) -> None:
    benzamidine = next(residue for residue in trypsin.residues if residue.name == "BEN")
    heavy = [
        trypsin.atoms[index]
        for index in range(benzamidine.atom_start, benzamidine.atom_start + benzamidine.atom_count)
        if trypsin.atoms[index].element != "H"
    ]
    coords = np.asarray([[atom.x, atom.y, atom.z] for atom in heavy])
    centered = coords - coords.mean(axis=0)
    # The smallest singular value measures out-of-plane spread: a flat aromatic
    # amidine is planar to well under 0.5 A.
    singular_values = np.linalg.svd(centered, compute_uv=False)
    assert singular_values[-1] < 0.5


# --- cross-checks -----------------------------------------------------------
def test_peptide_bond_lengths_are_uniform(trypsin: ParsedStructure) -> None:
    lengths = []
    residues = trypsin.residues
    for index in range(len(residues) - 1):
        first = residues[index]
        second = residues[index + 1]
        if not (first.is_amino_acid and second.is_amino_acid):
            continue
        if first.chain_index != second.chain_index:
            continue
        if first.c_index is None or second.n_index is None:
            continue
        lengths.append(math.dist(trypsin.atoms[first.c_index].coords, trypsin.atoms[second.n_index].coords))
    assert len(lengths) > 200
    assert statistics.median(lengths) == pytest.approx(1.33, abs=0.03)
    assert max(lengths) < 1.6


@pytest.mark.slow
def test_solvent_accessible_area_is_biologically_plausible(ubiquitin: ParsedStructure) -> None:
    from app.services.geometry.surface import surface_from_structure

    mesh = surface_from_structure(ubiquitin, mode="sas", probe_radius=1.4, grid_spacing=0.8)
    # The SASA of ubiquitin is ~6000-7000 A^2 (Shrake-Rupley / LCPO literature).
    # A coarse grid slightly underestimates it.
    assert 4000 < mesh.area < 9000, mesh.area
    # The probe-centre envelope encloses the van der Waals volume (~11000 A^3)
    # plus the probe shell, so it is clearly larger than the dry volume.
    assert 9000 < mesh.volume < 30000, mesh.volume
