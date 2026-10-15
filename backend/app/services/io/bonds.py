"""Bond perception.

Protein formats (PDB, mmCIF) do not carry bond tables, so connectivity is
perceived from interatomic distances using covalent radii. The algorithm is
deliberately conservative and enforces chemically sensible maximum valences,
because a wrong bond becomes a wrong figure and — later — a wrong preparation
input.

Rules
-----
* Two atoms are bonded when ``d <= (r_cov(i) + r_cov(j)) * tolerance``.
* Hydrogens are capped at one bond, carbon at four, nitrogen at four, oxygen at
  two, sulfur at six, phosphorus at five.
* Bonds involving metal ions are not perceived: metals coordinate rather than
  form directional covalent bonds, and drawing them as bonds misrepresents the
  geometry. (Coordination analysis arrives with interaction analysis in Phase 4.)
* Waters are not bonded to each other; the geometry of a crystallographic water
  network is not a covalent bond network.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np
from scipy.spatial import cKDTree

from app.services.chemistry.elements import element_by_symbol
from app.services.io.types import Atom, Bond, Residue

DEFAULT_TOLERANCE = 1.25
MAX_VALENCE: dict[str, int] = {
    "H": 1,
    "D": 1,
    "B": 4,
    "C": 4,
    "N": 4,
    "O": 2,
    "F": 1,
    "P": 5,
    "S": 6,
    "Cl": 1,
    "Br": 1,
    "I": 1,
    "Se": 2,
}


def _max_valence(symbol: str) -> int:
    info = element_by_symbol(symbol)
    if info.is_metal:
        return 0  # never perceived
    return MAX_VALENCE.get(symbol, 6)


def _coords(atoms: Sequence[Atom]) -> np.ndarray:
    return np.asarray([(atom.x, atom.y, atom.z) for atom in atoms], dtype=np.float64)


# Backbone geometry constants (Å). A peptide bond C–N is ~1.33 Å; a disulfide
# S–S is ~2.05 Å; a phosphodiester O3'–P is ~1.6 Å.
_PEPTIDE_BOND = frozenset({"C", "N"})
_DISULFIDE_RESIDUES = frozenset({"CYS", "CYX", "CSO", "CSS", "CME"})
_NUCLEIC_LINK = frozenset({"P", "O3'", "O3*", "O3P"})


def _residue_lookup(
    atoms: Sequence[Atom], residues: Sequence[Residue]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-atom arrays: residue name, is-polymer, is-water."""
    name = np.empty(len(atoms), dtype=object)
    polymer = np.zeros(len(atoms), dtype=bool)
    water = np.zeros(len(atoms), dtype=bool)
    for position, atom in enumerate(atoms):
        residue = residues[atom.residue_index] if 0 <= atom.residue_index < len(residues) else None
        if residue is None:
            name[position] = ""
            continue
        name[position] = residue.name
        polymer[position] = bool(residue.is_amino_acid or residue.is_nucleic)
        water[position] = bool(residue.is_water)
    return name, polymer, water


def _inter_residue_allowed(
    ai: int,
    aj: int,
    atoms: Sequence[Atom],
    res_name: np.ndarray,
    is_polymer: np.ndarray,
    is_nucleic: np.ndarray,
) -> bool:
    """Decide whether a covalent bond between two different residues is real.

    Distance alone is not enough in a polymer: atoms from neighbouring residues
    are routinely within bonding distance without being bonded (CA(i)...CA(i+1)
    is 3.8 A; C(i)...N(i+1) is the peptide bond at 1.33 A). Only recognised
    inter-residue links are accepted.
    """
    a = atoms[ai]
    b = atoms[aj]
    distance = math.dist(a.coords, b.coords)

    both_cys = (
        a.element == "S"
        and b.element == "S"
        and str(res_name[ai]) in _DISULFIDE_RESIDUES
        and str(res_name[aj]) in _DISULFIDE_RESIDUES
    )
    # A disulfide bridge is real regardless of chain or sequence distance (3PTB
    # links CYS22 to CYS157). Requiring true ~2.05 A geometry keeps an ordinary
    # sulfur-sulfur contact from being drawn as a bond.
    if both_cys:
        return distance <= 2.5

    names = {a.name, b.name}
    if is_polymer[ai] and is_polymer[aj]:
        if a.chain_index != b.chain_index:
            return False
        if abs(a.residue_index - b.residue_index) != 1:
            return False
        if bool(is_nucleic[ai]) != bool(is_nucleic[aj]):
            return False
        if is_nucleic[ai]:
            return bool(names & _NUCLEIC_LINK)
        return names == _PEPTIDE_BOND

    if is_polymer[ai] or is_polymer[aj]:
        # Polymer to non-polymer: a covalent modification (an inhibitor bound to
        # a catalytic cysteine, a glycosylation, a heme linkage). Real, but the
        # tolerance is tighter so a van der Waals contact is never drawn as a
        # bond, and it is not limited to sequence-adjacent residues.
        return distance <= (a.covalent_radius + b.covalent_radius) * 1.2 + 0.1

    # Neither side is a polymer: two hetero residues of one object (a glycan, a
    # multi-residue cofactor) or a covalent ligand-ligand link. The distance and
    # valence rules already applied are sufficient.
    return True


def infer_bonds(
    atoms: Sequence[Atom],
    *,
    residues: Sequence[Residue] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    extra_cutoff: float = 0.0,
) -> list[Bond]:
    """Perceive bonds from geometry. Returns bonds with 0-based atom indices.

    When ``residues`` is supplied the perception is polymer-aware: intra-residue
    bonds are accepted from distance, while inter-residue bonds are restricted to
    peptide bonds, disulfides, phosphodiester links and genuine covalent
    modifications. Without it (e.g. an XYZ trajectory) only the distance and
    valence rules apply.

    ``tolerance`` alone (a 25 % slack on the sum of covalent radii) already
    covers every real covalent bond: C-C 1.54 vs 1.90, C-S 1.81 vs 2.26, S-S
    2.05 vs 2.63, P-O 1.60 vs 2.16. ``extra_cutoff`` is an optional *additional*
    absolute slack for deliberately generous perception (low-resolution or
    neutron structures) and defaults to zero, because adding even 0.3 A to a
    carbon-carbon pair accepts 2.2 A non-bonds as bonds.
    """
    if len(atoms) < 2:
        return []

    coords = _coords(atoms)
    radii = np.asarray([max(atom.covalent_radius, 0.25) for atom in atoms])
    max_valence = np.asarray([_max_valence(atom.element) for atom in atoms])
    is_metal = np.asarray([element_by_symbol(atom.element).is_metal for atom in atoms])
    is_water = np.asarray([bool(atom.is_water) for atom in atoms])

    res_name: np.ndarray | None = None
    is_polymer: np.ndarray | None = None
    is_nucleic: np.ndarray | None = None
    if residues:
        res_name, is_polymer, _ = _residue_lookup(atoms, residues)
        is_nucleic = np.asarray(
            [
                bool(residues[atom.residue_index].is_nucleic)
                if 0 <= atom.residue_index < len(residues)
                else False
                for atom in atoms
            ]
        )
    # Candidate pairs: any two atoms whose centres are within the largest
    # possible bonding distance. Querying once keeps this O(N log N).
    max_pair = float(np.max(radii) * 2 * tolerance + extra_cutoff)
    tree = cKDTree(coords)
    pairs = tree.query_pairs(r=max_pair, output_type="ndarray")
    if pairs.size == 0:
        return []

    i_idx = pairs[:, 0]
    j_idx = pairs[:, 1]
    distances = np.linalg.norm(coords[i_idx] - coords[j_idx], axis=1)
    cutoffs = (radii[i_idx] + radii[j_idx]) * tolerance + extra_cutoff

    keep = distances <= cutoffs
    keep &= ~is_metal[i_idx]
    keep &= ~is_metal[j_idx]
    keep &= ~is_water[i_idx]
    keep &= ~is_water[j_idx]
    # Two hydrogens never bond.
    keep &= ~((max_valence[i_idx] == 1) & (max_valence[j_idx] == 1))

    if residues and res_name is not None and is_polymer is not None:
        chain_of = np.asarray([atom.chain_index for atom in atoms])
        res_of = np.asarray([atom.residue_index for atom in atoms])
        intra = (chain_of[i_idx] == chain_of[j_idx]) & (res_of[i_idx] == res_of[j_idx])
        if not np.all(intra):
            for k in np.nonzero(~intra)[0]:
                if not _inter_residue_allowed(
                    int(i_idx[k]), int(j_idx[k]), atoms, res_name, is_polymer, is_nucleic
                ):
                    keep[k] = False

    if not np.any(keep):
        return []

    i_idx = i_idx[keep]
    j_idx = j_idx[keep]
    distances = distances[keep]

    # Sort by distance so that when an atom exceeds its maximum valence we keep
    # its shortest (i.e. most chemically plausible) contacts.
    order = np.argsort(distances, kind="stable")
    i_idx = i_idx[order]
    j_idx = j_idx[order]

    degrees = np.zeros(len(atoms), dtype=np.int64)
    bonds: list[Bond] = []
    for i, j in zip(i_idx.tolist(), j_idx.tolist(), strict=True):
        if degrees[i] >= max_valence[i] or degrees[j] >= max_valence[j]:
            continue
        degrees[i] += 1
        degrees[j] += 1
        aromatic = bool(
            res_name is not None
            and str(res_name[i]) not in {"", "HOH", "WAT"}
            and _looks_aromatic(atoms[i].name, atoms[j].name)
        )
        bonds.append(Bond(a=i, b=j, order=1, source="geometry", aromatic=aromatic))
    return bonds


def _looks_aromatic(name_a: str, name_b: str) -> bool:
    """Rough aromaticity hint for aromatic ring atom names (PHE/TYR/TRP/HIS)."""
    ring = {"CG", "CD1", "CD2", "CE1", "CE2", "CZ", "CH2", "NE1", "ND1", "CE3", "CZ2", "CZ3"}
    return name_a in ring and name_b in ring


def merge_bonds(primary: Iterable[Bond], secondary: Iterable[Bond]) -> list[Bond]:
    """Union two bond lists, keeping the primary entry on duplicates."""
    merged: dict[tuple[int, int], Bond] = {}
    for bond in primary:
        merged[(min(bond.a, bond.b), max(bond.a, bond.b))] = bond
    for bond in secondary:
        key = (min(bond.a, bond.b), max(bond.a, bond.b))
        if key not in merged:
            merged[key] = bond
    return list(merged.values())


def validate_bond_lengths(
    atoms: Sequence[Atom], bonds: Sequence[Bond], *, tolerance: float = 1.4
) -> list[dict[str, object]]:
    """Return bonds whose length is implausible for their element pair.

    Used by the scientific sanity tests and by the import report: a 0.6 Å
    "bond" between two carbons means the parser mistook something.
    """
    problems: list[dict[str, object]] = []
    for bond in bonds:
        atom_a = atoms[bond.a]
        atom_b = atoms[bond.b]
        distance = float(
            np.linalg.norm(
                np.array(atom_a.coords) - np.array(atom_b.coords)
            )
        )
        expected = atom_a.covalent_radius + atom_b.covalent_radius
        if distance > expected * tolerance or distance < 0.4:
            problems.append(
                {
                    "a": bond.a,
                    "b": bond.b,
                    "distance": round(distance, 3),
                    "expected": round(expected, 3),
                    "elements": [atom_a.element, atom_b.element],
                }
            )
    return problems
