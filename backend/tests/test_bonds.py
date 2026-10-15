"""Bond perception rules.

Bond perception decides what a figure shows and what a later preparation step
believes about connectivity, so it is tested directly rather than only through a
parsed file.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.services.io.bonds import infer_bonds, merge_bonds, validate_bond_lengths
from app.services.io.types import Atom, Bond, Residue


def atom(
    index: int,
    element: str,
    xyz: tuple[float, float, float],
    *,
    name: str | None = None,
    residue_index: int = 0,
    chain_index: int = 0,
    is_water: bool = False,
) -> Atom:
    return Atom(
        index=index,
        serial=index + 1,
        name=name or element,
        element=element,
        x=xyz[0],
        y=xyz[1],
        z=xyz[2],
        residue_index=residue_index,
        chain_index=chain_index,
        is_water=is_water,
    )


def residue(
    index: int,
    name: str,
    *,
    chain_index: int = 0,
    is_amino_acid: bool = True,
    is_nucleic: bool = False,
    is_water: bool = False,
) -> Residue:
    return Residue(
        index=index,
        name=name,
        seq=index + 1,
        chain_index=chain_index,
        atom_start=0,
        atom_count=1,
        is_amino_acid=is_amino_acid,
        is_nucleic=is_nucleic,
        is_water=is_water,
    )


def pairs(atoms: Sequence[Atom], residues: Sequence[Residue] | None = None) -> set[tuple[int, int]]:
    return {b.as_tuple() for b in infer_bonds(atoms, residues=residues)}


# --- plain distance rules ---------------------------------------------------
def test_two_carbons_within_bond_length_are_bonded() -> None:
    atoms = [atom(0, "C", (0, 0, 0)), atom(1, "C", (1.54, 0, 0))]
    assert pairs(atoms) == {(0, 1)}


def test_two_carbons_far_apart_are_not_bonded() -> None:
    atoms = [atom(0, "C", (0, 0, 0)), atom(1, "C", (3.0, 0, 0))]
    assert pairs(atoms) == set()


def test_maximum_valence_is_enforced_by_keeping_the_shortest_contacts() -> None:
    # A carbon with five neighbours packed at bonding distance keeps four.
    atoms = [atom(0, "C", (0, 0, 0))]
    atoms += [
        atom(1, "H", (0.50, 0, 0)),
        atom(2, "H", (-0.50, 0, 0)),
        atom(3, "H", (0, 0.50, 0)),
        atom(4, "H", (0, -0.50, 0)),
        atom(5, "H", (0, 0, 0.50)),
    ]
    bonds = infer_bonds(atoms)
    assert len(bonds) == 4
    assert all(bond.a == 0 or bond.b == 0 for bond in bonds)


def test_hydrogen_never_bonds_to_hydrogen() -> None:
    atoms = [atom(0, "H", (0, 0, 0)), atom(1, "H", (0.74, 0, 0))]
    assert pairs(atoms) == set()


def test_metals_are_not_drawn_as_covalently_bonded() -> None:
    # Zn to O at 2.0 A is a coordination contact, not a covalent bond.
    atoms = [atom(0, "Zn", (0, 0, 0)), atom(1, "O", (2.0, 0, 0))]
    assert pairs(atoms) == set()


# --- waters -----------------------------------------------------------------
def test_water_oxygen_does_not_bond_to_a_nearby_carbon() -> None:
    atoms = [
        atom(0, "O", (0, 0, 0), residue_index=0, is_water=True),
        atom(1, "C", (1.4, 0, 0), residue_index=1),
    ]
    residues = [
        residue(0, "HOH", is_amino_acid=False, is_water=True),
        residue(1, "ALA"),
    ]
    assert pairs(atoms, residues) == set()


def test_two_waters_are_not_bonded() -> None:
    atoms = [
        atom(0, "O", (0, 0, 0), residue_index=0, is_water=True),
        atom(1, "O", (1.4, 0, 0), residue_index=1, is_water=True),
    ]
    residues = [
        residue(0, "HOH", is_amino_acid=False, is_water=True),
        residue(1, "HOH", is_amino_acid=False, is_water=True),
    ]
    assert pairs(atoms, residues) == set()


# --- polymer-aware inter-residue rules --------------------------------------
def test_peptide_bond_is_perceived_between_adjacent_residues() -> None:
    atoms = [
        atom(0, "C", (0, 0, 0), name="C", residue_index=0),
        atom(1, "N", (1.33, 0, 0), name="N", residue_index=1),
    ]
    residues = [residue(0, "ALA"), residue(1, "GLY")]
    assert pairs(atoms, residues) == {(0, 1)}


def test_ca_ca_contact_is_not_a_bond() -> None:
    atoms = [
        atom(0, "C", (0, 0, 0), name="CA", residue_index=0),
        atom(1, "C", (3.80, 0, 0), name="CA", residue_index=1),
    ]
    residues = [residue(0, "ALA"), residue(1, "GLY")]
    assert pairs(atoms, residues) == set()


def test_backbone_carbon_does_not_bond_to_a_distant_residue_nitrogen() -> None:
    # C(i) to N(i+2) is not a peptide bond even if the geometry is close.
    atoms = [
        atom(0, "C", (0, 0, 0), name="C", residue_index=0),
        atom(1, "N", (1.40, 0, 0), name="N", residue_index=2),
    ]
    residues = [residue(0, "ALA"), residue(1, "GLY"), residue(2, "SER")]
    assert pairs(atoms, residues) == set()


def test_disulfide_is_perceived_across_a_long_sequence_distance() -> None:
    atoms = [
        atom(0, "S", (0, 0, 0), name="SG", residue_index=21),
        atom(1, "S", (2.05, 0, 0), name="SG", residue_index=156),
    ]
    residues = [residue(21, "CYS"), residue(156, "CYS")]
    assert pairs(atoms, residues) == {(0, 1)}


def test_sulfur_contact_too_long_for_a_disulfide_is_not_bonded() -> None:
    atoms = [
        atom(0, "S", (0, 0, 0), name="SG", residue_index=21),
        atom(1, "S", (2.8, 0, 0), name="SG", residue_index=156),
    ]
    residues = [residue(21, "CYS"), residue(156, "CYS")]
    assert pairs(atoms, residues) == set()


def test_covalent_ligand_link_is_perceived_but_a_contact_is_not() -> None:
    residues = [residue(0, "CYS"), residue(400, "LIG", is_amino_acid=False)]
    covalent = [
        atom(0, "S", (0, 0, 0), name="SG", residue_index=0),
        atom(1, "C", (1.81, 0, 0), name="C1", residue_index=400),
    ]
    assert pairs(covalent, residues) == {(0, 1)}

    contact = [
        atom(0, "S", (0, 0, 0), name="SG", residue_index=0),
        atom(1, "C", (3.20, 0, 0), name="C1", residue_index=400),
    ]
    assert pairs(contact, residues) == set()


def test_intra_residue_bonds_still_perceived_with_residues_supplied() -> None:
    atoms = [
        atom(0, "C", (0, 0, 0), name="C1", residue_index=0),
        atom(1, "O", (1.23, 0, 0), name="O1", residue_index=0),
    ]
    residues = [residue(0, "LIG", is_amino_acid=False)]
    assert pairs(atoms, residues) == {(0, 1)}


def test_without_residue_information_perception_is_distance_only() -> None:
    atoms = [
        atom(0, "C", (0, 0, 0), residue_index=0),
        atom(1, "C", (1.54, 0, 0), residue_index=5),
    ]
    assert pairs(atoms, None) == {(0, 1)}


# --- merging and validation -------------------------------------------------
def test_merge_bonds_keeps_the_primary_entry() -> None:
    file_bond = Bond(a=0, b=1, order=2, source="file")
    geometry_bond = Bond(a=0, b=1, order=1, source="geometry")
    merged = merge_bonds([file_bond], [geometry_bond, Bond(a=1, b=2, source="geometry")])
    assert len(merged) == 2
    kept = next(bond for bond in merged if bond.as_tuple() == (0, 1))
    assert kept.source == "file"
    assert kept.order == 2


def test_merge_bonds_is_order_independent_for_duplicates() -> None:
    merged = merge_bonds([Bond(a=3, b=1, source="file")], [Bond(a=1, b=3, source="geometry")])
    assert len(merged) == 1


def test_validate_bond_lengths_flags_a_too_long_bond() -> None:
    atoms = [atom(0, "C", (0, 0, 0)), atom(1, "C", (2.4, 0, 0))]
    problems = validate_bond_lengths(atoms, [Bond(a=0, b=1)])
    assert len(problems) == 1
    assert problems[0]["elements"] == ["C", "C"]
    assert problems[0]["distance"] == pytest.approx(2.4)


def test_validate_bond_lengths_flags_an_impossibly_short_bond() -> None:
    atoms = [atom(0, "C", (0, 0, 0)), atom(1, "C", (0.2, 0, 0))]
    assert len(validate_bond_lengths(atoms, [Bond(a=0, b=1)])) == 1


def test_validate_bond_lengths_accepts_a_normal_bond() -> None:
    atoms = [atom(0, "C", (0, 0, 0)), atom(1, "O", (1.23, 0, 0))]
    assert validate_bond_lengths(atoms, [Bond(a=0, b=1)]) == []
