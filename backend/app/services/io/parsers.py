"""Structure parsers.

One entry point, :func:`parse_structure_file`, dispatching to a parser per
format family:

* ``pdb``/``mmcif``  -> gemmi (authoritative PDB/mmCIF semantics)
* ``sdf``/``mol``/``mol2``/``xyz`` -> RDKit (real bond orders, charges)
* ``pdbqt``          -> built-in reader (AutoDock conventions; no RDKit parser exists)
* ``fasta``          -> Biopython (sequence only, no coordinates)

Every parser reports what it changed or dropped through
``ParsedStructure.warnings``: nothing is discarded silently.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import StructureParseError, UnsupportedFormatError, ValidationFailure
from app.services.chemistry.elements import (
    AMINO_ACIDS,
    element_by_symbol,
    is_amino_acid,
    is_water,
    residue_info,
)
from app.services.io.bonds import infer_bonds, merge_bonds, validate_bond_lengths
from app.services.io.secondary_structure import (
    SsrRange,
    apply_file_secondary_structure,
    assign_geometric_secondary_structure,
    build_ss_warning,
)
from app.services.io.types import Atom, Bond, Chain, ParsedStructure, Residue

BACKBONE_ATOMS = {"N", "CA", "C", "O", "OXT"}
MAX_SDF_MOLECULES = 2000

ION_RESIDUES = {
    "NA": "Na",
    "CL": "Cl",
    "K": "K",
    "MG": "Mg",
    "CA": "Ca",
    "ZN": "Zn",
    "MN": "Mn",
    "FE": "Fe",
    "FE2": "Fe",
    "CU": "Cu",
    "CO": "Co",
    "NI": "Ni",
    "CD": "Cd",
    "HG": "Hg",
    "CS": "Cs",
    "SR": "Sr",
    "BA": "Ba",
    "LI": "Li",
    "AL": "Al",
    "BR": "Br",
    "IOD": "I",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def infer_element_from_name(atom_name: str, residue_name: str) -> str:
    """Recover an element symbol when the file leaves it blank.

    Hydrogens, protein atoms (``CA`` -> C) and common ions are handled
    explicitly; the fallback is the first alphabetic character.
    """
    res = residue_name.strip().upper()
    if res in ION_RESIDUES:
        return ION_RESIDUES[res]

    name = atom_name.strip()
    if not name:
        return "X"
    if name[0].isdigit():  # e.g. "1HG1" -> hydrogen
        name = name[1:]
    if not name:
        return "X"

    letters = "".join(ch for ch in name if ch.isalpha())
    if not letters:
        return "X"
    if letters.upper() in {"H", "D"}:
        return "H"
    # Two-letter elements only appear in non-polymer (hetero) residues; inside a
    # polymer "CA" is the alpha carbon, not calcium.
    if len(letters) >= 2 and not is_amino_acid(res) and not res.startswith("D") and len(letters) == 2:
        candidate = letters.capitalize()
        if element_by_symbol(candidate).atomic_number:
            return candidate
    candidate = letters[0].upper()
    return candidate if element_by_symbol(candidate).atomic_number else "X"


def _backbone_flag(name: str) -> bool:
    return name.strip().upper() in BACKBONE_ATOMS


def _residue_kind_flags(name: str) -> tuple[bool, bool, bool]:
    """Return (is_water, is_amino_acid, is_nucleic)."""
    info = residue_info(name)
    water = is_water(name)
    nucleic = bool(info) and info.get("type") == "nucleic"
    return water, is_amino_acid(name), nucleic


def _chain_kind(residues: list[Residue], atoms_for_chain: list[Atom]) -> str:
    """Classify a chain without discarding anything.

    A PDB chain routinely mixes a polymer with waters and a bound ligand, so the
    presence of polymer residues decides the chain kind; waters and hetero
    residues stay listed and are filtered per-residue in the UI.
    """
    if not residues:
        return "other"
    if any(residue.is_amino_acid or residue.is_nucleic for residue in residues):
        return "polymer"
    if all(residue.is_water for residue in residues):
        return "water"
    if len(residues) == 1 and elements_are_ion(atoms_for_chain):
        return "ion"
    return "ligand"


def elements_are_ion(atoms: list[Atom]) -> bool:
    return all(element_by_symbol(atom.element).is_metal for atom in atoms) or (
        len(atoms) == 1 and atoms[0].element in {"Na", "Cl", "K", "Mg", "Ca", "Zn", "Mn", "Fe"}
    )


def _sequences(structure: ParsedStructure) -> dict[str, str]:
    sequences: dict[str, str] = {}
    for residue in structure.residues:
        if not residue.is_amino_acid:
            continue
        chain = structure.chains[residue.chain_index].id
        sequences.setdefault(chain, "")
        sequences[chain] += residue.one_letter if residue.one_letter != "X" else "X"
    return sequences


def finalize(
    structure: ParsedStructure,
    *,
    perceived_bonds: list[Bond] | None = None,
    keep_file_bonds: bool = True,
    perceive_bonds: bool = True,
) -> ParsedStructure:
    """Sort atoms by chain/residue, (re)index everything, and establish bonds.

    Sorting means every residue owns a contiguous atom range, which is what the
    column-oriented packet, the cartoon builder and the selection tree all rely
    on. The order of atoms *within* a residue is preserved exactly as the file
    wrote it: for SDF/MOL2/PDBQT the atom order is meaningful (it is what the
    bond block and the torsion tree refer to), so it must not be rearranged.

    ``perceive_bonds=False`` is used for formats that carry a complete
    connectivity table (SDF, MOL, MOL2). Adding perceived bonds on top of a real
    bond block would invent bonds, so the file wins outright.
    """
    if not structure.atoms:
        structure.sequences = {}
        return structure

    # 1. Group atoms by chain/residue, keeping within-residue file order, and
    #    remap every index we already hold (bonds included).
    original = list(structure.atoms)
    order = sorted(
        range(len(original)),
        key=lambda position: (
            original[position].chain_index,
            original[position].residue_index,
            position,
        ),
    )
    old_to_new = {old: new for new, old in enumerate(order)}
    structure.atoms = [original[old] for old in order]

    for new_index, atom in enumerate(structure.atoms):
        atom.index = new_index

    def remap(bonds: list[Bond]) -> list[Bond]:
        remapped: list[Bond] = []
        for bond in bonds:
            a = old_to_new.get(bond.a)
            b = old_to_new.get(bond.b)
            if a is None or b is None:
                continue
            remapped.append(Bond(a=a, b=b, order=bond.order, source=bond.source, aromatic=bond.aromatic))
        return remapped

    structure.bonds = remap(structure.bonds)
    if perceived_bonds:
        perceived_bonds = remap(perceived_bonds)

    # 2. Rebuild residue atom ranges and backbone pointers.
    residue_atoms: dict[int, list[Atom]] = {}
    for atom in structure.atoms:
        residue_atoms.setdefault(atom.residue_index, []).append(atom)

    for residue in structure.residues:
        atoms = residue_atoms.get(residue.index, [])
        residue.atom_start = atoms[0].index if atoms else 0
        residue.atom_count = len(atoms)
        residue.ca_index = residue.n_index = residue.c_index = residue.o_index = residue.cb_index = None
        for atom in atoms:
            name = atom.name.strip().upper()
            if name == "CA":
                residue.ca_index = atom.index
            elif name == "N":
                residue.n_index = atom.index
            elif name == "C":
                residue.c_index = atom.index
            elif name == "O":
                residue.o_index = atom.index
            elif name == "CB":
                residue.cb_index = atom.index

    # 3. Chains -> atom/residue ranges.
    for chain in structure.chains:
        chain.residue_start = min(
            (residue.index for residue in structure.residues if residue.chain_index == chain.index),
            default=0,
        )
        chain.residue_count = sum(
            1 for residue in structure.residues if residue.chain_index == chain.index
        )

    # 4. Bonds.
    if perceive_bonds:
        geometry_bonds = infer_bonds(structure.atoms, residues=structure.residues)
        if perceived_bonds:
            geometry_bonds = merge_bonds(perceived_bonds, geometry_bonds)
        structure.bonds = (
            merge_bonds(structure.bonds, geometry_bonds) if keep_file_bonds and structure.bonds
            else geometry_bonds
        )
    elif not structure.bonds:
        structure.bonds = []

    # 5. Secondary structure: file records win, geometry fills the gaps.
    if not any(residue.ss != "C" for residue in structure.residues):
        coords = {
            residue.index: (
                (structure.atoms[residue.ca_index].x, structure.atoms[residue.ca_index].y, structure.atoms[residue.ca_index].z)
                if residue.ca_index is not None
                else (0.0, 0.0, 0.0)
            )
            for residue in structure.residues
        }
        assigned = assign_geometric_secondary_structure(structure.residues, coords)
        structure.metadata["secondary_structure_method"] = "geometric-ca-heuristic"
        if assigned:
            structure.metadata["secondary_structure_residues"] = assigned
    else:
        structure.metadata["secondary_structure_method"] = "file-records"

    warning = build_ss_warning(structure.residues, structure.metadata["secondary_structure_method"])
    if warning:
        structure.add_warning(warning)

    # 6. Sequences and implausible-bond report. Only perceived bonds are checked:
    # a file's own bond block is authoritative, even when a bond length is unusual
    # (metal coordination, strained or transition-state geometry).
    structure.sequences = _sequences(structure)
    geometry_bonds = [bond for bond in structure.bonds if bond.source == "geometry"]
    problems = validate_bond_lengths(structure.atoms, geometry_bonds)
    if problems:
        structure.warn(
            "implausible_bond_lengths",
            f"{len(problems)} perceived bond(s) have implausible lengths and were kept for "
            "inspection only; check the source file.",
            count=len(problems),
            examples=problems[:5],
        )

    structure.metadata["bond_sources"] = sorted(
        {bond.source for bond in structure.bonds}
    )
    return structure


# ---------------------------------------------------------------------------
# gemmi (PDB, mmCIF)
# ---------------------------------------------------------------------------
def _seq_parts(obj: Any) -> tuple[int, str] | None:
    """Return ``(seq_number, insertion_code)`` from any gemmi identifier object.

    gemmi nests its identifiers differently by version and by record type::

        Residue.seqid        -> SeqId(num, icode)
        AtomAddress.res_id   -> ResidueId(seqid=SeqId, name, segment)
        Connection.partnerN.res_id -> ResidueId

    This walks the nesting instead of guessing, so HELIX/SHEET records and
    CONECT/struct_conn links are read correctly across gemmi versions.
    """
    if obj is None:
        return None
    for candidate in (obj, getattr(obj, "seqid", None), getattr(obj, "res_id", None)):
        if candidate is None:
            continue
        seqid = getattr(candidate, "seqid", candidate)
        num = getattr(seqid, "num", None)
        if num is None:
            continue
        icode = getattr(seqid, "icode", " ") or " "
        return int(num), str(icode).replace("\x00", " ")
    return None


def _endpoint_parts(obj: Any) -> tuple[str, int, str] | None:
    """``(chain, seq, icode)`` for a HELIX/SHEET/CONECT endpoint."""
    if obj is None:
        return None
    chain = getattr(obj, "chain_name", None)
    if chain is None:
        res_id = getattr(obj, "res_id", None)
        chain = getattr(res_id, "chain_name", None) if res_id is not None else None
    parts = _seq_parts(obj)
    if chain is None or parts is None:
        return None
    seq, icode = parts
    return (str(chain), seq, _norm_icode(icode))


def _norm_icode(value: Any) -> str:
    """Normalise an insertion code for comparisons.

    gemmi reports a missing insertion code as ``'\\x00'`` in some places and as
    ``' '`` or ``''`` in others, so every comparison strips and blanks it.
    """
    if value is None:
        return ""
    return str(value).replace("\x00", " ").strip()


def _gemmi_ss_ranges(structure: Any) -> dict[str, list[SsrRange]]:
    """Extract HELIX/SHEET ranges, tolerating gemmi API differences."""
    ranges: dict[str, list[SsrRange]] = {"H": [], "E": []}

    def as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        return list(value) if isinstance(value, (list, tuple)) else [value]

    try:
        for helix in getattr(structure, "helices", []) or []:
            for start, end in zip(
                as_list(getattr(helix, "start", None)),
                as_list(getattr(helix, "end", None)),
                strict=False,
            ):
                start_tuple = _endpoint_parts(start)
                end_tuple = _endpoint_parts(end)
                if start_tuple and end_tuple:
                    ranges["H"].append((*start_tuple, *end_tuple))
        for sheet in getattr(structure, "sheets", []) or []:
            for strand in getattr(sheet, "strands", []) or []:
                start_tuple = _endpoint_parts(getattr(strand, "start", None))
                end_tuple = _endpoint_parts(getattr(strand, "end", None))
                if start_tuple and end_tuple:
                    ranges["E"].append((*start_tuple, *end_tuple))
    except Exception:  # noqa: BLE001 - SS records are optional
        return {"H": [], "E": []}
    return ranges


def parse_with_gemmi(path: Path, fmt: str, *, name: str, source: str) -> ParsedStructure:
    try:
        import gemmi
    except ImportError as exc:  # pragma: no cover - dependency is required
        raise StructureParseError(
            "gemmi is required to read PDB/mmCIF files.",
            remediation="Install backend dependencies: uv sync",
        ) from exc

    try:
        doc = gemmi.read_structure(str(path))
    except Exception as exc:  # noqa: BLE001 - gemmi raises RuntimeError on bad input
        raise StructureParseError(
            f"gemmi could not read '{path.name}': {exc}",
            detail={"format": fmt},
            remediation="Verify the file is a valid PDB/mmCIF file (try re-downloading it).",
        ) from exc

    structure = ParsedStructure(format=fmt, name=name, source=source)
    model_count = len(doc)
    if model_count == 0:
        raise StructureParseError(f"'{path.name}' contains no models.")
    if model_count > 1:
        structure.warn(
            "multiple_models",
            f"The file contains {model_count} models; only model 1 is loaded.",
            severity="warning",
            count=model_count,
        )
    model = doc[0]

    structure.metadata["spacegroup"] = str(getattr(doc, "spacegroup_hm", "") or "")
    cell = getattr(doc, "cell", None)
    if cell is not None:
        structure.metadata["cell"] = {
            "a": round(float(cell.a), 4),
            "b": round(float(cell.b), 4),
            "c": round(float(cell.c), 4),
            "alpha": round(float(cell.alpha), 3),
            "beta": round(float(cell.beta), 3),
            "gamma": round(float(cell.gamma), 3),
        }
    structure.metadata["experimental_method"] = _extract_experimental_method(doc)

    seen_altlocs: set[tuple[str, int, str, str]] = set()
    altloc_ids: set[str] = set()
    altloc_conflicts: dict[str, int] = {}
    missing_element = 0
    serial = 0

    for chain_index, chain in enumerate(model):
        chain_label = str(chain.name).strip() or "A"
        chain_residues: list[Residue] = []
        chain_atoms: list[Atom] = []
        for residue in chain:
            res_name = str(residue.name).strip()
            seqid = getattr(residue, "seqid", None)
            seq = int(getattr(seqid, "num", 0) or 0)
            icode = str(getattr(seqid, "icode", " ") or " ").strip()
            het_flag = str(getattr(residue, "het_flag", "A") or "A")
            water, amino, nucleic = _residue_kind_flags(res_name)
            info = residue_info(res_name)

            residue_index = len(structure.residues)
            parsed_residue = Residue(
                index=residue_index,
                name=res_name,
                seq=seq,
                chain_index=chain_index,
                atom_start=len(structure.atoms),
                atom_count=0,
                insertion_code=icode,
                is_water=water or het_flag == "W",
                is_hetero=het_flag in {"H", "W"} or not (amino or nucleic),
                is_amino_acid=amino,
                is_nucleic=nucleic,
                one_letter=str(info.get("one", "X")) if info else "X",
                chain_label=chain_label,
            )
            if het_flag == "W" and not parsed_residue.is_water:
                parsed_residue.is_water = True
                structure.warn(
                    "water_flag_without_name",
                    f"Residue flagged as water but named '{res_name}' (residue {seq}); treated as water.",
                    severity="info",
                )

            atom_start = len(structure.atoms)
            for atom in residue:
                atom_name = str(atom.name).strip()
                element_symbol = str(getattr(atom.element, "name", "") or "").strip()
                if not element_symbol or getattr(atom.element, "atomic_number", 0) == 0:
                    element_symbol = infer_element_from_name(atom_name, res_name)
                    missing_element += 1
                element_symbol = element_symbol[0].upper() + element_symbol[1:].lower()

                # gemmi represents "no altloc" as NUL, not as a space, so
                # normalise before deciding whether this is an alternate site.
                altloc = str(getattr(atom, "altloc", " ") or " ").replace("\x00", " ").strip()
                key = (chain_label, seq, icode, atom_name)
                if altloc:
                    altloc_ids.add(altloc)
                    if key in seen_altlocs:
                        # A site for this atom was already taken: keep the first
                        # one and record which alternate was skipped.
                        altloc_conflicts[altloc] = altloc_conflicts.get(altloc, 0) + 1
                        continue
                    seen_altlocs.add(key)

                serial += 1
                try:
                    position = atom.pos
                except Exception as exc:  # noqa: BLE001
                    raise StructureParseError(
                        f"Atom {atom_name} in residue {res_name} {seq} has no coordinates.",
                        detail={"chain": chain_label, "residue": res_name, "seq": seq},
                    ) from exc

                parsed_atom = Atom(
                    index=len(structure.atoms),
                    serial=int(getattr(atom, "serial", serial) or serial),
                    name=atom_name,
                    element=element_symbol,
                    x=round(float(position.x), 4),
                    y=round(float(position.y), 4),
                    z=round(float(position.z), 4),
                    residue_index=residue_index,
                    chain_index=chain_index,
                    occupancy=float(getattr(atom, "occ", 1.0) or 0.0),
                    bfactor=float(getattr(atom, "b_iso", 0.0) or 0.0),
                    formal_charge=int(getattr(atom, "charge", 0) or 0),
                    altloc=altloc,
                    record="HETATM" if parsed_residue.is_hetero else "ATOM",
                    is_hetero=parsed_residue.is_hetero,
                    is_water=parsed_residue.is_water,
                    is_backbone=_backbone_flag(atom_name),
                )
                structure.atoms.append(parsed_atom)
                chain_atoms.append(parsed_atom)
            parsed_residue.atom_start = atom_start
            parsed_residue.atom_count = len(structure.atoms) - atom_start
            structure.residues.append(parsed_residue)
            chain_residues.append(parsed_residue)

        if chain_residues:
            structure.chains.append(
                Chain(
                    index=chain_index,
                    id=chain_label,
                    residue_start=chain_residues[0].index,
                    residue_count=len(chain_residues),
                    kind=_chain_kind(chain_residues, chain_atoms),  # type: ignore[arg-type]
                )
            )

    if missing_element:
        structure.warn(
            "element_inferred",
            f"The element symbol was missing for {missing_element} atom(s) and was inferred "
            "from the atom name.",
            severity="warning",
            count=missing_element,
        )
    if altloc_ids:
        dropped = sum(altloc_conflicts.values())
        detail = f"; {dropped} alternate site(s) dropped" if dropped else ""
        structure.warn(
            "alternate_conformations",
            "Alternate conformations present ("
            + ", ".join(sorted(altloc_ids))
            + "). One conformer per atom site is kept so the structure renders without "
            "overlapping atoms"
            + detail
            + ".",
            severity="warning",
            count=dropped or 1,
            altlocs=sorted(altloc_ids),
            dropped=dropped,
        )

    # File-provided bonds (CONECT records) take priority over perception.
    structure.bonds = _gemmi_connections(doc, structure)

    ranges = _gemmi_ss_ranges(doc)
    if ranges["H"] or ranges["E"]:
        applied = apply_file_secondary_structure(structure.residues, ranges)
        if applied:
            structure.metadata["secondary_structure_source"] = "PDB HELIX/SHEET records"
    return structure


def _extract_experimental_method(doc: Any) -> str | None:
    for key in ("experimental_method", "remarks"):
        value = getattr(doc, key, None)
        if isinstance(value, str) and value:
            return value
    return None


def _gemmi_connections(doc: Any, structure: ParsedStructure) -> list[Bond]:
    """Translate CONECT/struct_conn records into bonds using our atom index."""
    try:
        connections = list(getattr(doc, "connections", []) or [])
    except Exception:  # noqa: BLE001
        return []
    if not connections:
        return []

    index: dict[tuple[str, int, str, str], int] = {}
    for atom in structure.atoms:
        residue = structure.residues[atom.residue_index]
        chain_label = structure.chains[atom.chain_index].id
        index[
            (
                chain_label,
                residue.seq,
                _norm_icode(residue.insertion_code),
                atom.name.strip().upper(),
            )
        ] = atom.index

    bonds: list[Bond] = []
    unresolved = 0
    seen: set[tuple[int, int]] = set()
    for connection in connections:
        parts1 = _endpoint_parts(getattr(connection, "partner1", None))
        parts2 = _endpoint_parts(getattr(connection, "partner2", None))
        name1 = str(getattr(getattr(connection, "partner1", None), "atom_name", "")).strip().upper()
        name2 = str(getattr(getattr(connection, "partner2", None), "atom_name", "")).strip().upper()
        if parts1 is None or parts2 is None or not name1 or not name2:
            unresolved += 1
            continue
        a = index.get((*parts1, name1))
        b = index.get((*parts2, name2))
        if a is None or b is None:
            unresolved += 1
            continue
        # CONECT/struct_conn records list a metal ion's coordination sphere, not
        # covalent bonds. 3PTB, for example, reports Ca–O contacts at 2.28–2.49 Å;
        # drawing those as bonds misrepresents the geometry (see bonds.py).
        if (
            element_by_symbol(structure.atoms[a].element).is_metal
            or element_by_symbol(structure.atoms[b].element).is_metal
        ):
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        # Disulfide and other covalent links are single bonds in the file.
        bonds.append(Bond(a=a, b=b, order=1, source="file"))

    if unresolved:
        structure.warn(
            "unresolved_connections",
            f"{unresolved} connection record(s) reference atoms that are not present in the "
            "loaded model (often alternate locations or symmetry-related partners).",
            severity="info",
            count=unresolved,
        )
    return bonds


# ---------------------------------------------------------------------------
# RDKit (SDF, MOL, MOL2, XYZ)
# ---------------------------------------------------------------------------
def parse_with_rdkit(path: Path, fmt: str, *, name: str, source: str) -> ParsedStructure:
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import rdDetermineBonds
    except ImportError as exc:  # pragma: no cover
        raise StructureParseError(
            "RDKit is required for SDF/MOL/MOL2/XYZ files.",
            remediation="Install backend dependencies: uv sync",
        ) from exc

    RDLogger.DisableLog("rdApp.*")  # we surface problems through warnings instead

    structures: list[ParsedStructure] = []
    if fmt in {"sdf", "mol"}:
        molecules, failures = _read_sdf_molecules(path, fmt)
        if not molecules:
            raise StructureParseError(
                f"RDKit could not parse '{path.name}' ({failures} record(s) failed).",
                detail={"failed_records": failures},
                remediation="Check the file, or convert it with Open Babel (`obabel -isdf in.sdf -osdf out.sdf`).",
            )
        if len(molecules) > MAX_SDF_MOLECULES:
            raise ValidationFailure(
                f"The file contains {len(molecules)} records; interactive import is limited to "
                f"{MAX_SDF_MOLECULES}. Compound libraries belong in the virtual-screening workflow.",
                remediation="Split the library or use the screening module (Phase 5).",
            )
        for mol in molecules:
            structures.append(_structure_from_rdkit_mol(mol, fmt=fmt, name=name, source=source))
    elif fmt == "mol2":
        mol = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=True)
        if mol is None:
            mol = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=False)
            if mol is None:
                raise StructureParseError(
                    f"RDKit could not parse the MOL2 file '{path.name}'.",
                    remediation="Convert the file with Open Babel: obabel -imol2 in.mol2 -osdf out.sdf",
                )
        structures.append(_structure_from_rdkit_mol(mol, fmt=fmt, name=name, source=source))
    elif fmt == "xyz":
        mol = Chem.MolFromXYZFile(str(path))
        if mol is None:
            raise StructureParseError(f"RDKit could not parse the XYZ file '{path.name}'.")
        try:
            rdDetermineBonds.DetermineBonds(mol, charge=0)
        except Exception:  # noqa: BLE001 - connectivity perception is best-effort
            mol = Chem.RWMol(mol).GetMol()
        structures.append(_structure_from_rdkit_mol(mol, fmt=fmt, name=name, source=source))
    else:  # pragma: no cover - guarded by the dispatcher
        raise UnsupportedFormatError(f"No RDKit parser for format '{fmt}'.")

    if len(structures) == 1:
        merged = structures[0]
    else:
        merged = _merge_ligand_structures(structures, fmt=fmt, name=name, source=source)
    return merged


def _read_sdf_molecules(path: Path, fmt: str) -> tuple[list[Any], int]:
    from rdkit import Chem

    if fmt == "mol":
        mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=True)
        return ([mol] if mol is not None else []), (0 if mol is not None else 1)

    supplier = Chem.SDMolSupplier(str(path), removeHs=False, sanitize=False)
    molecules: list[Any] = []
    failures = 0
    for mol in supplier:
        if mol is None:
            failures += 1
            continue
        try:
            Chem.SanitizeMol(mol)
        except Exception:  # noqa: BLE001 - keep the molecule, flag it later
            mol.SetProp("_moldock_sanitize_failed", "1")
        molecules.append(mol)
    return molecules, failures


def _structure_from_rdkit_mol(mol: Any, *, fmt: str, name: str, source: str) -> ParsedStructure:
    from rdkit import Chem

    if mol.GetNumConformers() == 0:
        raise StructureParseError(
            "The molecule has no 3D coordinates. Generate a conformer before importing it.",
            remediation="Use RDKit/Meeko to embed a 3D conformer, or import a 3D SDF/MOL2 file.",
        )

    structure = ParsedStructure(format=fmt, name=name, source=source)
    conformer = mol.GetConformer()
    title = mol.GetProp("_Name").strip() if mol.HasProp("_Name") else ""
    if not title:
        title = f"{name}"
    smiles = Chem.MolToSmiles(Chem.RemoveHs(mol)) if mol.GetNumAtoms() else None

    residue = Residue(
        index=0,
        name=(title[:20] if title else "LIG"),
        seq=1,
        chain_index=0,
        atom_start=0,
        atom_count=mol.GetNumAtoms(),
        is_hetero=True,
        is_amino_acid=False,
        one_letter="X",
        chain_label="L",
        title=title,
        smiles=smiles,
    )
    structure.residues.append(residue)

    for atom_index, rd_atom in enumerate(mol.GetAtoms()):
        position = conformer.GetAtomPosition(atom_index)
        symbol = rd_atom.GetSymbol()
        symbol = symbol[0].upper() + symbol[1:].lower()
        structure.atoms.append(
            Atom(
                index=atom_index,
                serial=atom_index + 1,
                name=rd_atom.GetProp("_TriposAtomName") if rd_atom.HasProp("_TriposAtomName") else f"{symbol}{atom_index + 1}",
                element=symbol,
                x=round(position.x, 4),
                y=round(position.y, 4),
                z=round(position.z, 4),
                residue_index=0,
                chain_index=0,
                formal_charge=rd_atom.GetFormalCharge(),
                record="HETATM",
                is_hetero=True,
            )
        )

    for bond in mol.GetBonds():
        structure.bonds.append(
            Bond(
                a=bond.GetBeginAtomIdx(),
                b=bond.GetEndAtomIdx(),
                order=int(round(bond.GetBondTypeAsDouble())) or 1,
                # SDF/MOL/MOL2 have a real bond block; XYZ connectivity comes from
                # RDKit's distance/valence perception, so it is labelled as such.
                source="file" if fmt in {"sdf", "mol", "mol2"} else "geometry",
                aromatic=bond.GetIsAromatic(),
            )
        )

    structure.metadata["connectivity_source"] = (
        "file" if fmt in {"sdf", "mol", "mol2"} else "perceived"
    )

    if mol.HasProp("_moldock_sanitize_failed"):
        structure.warn(
            "sanitization_failed",
            "RDKit could not fully sanitise this molecule (valence/aromaticity problems). "
            "It is shown as read; preparation will reject it until it is fixed.",
            severity="warning",
        )
    return structure


def _merge_ligand_structures(
    structures: list[ParsedStructure], *, fmt: str, name: str, source: str
) -> ParsedStructure:
    """Combine a multi-record SDF into one structure with one residue per molecule."""
    merged = ParsedStructure(format=fmt, name=name, source=source)
    for molecule_index, part in enumerate(structures):
        residue = part.residues[0]
        offset = len(merged.atoms)
        residue.index = len(merged.residues)
        residue.chain_index = 0
        residue.seq = molecule_index + 1
        residue.atom_start = offset
        merged.residues.append(residue)
        for atom in part.atoms:
            atom.index = len(merged.atoms)
            atom.residue_index = residue.index
            atom.chain_index = 0
            merged.atoms.append(atom)
        for bond in part.bonds:
            bond.a += offset
            bond.b += offset
            merged.bonds.append(bond)

    merged.chains.append(
        Chain(index=0, id="L", residue_start=0, residue_count=len(merged.residues), kind="ligand")
    )
    merged.metadata["connectivity_source"] = "file" if fmt in {"sdf", "mol", "mol2"} else "perceived"
    merged.warn(
        "multi_record_file",
        f"{len(structures)} molecules were loaded from the file; each is listed as a separate "
        "object in the structure tree.",
        severity="info",
        count=len(structures),
    )
    return merged


# ---------------------------------------------------------------------------
# PDBQT
# ---------------------------------------------------------------------------
PDBQT_ATOM_RE = re.compile(r"^(ATOM|HETATM)")


def parse_pdbqt(path: Path, *, name: str, source: str) -> ParsedStructure:
    """Read the atom block of a PDBQT file.

    PDBQT carries partial charges and AutoDock atom types. The torsion tree
    (ROOT/BRANCH/TORSDOF) is recorded as metadata but not applied: Phase 1 shows
    the coordinates as written.
    """
    structure = ParsedStructure(format="pdbqt", name=name, source=source)
    residue_lookup: dict[tuple[int, str], int] = {}
    ignored_records: dict[str, int] = {}
    serial = 0
    models = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            record = line[:6].strip().upper()
            if record in {"MODEL"}:
                models += 1
                if models > 1:
                    structure.warn(
                        "multiple_models",
                        "The PDBQT file contains multiple models; only the first is loaded.",
                        severity="warning",
                    )
                    break
                continue
            if not PDBQT_ATOM_RE.match(line):
                if record and record not in {
                    "ROOT",
                    "ENDROOT",
                    "BRANCH",
                    "ENDBRANCH",
                    "TORSDOF",
                    "REMARK",
                    "ENDMDL",
                    "END",
                    "COMPND",
                    "TER",
                    "CRYST1",
                }:
                    ignored_records[record] = ignored_records.get(record, 0) + 1
                continue

            fields = line.split()
            if len(fields) < 9:
                structure.warn(
                    "malformed_pdbqt_line",
                    "A PDBQT atom line could not be parsed and was skipped.",
                    severity="error",
                )
                continue
            try:
                atom_name = fields[2]
                res_name = fields[3]
                chain_label = fields[4] if fields[4].isalnum() and len(fields[4]) == 1 else "A"
                seq = int(re.sub(r"\D", "", fields[5]) or 1)
                x, y, z = (round(float(value), 4) for value in fields[6:9])
                occupancy = float(fields[9]) if len(fields) > 9 else 1.0
                bfactor = float(fields[10]) if len(fields) > 10 else 0.0
                partial_charge = float(fields[11]) if len(fields) > 11 else None
                autodock_type = fields[12] if len(fields) > 12 else None
            except ValueError:
                structure.warn(
                    "malformed_pdbqt_line",
                    "A PDBQT atom line contained non-numeric coordinates and was skipped.",
                    severity="error",
                )
                continue

            element = _element_from_autodock_type(autodock_type) or infer_element_from_name(
                atom_name, res_name
            )
            water, amino, nucleic = _residue_kind_flags(res_name)

            key = (seq, chain_label)
            chain_index = 0
            if key not in residue_lookup:
                chain_index = next(
                    (chain.index for chain in structure.chains if chain.id == chain_label), 0
                )
                if not structure.chains or structure.chains[-1].id != chain_label:
                    structure.chains.append(
                        Chain(
                            index=len(structure.chains),
                            id=chain_label,
                            residue_start=len(structure.residues),
                            residue_count=0,
                            kind="ligand" if not amino else "polymer",
                        )
                    )
                    chain_index = structure.chains[-1].index
                info = residue_info(res_name)
                residue = Residue(
                    index=len(structure.residues),
                    name=res_name.strip() or "LIG",
                    seq=seq,
                    chain_index=chain_index,
                    atom_start=len(structure.atoms),
                    atom_count=0,
                    is_water=water,
                    is_hetero=not amino,
                    is_amino_acid=amino,
                    is_nucleic=nucleic,
                    one_letter=str(info.get("one", "X")) if info else "X",
                    chain_label=chain_label,
                )
                structure.residues.append(residue)
                structure.chains[chain_index].residue_count += 1
                residue_lookup[key] = residue.index

            serial += 1
            residue_index = residue_lookup[key]
            structure.atoms.append(
                Atom(
                    index=len(structure.atoms),
                    serial=serial,
                    name=atom_name,
                    element=element,
                    x=x,
                    y=y,
                    z=z,
                    residue_index=residue_index,
                    chain_index=chain_index,
                    occupancy=occupancy,
                    bfactor=bfactor,
                    partial_charge=partial_charge,
                    autodock_type=autodock_type,
                    record="HETATM" if not amino else "ATOM",
                    is_hetero=not amino,
                    is_water=water,
                    is_backbone=_backbone_flag(atom_name),
                )
            )
            structure.residues[residue_index].atom_count += 1

    if not structure.atoms:
        raise StructureParseError(
            f"No ATOM/HETATM records were found in '{path.name}'.",
            remediation="Confirm the file is an AutoDock PDBQT file.",
        )

    if ignored_records:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(ignored_records.items()))
        structure.warn(
            "pdbqt_records_ignored",
            f"Unrecognised PDBQT records were ignored: {summary}.",
            severity="info",
        )
    structure.metadata["torsion_tree_applied"] = False
    structure.warn(
        "pdbqt_torsion_tree",
        "PDBQT torsion information (ROOT/BRANCH) is not applied; atoms are shown at their "
        "file coordinates. Docking input generation arrives in Phase 3.",
        severity="info",
    )
    return structure


AUTODOCK_ELEMENTS = {
    "A": "C",  # aromatic carbon
    "C": "C",
    "N": "N",
    "NA": "N",  # H-bond acceptor nitrogen
    "NS": "N",
    "OA": "O",
    "OS": "O",
    "O": "O",
    "S": "S",
    "SA": "S",
    "H": "H",
    "HD": "H",
    "HS": "H",
    "F": "F",
    "Cl": "Cl",
    "Br": "Br",
    "I": "I",
    "P": "P",
    "Mg": "Mg",
    "Mn": "Mn",
    "Zn": "Zn",
    "Ca": "Ca",
    "Fe": "Fe",
    "ClA": "Cl",
}


def _element_from_autodock_type(autodock_type: str | None) -> str | None:
    if not autodock_type:
        return None
    if autodock_type in AUTODOCK_ELEMENTS:
        return AUTODOCK_ELEMENTS[autodock_type]
    stripped = autodock_type.rstrip("0123456789")
    if stripped in AUTODOCK_ELEMENTS:
        return AUTODOCK_ELEMENTS[stripped]
    return None


# ---------------------------------------------------------------------------
# FASTA
# ---------------------------------------------------------------------------
def parse_fasta(path: Path, *, name: str, source: str) -> ParsedStructure:
    """Sequence-only import: useful metadata, no 3D coordinates."""
    try:
        from Bio import SeqIO
    except ImportError as exc:  # pragma: no cover
        raise StructureParseError("Biopython is required for FASTA files.") from exc

    structure = ParsedStructure(format="fasta", name=name, source=source)
    sequences: list[dict[str, Any]] = []
    try:
        for record in SeqIO.parse(str(path), "fasta"):
            sequences.append(
                {
                    "id": record.id,
                    "description": record.description,
                    "length": len(record.seq),
                    "sequence": str(record.seq),
                }
            )
    except Exception as exc:  # noqa: BLE001
        raise StructureParseError(f"Could not read the FASTA file '{path.name}': {exc}") from exc

    if not sequences:
        raise StructureParseError(f"'{path.name}' contains no FASTA records.")

    structure.metadata["sequences"] = sequences
    structure.warn(
        "sequence_only",
        "FASTA contains sequence information only: there are no 3D coordinates to visualise. "
        "Use it as a reference for sequence checks, or fetch the structure from the RCSB PDB.",
        severity="warning",
    )
    return structure


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
def parse_structure_file(
    path: Path,
    fmt: str,
    *,
    name: str | None = None,
    source: str = "uploaded",
    enforce_atom_limit: bool = True,
) -> ParsedStructure:
    """Parse a structure file into the format-neutral model."""
    if not path.exists():
        raise StructureParseError(f"Structure file not found: {path}")

    display_name = name or path.stem
    if fmt in {"pdb", "mmcif"}:
        structure = parse_with_gemmi(path, fmt, name=display_name, source=source)
    elif fmt in {"sdf", "mol", "mol2", "xyz"}:
        structure = parse_with_rdkit(path, fmt, name=display_name, source=source)
    elif fmt == "pdbqt":
        structure = parse_pdbqt(path, name=display_name, source=source)
    elif fmt == "fasta":
        structure = parse_fasta(path, name=display_name, source=source)
    else:
        raise UnsupportedFormatError(
            f"No parser is available for format '{fmt}'.",
            detail={"format": fmt},
        )

    # An empty file, binary garbage, and a truncated download all parse to an
    # empty structure. That is not a structure: fail loudly instead of opening an
    # empty viewer. FASTA is the one format that legitimately has no coordinates
    # — it reports sequences instead, which is checked for here as well.
    if (
        structure.atom_count == 0
        and not structure.residues
        and not structure.sequences
        and not structure.metadata.get("sequences")
    ):
        raise StructureParseError(
            f"No atoms or residues could be read from '{path.name}'.",
            detail={"format": fmt, "bytes": path.stat().st_size},
            remediation=(
                "The file is empty, truncated, or not in the declared format. "
                "Re-export it and try again."
            ),
        )

    settings = get_settings()
    if enforce_atom_limit and structure.atom_count > settings.max_atoms:
        raise ValidationFailure(
            f"The structure has {structure.atom_count} atoms, above the configured limit of "
            f"{settings.max_atoms}.",
            detail={"atoms": structure.atom_count, "limit": settings.max_atoms},
            remediation="Raise MOLDOCK_MAX_ATOMS in .env if this structure is intentional.",
        )

    # SDF/MOL/MOL2 carry a complete bond block: trust it instead of inventing
    # additional bonds by distance.
    perceive = structure.metadata.get("connectivity_source") != "file"
    return finalize(structure, perceive_bonds=perceive)


def ligand_summary(structure: ParsedStructure) -> dict[str, Any]:
    """Small summary used for the ligand cards in the UI."""
    residues = [residue for residue in structure.residues if residue.title or residue.is_hetero]
    return {
        "molecules": len(residues) or len(structure.residues),
        "heavy_atoms": structure.heavy_atom_count,
        "elements": structure.element_counts,
        "mw_estimate": round(
            sum(
                element_by_symbol(atom.element).atomic_mass
                for atom in structure.atoms
                if atom.element != "H"
            ),
            3,
        ),
        "formula_estimate": _formula(structure),
    }


def _formula(structure: ParsedStructure) -> str:
    counts: dict[str, int] = {}
    for atom in structure.atoms:
        counts[atom.element] = counts.get(atom.element, 0) + 1
    # Hill order: C first, H second, then alphabetical.
    ordered: list[str] = []
    if "C" in counts:
        ordered.append("C")
        if "H" in counts:
            ordered.append("H")
    ordered += sorted(key for key in counts if key not in {"C", "H"})
    return "".join(f"{key}{counts[key] if counts[key] > 1 else ''}" for key in ordered)


def distance(a: Atom, b: Atom) -> float:
    """Cartesian distance in Ångström."""
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


__all__ = [
    "AMINO_ACIDS",
    "ParsedStructure",
    "distance",
    "finalize",
    "infer_element_from_name",
    "ligand_summary",
    "parse_fasta",
    "parse_pdbqt",
    "parse_structure_file",
    "parse_with_gemmi",
    "parse_with_rdkit",
]
