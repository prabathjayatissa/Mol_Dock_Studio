"""Structure packet: the transport format between backend and viewer.

The packet is a compact, column-oriented payload. Coordinates and per-atom
flags arrive as parallel arrays so the frontend can hand them to typed arrays
and GPU buffers without any per-atom object allocation.

Design notes
------------
* Atoms are sorted by (chain, residue, atom) at parse time, so every residue is
  a contiguous slice ``[atom_start, atom_start + atom_count)``. That makes
  residue selection, cartoons and surfaces O(1) per residue.
* Nothing is rounded beyond 4 decimals (0.1 mÅ), far below any meaningful
  structural precision.
* A future binary transport for very large structures is documented in
  docs/architecture.md; the JSON packet is measured in tests so the switch is
  data-driven rather than speculative.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.chemistry.elements import element_by_symbol, residue_info
from app.services.io.types import ParsedStructure

PACKET_VERSION = 1


def build_packet(
    structure: ParsedStructure,
    *,
    structure_id: str,
    kind: str,
    properties: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the viewer packet for a parsed structure."""
    atom_count = len(structure.atoms)
    resolves_residues = len(structure.residues)

    atoms: dict[str, list[Any]] = {
        "x": [0.0] * atom_count,
        "y": [0.0] * atom_count,
        "z": [0.0] * atom_count,
        "element": [""] * atom_count,
        "radius": [0.0] * atom_count,
        "covalentRadius": [0.0] * atom_count,
        "color": [""] * atom_count,
        "residueIndex": [0] * atom_count,
        "chainIndex": [0] * atom_count,
        "serial": [0] * atom_count,
        "formalCharge": [0] * atom_count,
        "partialCharge": [None] * atom_count,
        "bfactor": [0.0] * atom_count,
        "occupancy": [1.0] * atom_count,
        "altloc": [""] * atom_count,
        "isHetero": [False] * atom_count,
        "isWater": [False] * atom_count,
        "isBackbone": [False] * atom_count,
        "name": [""] * atom_count,
        "autodockType": [None] * atom_count,
    }

    for atom in structure.atoms:
        index = atom.index
        info = element_by_symbol(atom.element)
        atoms["x"][index] = atom.x
        atoms["y"][index] = atom.y
        atoms["z"][index] = atom.z
        atoms["element"][index] = atom.element
        atoms["radius"][index] = info.vdw_radius
        atoms["covalentRadius"][index] = info.covalent_radius
        atoms["color"][index] = info.color
        atoms["residueIndex"][index] = atom.residue_index
        atoms["chainIndex"][index] = atom.chain_index
        atoms["serial"][index] = atom.serial
        atoms["formalCharge"][index] = atom.formal_charge
        atoms["partialCharge"][index] = (
            round(atom.partial_charge, 4) if atom.partial_charge is not None else None
        )
        atoms["bfactor"][index] = round(atom.bfactor, 3)
        atoms["occupancy"][index] = round(atom.occupancy, 3)
        atoms["altloc"][index] = atom.altloc
        atoms["isHetero"][index] = atom.is_hetero
        atoms["isWater"][index] = atom.is_water
        atoms["isBackbone"][index] = atom.is_backbone
        atoms["name"][index] = atom.name
        atoms["autodockType"][index] = atom.autodock_type

    chain_ids = [chain.id for chain in structure.chains]
    residues: list[dict[str, Any]] = []
    for residue in structure.residues:
        chain_label = chain_ids[residue.chain_index] if residue.chain_index < len(chain_ids) else "?"
        info = residue_info(residue.name)
        residues.append(
            {
                "index": residue.index,
                "name": residue.name,
                "seq": residue.seq,
                "insertionCode": residue.insertion_code,
                "chainIndex": residue.chain_index,
                "chainId": chain_label,
                "label": f"{residue.name} {residue.seq}{residue.insertion_code}".strip(),
                "ss": residue.ss,
                "isHetero": residue.is_hetero,
                "isWater": residue.is_water,
                "isAminoAcid": residue.is_amino_acid,
                "isNucleic": residue.is_nucleic,
                "oneLetter": residue.one_letter,
                "residueType": str(info.get("type", "")) if info else "",
                "hydropathy": float(info.get("hydropathy", 0.0)) if info else 0.0,
                "atomStart": residue.atom_start,
                "atomCount": residue.atom_count,
                "caIndex": residue.ca_index,
                "nIndex": residue.n_index,
                "cIndex": residue.c_index,
                "oIndex": residue.o_index,
                "cbIndex": residue.cb_index,
                "title": residue.title,
                "smiles": residue.smiles,
            }
        )

    bonds = {
        "a": [bond.a for bond in structure.bonds],
        "b": [bond.b for bond in structure.bonds],
        "order": [bond.order for bond in structure.bonds],
        "aromatic": [bond.aromatic for bond in structure.bonds],
        "source": [bond.source for bond in structure.bonds],
    }

    bonds_per_atom = [0] * atom_count
    for bond in structure.bonds:
        if 0 <= bond.a < atom_count:
            bonds_per_atom[bond.a] += 1
        if 0 <= bond.b < atom_count:
            bonds_per_atom[bond.b] += 1
    atoms["bondCount"] = bonds_per_atom

    bounds = structure.bounds()
    center = structure.centroid()
    packet = {
        "packetVersion": PACKET_VERSION,
        "structure": {
            "id": structure_id,
            "name": structure.name,
            "kind": kind,
            "format": structure.format,
            "source": structure.source,
            "atoms": atom_count,
            "residues": resolves_residues,
            "chains": len(structure.chains),
            "bonds": len(structure.bonds),
            "hasCoordinates": structure.has_coordinates,
            "centroid": [round(value, 3) for value in center],
            "bounds": bounds,
            "radius": round(structure.bounding_radius(), 3),
        },
        "chains": [
            {
                "index": chain.index,
                "id": chain.id,
                "kind": chain.kind,
                "residueStart": chain.residue_start,
                "residueCount": chain.residue_count,
                "label": f"Chain {chain.id}",
            }
            for chain in structure.chains
        ],
        "residues": residues,
        "atoms": atoms,
        "bonds": bonds,
        "sequences": structure.sequences,
        "secondaryStructure": structure.metadata.get("secondary_structure_method", "unknown"),
        "statistics": structure.summary(),
        "warnings": [warning.as_dict() for warning in structure.warnings],
        "metadata": structure.metadata,
        "properties": properties or {},
        "provenance": provenance or {},
    }
    return packet


def packet_size_bytes(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, separators=(",", ":")).encode("utf-8"))
