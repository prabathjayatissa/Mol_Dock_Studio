"""Viewer packet contract.

The packet is the interface between the backend and the 3D engine, so its
invariants are tested explicitly: parallel arrays stay aligned, residue slices
are contiguous, and every index into an atom array is in range.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.io.packet import PACKET_VERSION, build_packet, packet_size_bytes
from app.services.io.parsers import parse_structure_file

ATOM_FIELDS = (
    "x",
    "y",
    "z",
    "element",
    "radius",
    "covalentRadius",
    "color",
    "residueIndex",
    "chainIndex",
    "serial",
    "formalCharge",
    "bfactor",
    "occupancy",
    "altloc",
    "isHetero",
    "isWater",
    "isBackbone",
    "name",
    "bondCount",
)


def make_packet(sample_data: Path, filename: str = "1UBQ.pdb", fmt: str = "pdb"):
    structure = parse_structure_file(sample_data / filename, fmt, name=filename, source="test")
    return structure, build_packet(structure, structure_id="str_test", kind="protein")


def test_packet_arrays_are_parallel(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    atoms = packet["atoms"]
    count = structure.atom_count
    for field in ATOM_FIELDS:
        assert field in atoms
        assert len(atoms[field]) == count, field
    assert len(atoms["partialCharge"]) == count
    assert len(atoms["autodockType"]) == count


def test_packet_metadata_matches_the_structure(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    assert packet["packetVersion"] == PACKET_VERSION
    assert packet["structure"]["id"] == "str_test"
    assert packet["structure"]["kind"] == "protein"
    assert packet["structure"]["atoms"] == structure.atom_count
    assert packet["structure"]["residues"] == len(structure.residues)
    assert packet["structure"]["bonds"] == len(structure.bonds)
    assert packet["structure"]["format"] == "pdb"
    assert packet["statistics"]["atoms"] == structure.atom_count


def test_residue_slices_are_contiguous_and_cover_every_atom(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    covered = 0
    for residue in packet["residues"]:
        start = residue["atomStart"]
        count = residue["atomCount"]
        assert start == covered, f"residue {residue['label']} is not contiguous"
        assert count > 0
        # Every atom in the slice must point back at this residue.
        for index in range(start, start + count):
            assert packet["atoms"]["residueIndex"][index] == residue["index"]
        covered += count
    assert covered == structure.atom_count


def test_every_bond_index_is_in_range(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    count = structure.atom_count
    for a, b in zip(packet["bonds"]["a"], packet["bonds"]["b"], strict=True):
        assert 0 <= a < count
        assert 0 <= b < count
        assert a != b
    assert len(packet["bonds"]["order"]) == len(packet["bonds"]["a"])
    assert len(packet["bonds"]["aromatic"]) == len(packet["bonds"]["a"])
    assert len(packet["bonds"]["source"]) == len(packet["bonds"]["a"])


def test_bond_count_array_matches_the_bond_list(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    expected = [0] * structure.atom_count
    for a, b in zip(packet["bonds"]["a"], packet["bonds"]["b"], strict=True):
        expected[a] += 1
        expected[b] += 1
    assert packet["atoms"]["bondCount"] == expected


def test_backbone_pointers_are_in_range(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    count = structure.atom_count
    for residue in packet["residues"]:
        if not residue["isAminoAcid"]:
            continue
        for key in ("caIndex", "nIndex", "cIndex", "oIndex"):
            value = residue[key]
            if value is not None:
                assert 0 <= value < count, key
                atom_name = packet["atoms"]["name"][value]
                assert atom_name


def test_chains_are_reported_with_their_kind_and_range(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    assert [chain["id"] for chain in packet["chains"]] == [c.id for c in structure.chains]
    chain = packet["chains"][0]
    assert chain["kind"] == "polymer"
    assert chain["residueCount"] == structure.chains[0].residue_count
    assert chain["label"] == f"Chain {chain['id']}"


def test_warnings_are_serialised(sample_data: Path) -> None:
    _, packet = make_packet(sample_data, "3PTB.pdb")
    codes = {warning["code"] for warning in packet["warnings"]}
    assert "no_secondary_structure" not in codes
    for warning in packet["warnings"]:
        assert warning["severity"] in {"info", "warning", "error"}
        assert warning["message"]


def test_ligand_residue_details_are_present(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data, "benzamidine.sdf", "sdf")
    residue = packet["residues"][0]
    assert residue["isHetero"] is False or residue["isHetero"] is True
    assert residue["smiles"]
    assert residue["atomCount"] == structure.atom_count


def test_sequences_are_carried(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    assert packet["sequences"]["A"] == structure.sequences["A"]
    assert len(packet["sequences"]["A"]) == 76


def test_packet_is_json_serialisable_and_reasonably_sized(sample_data: Path) -> None:
    structure, packet = make_packet(sample_data)
    # Compare like with like: `packet_size_bytes` measures the compact encoding
    # that starlette's JSONResponse actually puts on the wire, not the
    # whitespace-separated form bare json.dumps() produces.
    encoded = json.dumps(packet, separators=(",", ":"))
    assert len(encoded) > 0
    size = packet_size_bytes(packet)
    assert size == len(encoded.encode("utf-8"))
    # 660 atoms; a very loose ceiling that still catches accidental per-atom
    # object blobs being added.
    assert size < 1_500_000


def test_properties_and_provenance_pass_through() -> None:
    from app.services.io.types import ParsedStructure

    structure = ParsedStructure(format="pdb", name="empty")
    packet = build_packet(
        structure,
        structure_id="str_x",
        kind="protein",
        properties={"note": "hello"},
        provenance={"tool": "gemmi"},
    )
    assert packet["properties"] == {"note": "hello"}
    assert packet["provenance"] == {"tool": "gemmi"}
    assert packet["atoms"]["x"] == []
