"""Scientific geometry sanity checks on real structures.

These are the checks a structural biologist would run first: are the atom
counts right, is the backbone geometry physical, are disulfides present. They
catch "the file parsed but the numbers are nonsense" failures that a schema test
cannot.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path

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


def distance(structure: ParsedStructure, a: int, b: int) -> float:
    atom_a = structure.atoms[a]
    atom_b = structure.atoms[b]
    return math.dist(atom_a.coords, atom_b.coords)


def peptide_bond_lengths(structure: ParsedStructure) -> list[float]:
    lengths: list[float] = []
    residues = structure.residues
    for index in range(len(residues) - 1):
        first = residues[index]
        second = residues[index + 1]
        if not (first.is_amino_acid and second.is_amino_acid):
            continue
        if first.chain_index != second.chain_index:
            continue
        if second.index != first.index + 1:
            continue
        if first.c_index is None or second.n_index is None:
            continue
        lengths.append(distance(structure, first.c_index, second.n_index))
    return lengths


def consecutive_ca_distances(structure: ParsedStructure) -> list[float]:
    distances: list[float] = []
    residues = structure.residues
    for index in range(len(residues) - 1):
        first = residues[index]
        second = residues[index + 1]
        if not (first.is_amino_acid and second.is_amino_acid):
            continue
        if first.chain_index != second.chain_index or second.index != first.index + 1:
            continue
        if first.ca_index is None or second.ca_index is None:
            continue
        distances.append(distance(structure, first.ca_index, second.ca_index))
    return distances


# --- ubiquitin (1UBQ, 1.8 A) ------------------------------------------------
def test_ubiquitin_backbone_is_physically_plausible(ubiquitin: ParsedStructure) -> None:
    ca_distances = consecutive_ca_distances(ubiquitin)
    assert len(ca_distances) >= 70
    # trans peptide CA-CA is 3.80 +/- 0.1 A; cis-proline is ~2.9 A (1UBQ has none).
    assert min(ca_distances) > 3.5
    assert max(ca_distances) < 4.2
    assert statistics.median(ca_distances) == pytest.approx(3.80, abs=0.05)


def test_ubiquitin_peptide_bonds_have_the_right_length(ubiquitin: ParsedStructure) -> None:
    lengths = peptide_bond_lengths(ubiquitin)
    assert len(lengths) >= 70
    assert min(lengths) > 1.2
    assert max(lengths) < 1.5
    assert statistics.median(lengths) == pytest.approx(1.33, abs=0.04)


def test_ubiquitin_has_one_cysteine_and_no_disulfide(ubiquitin: ParsedStructure) -> None:
    assert ubiquitin.element_counts["S"] == 1
    sulfur_bonds = [
        bond
        for bond in ubiquitin.bonds
        if ubiquitin.atoms[bond.a].element == "S" and ubiquitin.atoms[bond.b].element == "S"
    ]
    assert sulfur_bonds == []


def test_ubiquitin_secondary_structure_comes_from_file_records(ubiquitin: ParsedStructure) -> None:
    assert ubiquitin.metadata["secondary_structure_method"] == "file-records"
    content = ubiquitin.secondary_structure_content
    # 1UBQ has a 3-10 helix (23-34), an alpha helix (56-59) and a five-stranded
    # beta sheet. Check the shape, not exact residue-by-residue agreement.
    assert content["helix"] >= 12
    assert content["sheet"] >= 25
    assert content["coil"] >= 15
    assert content["helix"] + content["sheet"] + content["coil"] == 76


def test_ubiquitin_no_plausibility_warnings(ubiquitin: ParsedStructure) -> None:
    codes = {warning.code for warning in ubiquitin.warnings}
    assert "implausible_bond_lengths" not in codes
    assert "alternate_conformations" not in codes


# --- trypsin + benzamidine (3PTB, 1.8 A) ------------------------------------
def test_trypsin_has_six_disulfide_bridges(trypsin: ParsedStructure) -> None:
    sulfur_sulfur = [
        distance(trypsin, bond.a, bond.b)
        for bond in trypsin.bonds
        if trypsin.atoms[bond.a].element == "S" and trypsin.atoms[bond.b].element == "S"
    ]
    assert len(sulfur_sulfur) == 6
    for length in sulfur_sulfur:
        assert length == pytest.approx(2.05, abs=0.1)


def test_trypsin_backbone_is_physically_plausible(trypsin: ParsedStructure) -> None:
    ca_distances = consecutive_ca_distances(trypsin)
    assert len(ca_distances) >= 200
    assert min(ca_distances) > 3.4
    assert max(ca_distances) < 4.2
    assert statistics.median(ca_distances) == pytest.approx(3.80, abs=0.06)


def test_trypsin_benzamidine_and_calcium_are_present(trypsin: ParsedStructure) -> None:
    hetero = {residue.name for residue in trypsin.residues if residue.is_hetero and not residue.is_water}
    assert hetero == {"BEN", "CA"}
    benzamidine = next(residue for residue in trypsin.residues if residue.name == "BEN")
    assert benzamidine.atom_count >= 9
    # Benzamidine has no covalent bond to the protein.
    protein_residues = {
        residue.index for residue in trypsin.residues if residue.is_amino_acid
    }
    ligand_atoms = set(range(benzamidine.atom_start, benzamidine.atom_start + benzamidine.atom_count))
    for bond in trypsin.bonds:
        touches_ligand = bond.a in ligand_atoms or bond.b in ligand_atoms
        if not touches_ligand:
            continue
        other = bond.b if bond.a in ligand_atoms else bond.a
        assert trypsin.atoms[other].residue_index not in protein_residues


def test_trypsin_peptide_bonds_are_physical(trypsin: ParsedStructure) -> None:
    lengths = peptide_bond_lengths(trypsin)
    assert len(lengths) >= 200
    assert min(lengths) > 1.2
    assert max(lengths) < 1.55
