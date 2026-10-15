"""Export writers and round-trip fidelity.

An export is only useful if another tool can read it, so every writer is tested
by reading its own output back with an independent parser and comparing the
physical content (atom counts, elements, coordinates, bonds).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import ValidationFailure
from app.services.io.parsers import parse_structure_file
from app.services.io.types import ParsedStructure
from app.services.io.writers import export_structure

pytestmark = pytest.mark.scientific


@pytest.fixture(scope="module")
def ubiquitin(sample_data: Path) -> ParsedStructure:
    return parse_structure_file(sample_data / "1UBQ.pdb", "pdb", name="1UBQ", source="test")


@pytest.fixture(scope="module")
def benzamidine(sample_data: Path) -> ParsedStructure:
    return parse_structure_file(sample_data / "benzamidine.sdf", "sdf", name="benzamidine", source="test")


def reparse(content: str, fmt: str, tmp_path: Path) -> ParsedStructure:
    path = tmp_path / f"roundtrip.{fmt}"
    path.write_text(content, encoding="utf-8")
    return parse_structure_file(path, fmt, name="roundtrip", source="test")


# --- PDB --------------------------------------------------------------------
def test_pdb_export_round_trips(ubiquitin: ParsedStructure, tmp_path: Path) -> None:
    content, filename = export_structure(ubiquitin, "pdb")
    assert filename.endswith(".pdb")
    assert content.startswith("HEADER")
    assert content.rstrip().endswith("END")

    again = reparse(content, "pdb", tmp_path)
    assert again.atom_count == ubiquitin.atom_count
    assert len(again.residues) == len(ubiquitin.residues)
    assert again.element_counts == ubiquitin.element_counts
    assert again.sequences["A"] == ubiquitin.sequences["A"]


def test_pdb_export_coordinates_are_preserved(ubiquitin: ParsedStructure, tmp_path: Path) -> None:
    content, _ = export_structure(ubiquitin, "pdb")
    again = reparse(content, "pdb", tmp_path)
    # PDB stores 3 decimals (0.001 A); compare a sample of atoms.
    for original, restored in zip(ubiquitin.atoms[:50], again.atoms[:50], strict=True):
        assert restored.x == pytest.approx(original.x, abs=5e-4)
        assert restored.y == pytest.approx(original.y, abs=5e-4)
        assert restored.z == pytest.approx(original.z, abs=5e-4)


def test_pdb_export_writes_connectivity(ubiquitin: ParsedStructure) -> None:
    content, _ = export_structure(ubiquitin, "pdb")
    assert "CONECT" in content


# --- mmCIF ------------------------------------------------------------------
def test_mmcif_export_round_trips(ubiquitin: ParsedStructure, tmp_path: Path) -> None:
    content, filename = export_structure(ubiquitin, "mmcif")
    assert filename.endswith(".cif")
    assert content.startswith("data_")

    again = reparse(content, "mmcif", tmp_path)
    assert again.atom_count == ubiquitin.atom_count
    assert again.element_counts == ubiquitin.element_counts
    for original, restored in zip(ubiquitin.atoms[:50], again.atoms[:50], strict=True):
        assert restored.x == pytest.approx(original.x, abs=5e-4)


# --- SDF --------------------------------------------------------------------
def test_sdf_export_round_trips(benzamidine: ParsedStructure, tmp_path: Path) -> None:
    content, filename = export_structure(benzamidine, "sdf")
    assert filename.endswith(".sdf")
    assert content.rstrip().endswith("$$$$")

    again = reparse(content, "sdf", tmp_path)
    assert again.atom_count == benzamidine.atom_count
    assert len(again.bonds) == len(benzamidine.bonds)
    assert again.element_counts == benzamidine.element_counts


def test_sdf_export_refuses_a_macromolecule(ubiquitin: ParsedStructure) -> None:
    with pytest.raises(ValidationFailure) as excinfo:
        export_structure(ubiquitin, "sdf")
    assert "macromolecule" in (excinfo.value.remediation or "")


# --- MOL2 -------------------------------------------------------------------
def test_mol2_export_round_trips(benzamidine: ParsedStructure, tmp_path: Path) -> None:
    content, filename = export_structure(benzamidine, "mol2")
    assert filename.endswith(".mol2")
    assert "@<TRIPOS>MOLECULE" in content
    assert "@<TRIPOS>ATOM" in content

    again = reparse(content, "mol2", tmp_path)
    assert again.atom_count == benzamidine.atom_count
    assert again.element_counts == benzamidine.element_counts


# --- XYZ --------------------------------------------------------------------
def test_xyz_export_round_trips(benzamidine: ParsedStructure, tmp_path: Path) -> None:
    content, filename = export_structure(benzamidine, "xyz")
    assert filename.endswith(".xyz")
    first_line = content.splitlines()[0]
    assert int(first_line) == benzamidine.atom_count

    again = reparse(content, "xyz", tmp_path)
    assert again.atom_count == benzamidine.atom_count
    assert again.element_counts == benzamidine.element_counts
    # Geometry perception recovers connectivity for a small organic molecule.
    assert len(again.bonds) > 0


# --- error handling ---------------------------------------------------------
def test_unknown_export_format_is_rejected(ubiquitin: ParsedStructure) -> None:
    with pytest.raises(ValidationFailure):
        export_structure(ubiquitin, "xyzzy")


def test_pdb_atom_limit_is_enforced() -> None:
    from app.services.io.types import Atom, Chain, ParsedStructure, Residue

    structure = ParsedStructure(format="pdb", name="huge")
    structure.atoms = [
        Atom(index=0, serial=1, name="C", element="C", x=0, y=0, z=0, residue_index=0, chain_index=0)
    ]
    structure.residues = [Residue(index=0, name="LIG", seq=1, chain_index=0, atom_start=0, atom_count=1)]
    structure.chains = [Chain(index=0, id="A", residue_start=0, residue_count=1, kind="ligand")]

    from app.services.io import writers

    original = writers.PDB_FREE_FORMAT_ATOM_LIMIT
    writers.PDB_FREE_FORMAT_ATOM_LIMIT = 0
    try:
        with pytest.raises(ValidationFailure):
            writers.write_pdb(structure)
    finally:
        writers.PDB_FREE_FORMAT_ATOM_LIMIT = original
