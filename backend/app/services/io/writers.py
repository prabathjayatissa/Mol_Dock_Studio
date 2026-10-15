"""Coordinate writers.

Export is a first-class feature: what the user exports must be readable by other
tools, and MolDock Studio must be able to read its own output back (round-trip
tests in ``tests/test_export.py`` cover exactly that).

Formats: PDB, PDBx/mmCIF, SDF (RDKit), MOL2 and XYZ. All writers are explicit
about their limitations — an SDF export of a 40 kDa protein is a bad idea, so
:func:`export_structure` refuses it instead of writing something surprising.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from pathlib import Path

from app.core.errors import ValidationFailure
from app.services.io.types import Atom, ParsedStructure

ExportFormat = str
PDB_FREE_FORMAT_ATOM_LIMIT = 99_999


def _pdb_atom_line(atom: Atom, residue, chain_id: str, serial: int) -> str:
    record = "HETATM" if atom.is_hetero else "ATOM  "
    name = atom.name
    # PDB convention: element right-justified in columns 13-14 for one-letter
    # elements, i.e. " N  " rather than "N   ".
    if len(name) < 4 and len(element_symbol := atom.element) == 1:
        name_field = f" {name:<3}"[:4]
        del element_symbol
    else:
        name_field = f"{name:<4}"[:4]
    charge_field = f"{atom.formal_charge:+d}" if atom.formal_charge else "  "
    return (
        f"{record}{serial:>5} {name_field}{atom.altloc or ' ':1}"
        f"{(residue.name[:3] if residue else 'UNK'):>3} {chain_id[:1]:1}"
        f"{(residue.seq if residue else 1):>4}{(residue.insertion_code if residue else '')[:1] or ' ':1}   "
        f"{atom.x:>8.3f}{atom.y:>8.3f}{atom.z:>8.3f}"
        f"{atom.occupancy:>6.2f}{atom.bfactor:>6.2f}          "
        f"{atom.element:>2}{charge_field}"
    )


def write_pdb(structure: ParsedStructure, *, entry_id: str = "MOLDOCK") -> str:
    if structure.atom_count > PDB_FREE_FORMAT_ATOM_LIMIT:
        raise ValidationFailure(
            f"PDB format cannot represent {structure.atom_count} atoms with more than 99,999 serial "
            "numbers in this writer.",
            remediation="Export as mmCIF, or export a subset (a chain or a chain selection).",
        )
    now = dt.datetime.now(dt.UTC).strftime("%d-%b-%y").upper()
    lines: list[str] = [
        f"HEADER    MOLDOCK STUDIO EXPORT{' ' * 22}{entry_id[:4]:>4}{now}",
        f"TITLE     {structure.name[:70]}",
    ]

    # SEQRES per chain, using the three-letter residue names of the polymer
    # residues actually present (a faithful record of what was exported).
    for chain in structure.chains:
        polymer = [
            residue
            for residue in structure.residues
            if residue.chain_index == chain.index and residue.is_amino_acid
        ]
        if not polymer:
            continue
        names = [residue.name[:3].upper() for residue in polymer]
        for start in range(0, len(names), 13):
            chunk = " ".join(names[start : start + 13])
            lines.append(f"SEQRES {1 + start // 13:>3} {chain.id[:1]} {len(names):>4}  {chunk}")

    previous_chain: str | None = None
    serial_by_atom: dict[int, int] = {}
    for serial, atom in enumerate(structure.atoms, start=1):
        residue = structure.residues[atom.residue_index]
        chain_id = structure.chains[atom.chain_index].id if atom.chain_index < len(structure.chains) else "A"
        if previous_chain is not None and chain_id != previous_chain:
            lines.append("TER")
        previous_chain = chain_id
        serial_by_atom[atom.index] = serial
        lines.append(_pdb_atom_line(atom, residue, chain_id, serial))
    lines.append("TER")

    # CONECT records (mirrors what we read back) must precede the trailing END.
    if structure.bonds:
        partners: dict[int, list[int]] = {}
        for bond in structure.bonds:
            if bond.a in serial_by_atom and bond.b in serial_by_atom:
                partners.setdefault(serial_by_atom[bond.a], []).append(serial_by_atom[bond.b])
        for atom_serial in sorted(partners):
            targets = partners[atom_serial][:4]
            lines.append(f"CONECT{atom_serial:>5}" + "".join(f"{target:>5}" for target in targets))

    lines.append("END")
    return "\n".join(lines) + "\n"


def write_mmcif(structure: ParsedStructure, *, entry_id: str = "MOLDOCK") -> str:
    lines = [
        f"data_{entry_id}",
        "#",
        f"_entry.id   {entry_id}",
        f"_struct.title   '{structure.name[:200]}'",
        "#",
        "loop_",
        "_atom_site.group_PDB",
        "_atom_site.id",
        "_atom_site.type_symbol",
        "_atom_site.label_atom_id",
        "_atom_site.label_alt_id",
        "_atom_site.label_comp_id",
        "_atom_site.label_asym_id",
        "_atom_site.label_seq_id",
        "_atom_site.pdbx_formal_charge",
        "_atom_site.Cartn_x",
        "_atom_site.Cartn_y",
        "_atom_site.Cartn_z",
        "_atom_site.occupancy",
        "_atom_site.B_iso_or_equiv",
        "_atom_site.auth_seq_id",
        "_atom_site.auth_comp_id",
        "_atom_site.auth_asym_id",
        "_atom_site.auth_atom_id",
        "_atom_site.pdbx_PDB_model_num",
    ]
    serial_by_atom: dict[int, int] = {}
    for serial, atom in enumerate(structure.atoms, start=1):
        residue = structure.residues[atom.residue_index]
        chain_id = structure.chains[atom.chain_index].id if atom.chain_index < len(structure.chains) else "A"
        serial_by_atom[atom.index] = serial
        lines.append(
            f"{'HETATM' if atom.is_hetero else 'ATOM'} {serial} {atom.element} "
            f"{atom.name} {atom.altloc or '.'} {residue.name} {chain_id} {serial} "
            f"{atom.formal_charge} {atom.x:.3f} {atom.y:.3f} {atom.z:.3f} "
            f"{atom.occupancy:.2f} {atom.bfactor:.2f} {residue.seq} {residue.name} {chain_id} {atom.name} 1"
        )
    lines.append("#")
    return "\n".join(lines) + "\n"


def write_xyz(structure: ParsedStructure, *, comment: str | None = None) -> str:
    header = comment or f"{structure.name} exported by MolDock Studio"
    lines = [str(structure.atom_count), header]
    for atom in structure.atoms:
        lines.append(f"{atom.element:<3} {atom.x:>12.5f} {atom.y:>12.5f} {atom.z:>12.5f}")
    return "\n".join(lines) + "\n"


def write_mol2(structure: ParsedStructure) -> str:
    """Tripos MOL2 with generic Sybyl types (C.3/N.3/O.2/...) inferred from geometry."""
    lines = [
        "@<TRIPOS>MOLECULE",
        structure.name[:200] or "MOLDOCK",
        f"{structure.atom_count} {len(structure.bonds)} 1 0 0",
        "SMALL",
        "USER_CHARGES",
        "",
        "@<TRIPOS>ATOM",
    ]
    types = _sybyl_types(structure)
    for index, atom in enumerate(structure.atoms, start=1):
        residue = structure.residues[atom.residue_index]
        chain_id = structure.chains[atom.chain_index].id if atom.chain_index < len(structure.chains) else "A"
        charge = atom.partial_charge if atom.partial_charge is not None else float(atom.formal_charge)
        lines.append(
            f"{index:>7} {atom.name:<4} {atom.x:>10.4f} {atom.y:>10.4f} {atom.z:>10.4f} "
            f"{types[atom.index]:<6} {residue.index + 1:>4} {residue.name[:8]:<8} {charge:>9.4f}"
        )
    lines.append("@<TRIPOS>BOND")
    for bond_index, bond in enumerate(structure.bonds, start=1):
        bond_type = {1: "1", 2: "2", 3: "3"}.get(bond.order, "1")
        if bond.aromatic:
            bond_type = "ar"
        lines.append(f"{bond_index:>6} {bond.a + 1:>5} {bond.b + 1:>5} {bond_type}")
    lines.append("@<TRIPOS>SUBSTRUCTURE")
    for residue in structure.residues:
        if residue.atom_count:
            chain_id = structure.chains[residue.chain_index].id if residue.chain_index < len(structure.chains) else "A"
            lines.append(
                f"{residue.index + 1:>6} {residue.name[:8]:<8} {residue.atom_start + 1:>6} "
                f"GROUP 1 {chain_id[:8]:<8} {residue.seq:>4} {residue.one_letter[:1]}"
            )
    lines.append("")
    return "\n".join(lines)


def _sybyl_types(structure: ParsedStructure) -> dict[int, str]:
    """Rough Sybyl atom typing from element, aromaticity and hydrogen count."""
    hydrogen_counts: dict[int, int] = {}
    aromatic_atoms: set[int] = set()
    for bond in structure.bonds:
        for atom_index in (bond.a, bond.b):
            if structure.atoms[atom_index].element == "H":
                hydrogen_counts[bond.b if atom_index == bond.a else bond.a] = (
                    hydrogen_counts.get(bond.b if atom_index == bond.a else bond.a, 0) + 1
                )
        if bond.aromatic:
            aromatic_atoms.update({bond.a, bond.b})

    types: dict[int, str] = {}
    for atom in structure.atoms:
        symbol = atom.element
        if symbol == "C":
            if atom.index in aromatic_atoms:
                types[atom.index] = "C.ar"
            else:
                types[atom.index] = {4: "C.3", 3: "C.2", 2: "C.1"}.get(
                    hydrogen_counts.get(atom.index, 0), "C.3"
                )
        elif symbol == "N":
            types[atom.index] = "N.am" if atom.index not in aromatic_atoms else "N.ar"
        elif symbol == "O":
            types[atom.index] = "O.3" if hydrogen_counts.get(atom.index) else "O.2"
        elif symbol == "S":
            types[atom.index] = "S.3"
        elif symbol == "H":
            types[atom.index] = "H"
        else:
            types[atom.index] = symbol
    return types


def write_sdf(structure: ParsedStructure, *, name: str | None = None) -> str:
    """SDF via RDKit, rebuilt from our atoms and perceived bonds."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit.Geometry import Point3D

    molecule = Chem.RWMol()
    conformer = Chem.Conformer(structure.atom_count)
    conformer.Set3D(True)
    for atom in structure.atoms:
        rd_atom = Chem.Atom(atom.element)
        rd_atom.SetFormalCharge(atom.formal_charge)
        atom_index = molecule.AddAtom(rd_atom)
        conformer.SetAtomPosition(atom_index, Point3D(atom.x, atom.y, atom.z))
    for bond in structure.bonds:
        bond_type = {
            1: Chem.BondType.SINGLE,
            2: Chem.BondType.DOUBLE,
            3: Chem.BondType.TRIPLE,
        }.get(bond.order, Chem.BondType.SINGLE)
        if bond.aromatic:
            # An aromatic ring is not a set of double bonds. The parser stores
            # aromatic bonds with order 2 (RDKit reports 1.5), so writing every
            # one of them as a double bond gives each ring carbon two double
            # bonds — a valence of five, which RDKit rejects on re-read. Write it
            # as an aromatic bond and let RDKit re-kekulise the mol block.
            bond_type = Chem.BondType.AROMATIC
            for atom_index in (bond.a, bond.b):
                if 0 <= atom_index < molecule.GetNumAtoms():
                    molecule.GetAtomWithIdx(atom_index).SetIsAromatic(True)
        try:
            molecule.AddBond(bond.a, bond.b, bond_type)
        except Exception:  # noqa: BLE001 - duplicate/self bonds are skipped
            continue

    mol = molecule.GetMol()
    mol.AddConformer(conformer, assignId=True)
    mol.SetProp("_Name", (name or structure.name)[:200])
    with contextlib.suppress(Exception):
        Chem.SanitizeMol(mol, catchErrors=True)
    AllChem.AssignStereochemistry(mol, cleanIt=False, force=True)
    return Chem.MolToMolBlock(mol, forceV3000=structure.atom_count > 999) + "$$$$\n"


def export_structure(structure: ParsedStructure, fmt: str, *, name: str | None = None) -> tuple[str, str]:
    """Return ``(content, filename)`` for the requested export format."""
    base = (name or structure.name or "structure").replace(" ", "_")
    if fmt == "pdb":
        return write_pdb(structure), f"{base}.pdb"
    if fmt == "mmcif":
        return write_mmcif(structure), f"{base}.cif"
    if fmt in {"sdf", "mol"}:
        is_macromolecule = any(
            residue.is_amino_acid or residue.is_nucleic for residue in structure.residues
        )
        if is_macromolecule or structure.atom_count > 2000:  # noqa: PLR2004
            raise ValidationFailure(
                "SDF export is intended for small molecules; this structure has "
                f"{structure.atom_count} atoms.",
                remediation="Export as PDB or mmCIF for macromolecules.",
            )
        return write_sdf(structure, name=name), f"{base}.sdf"
    if fmt == "mol2":
        return write_mol2(structure), f"{base}.mol2"
    if fmt == "xyz":
        return write_xyz(structure), f"{base}.xyz"
    raise ValidationFailure(
        f"Unsupported export format '{fmt}'.",
        detail={"supported": ["pdb", "mmcif", "sdf", "mol", "mol2", "xyz"]},
    )


def write_structure_file(structure: ParsedStructure, path: Path, fmt: str) -> Path:
    content, _filename = export_structure(structure, fmt)
    path.write_text(content, encoding="utf-8")
    return path
