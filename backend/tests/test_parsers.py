"""Structure parsers: real files, formats, and honest reporting of information loss."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import StructureParseError, UnsupportedFormatError
from app.services.io.parsers import parse_structure_file

TINY_PDB = """\
HEADER    TEST STRUCTURE                          01-JAN-00   TINY
ATOM      1  N   GLY A   1      10.000  10.000  10.000  1.00 20.00           N
ATOM      2  CA  GLY A   1      11.458  10.000  10.000  1.00 20.00           C
ATOM      3  C   GLY A   1      12.000  11.420  10.000  1.00 20.00           C
ATOM      4  O   GLY A   1      13.200  11.560  10.000  1.00 20.00           O
ATOM      5  N   ALA A   2      12.300  12.600  10.000  1.00 20.00           N
ATOM      6  CA  ALA A   2      13.700  13.100  10.000  1.00 20.00           C
ATOM      7  C   ALA A   2      14.500  11.900  10.000  1.00 20.00           C
REMARK 999 this line is not a coordinate record and must be ignored
HETATM    8  O   HOH A 101      20.000  20.000  20.000  1.00 30.00           O
END
"""

TINY_XYZ = """\
3
water
O  0.000  0.000  0.000
H  0.000  0.000  0.960
H  0.930  0.000  0.000
"""

TINY_FASTA = """>sp|P0CG48|UBIQUITIN
MQIFVKTLTGKTITLEVEPSDTIENVK
>sp|P00698|LYSOZYME
KVFGRCELAAAMKRHGLDNYRGYSLG
"""

TINY_PDBQT = """\
REMARK  Name = test ligand
ROOT
ATOM      1  C   LIG A   1      10.000  10.000  10.000  1.00  0.00     0.000 A
ATOM      2  N   LIG A   1      11.400  10.000  10.000  1.00  0.00    -0.300 NA
ATOM      3  O   LIG A   1      12.000  11.420  10.000  1.00  0.00    -0.300 OA
ENDROOT
TORSDOF 0
"""

TWO_RECORD_SDF = """\
benzene
  RDKit          3D

  6  6  0  0  0  0  0  0  0  0999 V2000
    1.2000    0.0000    0.0000 C   0  0
    0.6000    1.0392    0.0000 C   0  0
   -0.6000    1.0392    0.0000 C   0  0
   -1.2000    0.0000    0.0000 C   0  0
   -0.6000   -1.0392    0.0000 C   0  0
    0.6000   -1.0392    0.0000 C   0  0
  1  2  2  0
  2  3  1  0
  3  4  2  0
  4  5  1  0
  5  6  2  0
  6  1  1  0
M  END
$$$$
ethanol
  RDKit          3D

  3  2  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0
    1.2000    0.0000    0.0000 O   0  0
   -0.5000    0.9000    0.0000 C   0  0
  1  2  1  0
  1  3  1  0
M  END
$$$$
"""


# --- real structures --------------------------------------------------------
def test_parse_1ubq_is_complete(sample_data: Path) -> None:
    structure = parse_structure_file(sample_data / "1UBQ.pdb", "pdb", name="1UBQ", source="test")
    summary = structure.summary()

    assert summary["atoms"] == 660
    assert summary["residues"] == 134  # 76 amino acids + 58 waters
    assert summary["waters"] == 58
    assert summary["chains"] == 1
    assert summary["elements"] == {"N": 105, "C": 378, "O": 176, "S": 1}
    assert structure.atom_count == structure.heavy_atom_count  # no hydrogens in this entry
    assert structure.chains[0].kind == "polymer"
    assert structure.sequences["A"].startswith("MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQR")
    assert len(structure.sequences["A"]) == 76
    assert structure.metadata["cell"]["a"] > 20  # unit-cell read from CRYST1


def test_nothing_is_dropped_and_no_water_is_removed(sample_data: Path) -> None:
    """Waters and hetero groups are retained and clearly flagged, never deleted."""
    structure = parse_structure_file(sample_data / "3PTB.pdb", "pdb", name="3PTB", source="test")
    summary = structure.summary()

    assert summary["waters"] == 62
    assert summary["hetero_residues"] == 2  # calcium ion + benzamidine
    names = {residue.name for residue in structure.residues if residue.is_hetero and not residue.is_water}
    assert names == {"BEN", "CA"}
    water_atoms = [atom for atom in structure.atoms if atom.is_water]
    assert len(water_atoms) == 62
    assert all(atom.element == "O" for atom in water_atoms)
    # The calcium is present as an atom and is not bonded covalently.
    calcium = [atom for atom in structure.atoms if atom.element == "Ca"]
    assert len(calcium) == 1
    assert all(atom.element != "Ca" for bond in structure.bonds for atom in (structure.atoms[bond.a], structure.atoms[bond.b]))


def test_alternate_conformation_warning_is_accurate(sample_data: Path) -> None:
    """1UBQ has no alternate locations, so no such warning may be reported."""
    structure = parse_structure_file(sample_data / "1UBQ.pdb", "pdb", name="1UBQ", source="test")
    codes = {warning.code for warning in structure.warnings}
    assert "alternate_conformations" not in codes
    assert "element_inferred" not in codes
    assert all(atom.altloc == "" for atom in structure.atoms)


# --- in-file structures -----------------------------------------------------
def test_parse_tiny_pdb(tmp_path: Path) -> None:
    path = tmp_path / "tiny.pdb"
    path.write_text(TINY_PDB, encoding="utf-8")
    structure = parse_structure_file(path, "pdb", name="tiny", source="test")

    assert structure.atom_count == 8
    assert [residue.name for residue in structure.residues] == ["GLY", "ALA", "HOH"]
    assert structure.residues[2].is_water
    assert structure.chains[0].kind == "polymer"
    assert structure.sequences["A"] == "GA"


def test_parse_xyz(tmp_path: Path) -> None:
    path = tmp_path / "water.xyz"
    path.write_text(TINY_XYZ, encoding="utf-8")
    structure = parse_structure_file(path, "xyz", name="water", source="test")

    assert structure.atom_count == 3
    assert structure.element_counts == {"O": 1, "H": 2}
    # Bond perception finds both O-H bonds.
    assert len(structure.bonds) == 2
    assert all(bond.source == "geometry" for bond in structure.bonds)


def test_parse_fasta_produces_sequences_without_coordinates(tmp_path: Path) -> None:
    path = tmp_path / "sequences.fasta"
    path.write_text(TINY_FASTA, encoding="utf-8")
    structure = parse_structure_file(path, "fasta", name="sequences", source="test")

    # A FASTA has no coordinates. Rather than inventing atoms, the parser stores
    # the sequences as metadata and says so explicitly.
    assert structure.has_coordinates is False
    assert structure.atom_count == 0
    assert structure.residues == []
    assert [record["id"] for record in structure.metadata["sequences"]] == [
        "sp|P0CG48|UBIQUITIN",
        "sp|P00698|LYSOZYME",
    ]
    assert structure.metadata["sequences"][0]["sequence"].startswith("MQIFVKTLTGKTITLEVEPSDTIENVK")
    codes = {warning.code for warning in structure.warnings}
    assert "sequence_only" in codes


def test_parse_fasta_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "not.fasta"
    path.write_text("this is not a fasta file", encoding="utf-8")
    with pytest.raises(StructureParseError):
        parse_structure_file(path, "fasta", name="not", source="test")


def test_parse_multi_record_sdf_keeps_records(tmp_path: Path) -> None:
    path = tmp_path / "two.sdf"
    path.write_text(TWO_RECORD_SDF, encoding="utf-8")
    structure = parse_structure_file(path, "sdf", name="two", source="test")

    titles = [residue.title for residue in structure.residues]
    assert titles == ["benzene", "ethanol"]
    assert structure.atom_count == 9
    assert structure.residues[0].atom_count == 6
    assert structure.residues[1].atom_count == 3
    assert structure.residues[0].smiles is not None
    assert "c1ccccc1" in structure.residues[0].smiles


def test_parse_benzamidine_sdf(sample_data: Path) -> None:
    structure = parse_structure_file(
        sample_data / "benzamidine.sdf", "sdf", name="benzamidine", source="test"
    )
    assert structure.atom_count == 17  # 9 heavy + 8 hydrogen
    assert structure.heavy_atom_count == 9
    assert structure.element_counts == {"C": 7, "H": 8, "N": 2}
    assert structure.is_ligand_like
    # File bonds are trusted and kept; geometry only adds what is missing.
    sources = {bond.source for bond in structure.bonds}
    assert "file" in sources
    # 6 aromatic ring C-C, 1 ring-C to amidine C, 1 C=N, 1 C-N, 5 aromatic C-H,
    # 1 imine N-H, 2 amine N-H.
    assert len(structure.bonds) == 17


def test_parse_pdbqt_keeps_charges_and_autodock_types(tmp_path: Path) -> None:
    path = tmp_path / "ligand.pdbqt"
    path.write_text(TINY_PDBQT, encoding="utf-8")
    structure = parse_structure_file(path, "pdbqt", name="ligand", source="test")

    assert structure.atom_count == 3
    assert structure.element_counts == {"C": 1, "N": 1, "O": 1}
    assert structure.atoms[0].autodock_type == "A"
    assert structure.atoms[0].partial_charge == pytest.approx(0.0)
    assert structure.atoms[1].partial_charge == pytest.approx(-0.3)
    assert structure.residues[0].is_hetero
    assert len(structure.bonds) >= 2
    codes = {warning.code for warning in structure.warnings}
    assert "pdbqt_torsion_tree" in codes
    assert structure.metadata["torsion_tree_applied"] is False


def test_parse_pdbqt_without_atoms_fails(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdbqt"
    path.write_text("ROOT\nENDROOT\nTORSDOF 0\n", encoding="utf-8")
    with pytest.raises(StructureParseError):
        parse_structure_file(path, "pdbqt", name="empty", source="test")


# --- failures ---------------------------------------------------------------
def test_parse_rejects_binary_garbage(tmp_path: Path) -> None:
    path = tmp_path / "garbage.pdb"
    path.write_bytes(b"\x00\x01\x02\x03" * 200)
    with pytest.raises(StructureParseError):
        parse_structure_file(path, "pdb", name="garbage", source="test")


def test_parse_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.pdb"
    path.write_text("", encoding="utf-8")
    with pytest.raises(StructureParseError):
        parse_structure_file(path, "pdb", name="empty", source="test")


def test_parse_rejects_unknown_format(tmp_path: Path) -> None:
    path = tmp_path / "thing.weird"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        parse_structure_file(path, "weird", name="thing", source="test")


def test_parse_rejects_invalid_smiles_sdf(tmp_path: Path) -> None:
    path = tmp_path / "bad.sdf"
    path.write_text("not really an sdf\n", encoding="utf-8")
    with pytest.raises(StructureParseError):
        parse_structure_file(path, "sdf", name="bad", source="test")
