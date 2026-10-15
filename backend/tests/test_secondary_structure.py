"""Secondary-structure assignment: file records first, geometry as a fallback."""

from __future__ import annotations

import math

import pytest

from app.services.io.secondary_structure import (
    apply_file_secondary_structure,
    assign_geometric_secondary_structure,
    build_ss_warning,
)
from app.services.io.types import Residue


def make_residue(index: int, *, chain_label: str = "A", chain_index: int = 0, ca: bool = True) -> Residue:
    return Residue(
        index=index,
        name="ALA",
        seq=index,
        chain_index=chain_index,
        atom_start=0,
        atom_count=1,
        is_amino_acid=True,
        ca_index=0 if ca else None,
        chain_label=chain_label,
    )


def ideal_helix(count: int, *, radius: float = 2.3, rise: float = 1.5, turn_deg: float = 100.0):
    residues = [make_residue(i) for i in range(count)]
    coords = {}
    for i in range(count):
        angle = math.radians(turn_deg * i)
        coords[i] = (radius * math.cos(angle), radius * math.sin(angle), rise * i)
    return residues, coords


def extended_chain(count: int, *, spacing: float = 3.8):
    residues = [make_residue(i) for i in range(count)]
    coords = {i: (spacing * i, 0.0, 0.0) for i in range(count)}
    return residues, coords


def two_strands(count: int = 6, *, spacing: float = 3.3, separation: float = 4.8):
    residues = [make_residue(i) for i in range(count * 2)]
    coords = {}
    for i in range(count):
        coords[i] = (spacing * i, 0.0, 0.0)
    for i in range(count):
        coords[count + i] = (spacing * i, separation, 0.0)
    return residues, coords


# --- geometric heuristic ----------------------------------------------------
def test_ideal_alpha_helix_geometry_is_detected() -> None:
    residues, coords = ideal_helix(14)
    assigned = assign_geometric_secondary_structure(residues, coords)
    assert assigned > 0
    helix = [residue for residue in residues if residue.ss == "H"]
    assert len(helix) >= 8


def test_ideal_helix_has_the_expected_ca_distances() -> None:
    """Sanity-check the fixture itself against textbook alpha-helix geometry."""
    _, coords = ideal_helix(10)
    assert math.dist(coords[0], coords[1]) == pytest.approx(3.8, abs=0.1)
    assert math.dist(coords[0], coords[3]) == pytest.approx(5.0, abs=0.2)
    assert math.dist(coords[0], coords[4]) == pytest.approx(6.2, abs=0.2)


def test_extended_chain_is_coil() -> None:
    residues, coords = extended_chain(12)
    assigned = assign_geometric_secondary_structure(residues, coords)
    assert assigned == 0
    assert all(residue.ss == "C" for residue in residues)


def test_two_close_strands_are_assigned_as_sheet() -> None:
    residues, coords = two_strands(6)
    assign_geometric_secondary_structure(residues, coords)
    sheet = [residue for residue in residues if residue.ss == "E"]
    assert len(sheet) >= 6


def test_fewer_than_four_residues_are_left_as_coil() -> None:
    residues, coords = ideal_helix(3)
    assert assign_geometric_secondary_structure(residues, coords) == 0
    assert all(residue.ss == "C" for residue in residues)


def test_geometric_does_not_overwrite_existing_assignments() -> None:
    residues, coords = ideal_helix(14)
    residues[0].ss = "E"
    assign_geometric_secondary_structure(residues, coords)
    assert residues[0].ss == "E"


# --- file records -----------------------------------------------------------
def test_file_ranges_are_applied() -> None:
    residues = [make_residue(i) for i in range(10)]
    ranges = {"H": [("A", 2, " ", "A", 6, " ")]}
    relabelled = apply_file_secondary_structure(residues, ranges)
    assert relabelled == 5
    assert [residue.ss for residue in residues] == ["C", "C", "H", "H", "H", "H", "H", "C", "C", "C"]


def test_reversed_sheet_range_is_normalised() -> None:
    residues = [make_residue(i) for i in range(10)]
    # Some SHEET records list the end before the start.
    ranges = {"E": [("A", 7, " ", "A", 3, " ")]}
    relabelled = apply_file_secondary_structure(residues, ranges)
    assert relabelled == 5
    assert [residue.ss for residue in residues].count("E") == 5


def test_ranges_for_another_chain_are_ignored() -> None:
    residues = [make_residue(i, chain_label="A") for i in range(5)]
    residues += [make_residue(i, chain_label="B", chain_index=1) for i in range(5)]
    apply_file_secondary_structure(residues, {"H": [("B", 0, " ", "B", 4, " ")]})
    assert all(residue.ss == "C" for residue in residues[:5])
    assert all(residue.ss == "H" for residue in residues[5:])


def test_insertion_codes_are_respected() -> None:
    plain = make_residue(0)
    plain.seq = 2
    coded = make_residue(1)
    coded.seq = 2
    coded.insertion_code = "A"
    # Residue 2 exists twice: a plain one and an insertion-coded one.
    relabelled = apply_file_secondary_structure(
        [plain, coded], {"H": [("A", 2, " ", "A", 2, " ")]}
    )
    # The range names residue 2 with no insertion code, so only the plain copy is
    # relabelled; the 2A copy keeps its own assignment.
    assert relabelled == 1
    assert plain.ss == "H"
    assert coded.ss == "C"


def test_overlapping_records_keep_the_first_type() -> None:
    residues = [make_residue(i) for i in range(6)]
    ranges = {"H": [("A", 0, " ", "A", 3, " ")], "E": [("A", 2, " ", "A", 5, " ")]}
    apply_file_secondary_structure(residues, ranges)
    # "H" is processed before "E"; a residue already labelled H is not counted
    # again, but "E" still wins for residues that were coil.
    assert [residue.ss for residue in residues] == ["H", "H", "H", "H", "E", "E"]


# --- warnings ---------------------------------------------------------------
def test_warning_when_no_secondary_structure_is_present() -> None:
    residues = [make_residue(i) for i in range(5)]
    warning = build_ss_warning(residues, "geometric-ca-heuristic")
    assert warning is not None
    assert warning.code == "no_secondary_structure"
    assert warning.severity == "info"


def test_no_warning_when_secondary_structure_exists() -> None:
    residues = [make_residue(i) for i in range(5)]
    residues[0].ss = "H"
    assert build_ss_warning(residues, "file-records") is None
