"""MolDock Studio: symmetry-aware RMSD for docking poses.

Docking poses can differ by symmetry-equivalent atom orderings (e.g. a
phenyl ring flipped 180°, or a carboxylate swapped). Plain atom-by-atom RMSD
would penalise these as large deviations even though they represent the same
physical pose. This module provides:

* :func:`symmetry_aware_rmsd` — best RMSD over symmetry-equivalent atom
  permutations using RDKit's canonical ranking and best-fit alignment.
* :func:`pose_rmsd_bounds` — lower/upper RMSD bounds between two poses, as
  stored on :class:`DockingPose`.

All coordinates are in Angstrom; RMSD is in Angstrom.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from rdkit import Chem


def _canonical_ranks(mol: Chem.Mol) -> list[int]:
    """Canonical atom ranks (symmetry classes) for a molecule.

    Atoms in the same symmetry class (e.g. the two oxygens of a carboxylate,
    or the two ortho carbons of a monosubstituted benzene) receive the same
    rank, so RMSD can be minimised over permutations within each class.
    """
    return [int(r) for r in Chem.CanonicalRankAtoms(mol, breakTies=False)]


def _group_by_rank(ranks: list[int]) -> dict[int, list[int]]:
    groups: dict[int, list[int]] = {}
    for idx, rank in enumerate(ranks):
        groups.setdefault(rank, []).append(idx)
    return groups


def _build_permutations(groups: dict[int, list[int]]) -> list[list[int]]:
    """Build all symmetry-equivalent atom permutations.

    For each symmetry class of size n, there are n! permutations. The total
    is the product of factorials, small for typical ligands.
    Returns a list of full permutations, each a list mapping original index
    -> permuted index.
    """
    classes = list(groups.values())
    per_class_perms = [list(itertools.permutations(idxs)) for idxs in classes]
    full: list[list[int]] = []
    for choice in itertools.product(*per_class_perms):
        mapping: dict[int, int] = {}
        for class_indices, chosen in zip(classes, choice, strict=False):
            for orig_idx, perm_idx in zip(class_indices, chosen, strict=False):
                mapping[orig_idx] = perm_idx
        full.append([mapping[i] for i in range(len(mapping))])
    return full


def _kabsch_rmsd(P: np.ndarray, Q: np.ndarray) -> float:
    """RMSD between two (N,3) arrays after optimal rigid alignment (Kabsch)."""
    if P.shape != Q.shape or P.shape[0] == 0:
        return float("inf")
    Pc = P - P.mean(axis=0)
    Qc = Q - Q.mean(axis=0)
    H = Pc.T @ Qc
    try:
        U, _, Vt = np.linalg.svd(H)
    except np.linalg.LinAlgError:
        return float("inf")
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    aligned = Pc @ R
    diff = aligned - Qc
    return float(math.sqrt(np.mean(np.sum(diff * diff, axis=1))))


def symmetry_aware_rmsd(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
    *,
    atom_map: dict[int, int] | None = None,
) -> float:
    """Best RMSD between two molecules over symmetry-equivalent atom orderings.

    Parameters
    ----------
    mol_a, mol_b:
        Two RDKit molecules with conformers. Same number of heavy atoms and
        same connectivity (same molecule, different pose).
    atom_map:
        Optional explicit mapping from atom index in ``mol_a`` to atom index
        in ``mol_b``. If omitted, atoms are matched by canonical rank and
        element.

    Returns
    -------
    float
        Minimum RMSD (Angstrom) over symmetry-equivalent permutations, or
        ``float("inf")`` if alignment is impossible.
    """
    if mol_a.GetNumAtoms() != mol_b.GetNumAtoms():
        return float("inf")
    n = mol_a.GetNumAtoms()

    if atom_map is None:
        ranks_a = _canonical_ranks(mol_a)
        ranks_b = _canonical_ranks(mol_b)
        groups_a = _group_by_rank(ranks_a)
        groups_b = _group_by_rank(ranks_b)
        common_ranks = set(groups_a) & set(groups_b)
        mapping: dict[int, int] = {}
        for rank in sorted(common_ranks):
            idx_a = sorted(groups_a[rank])
            idx_b = sorted(groups_b[rank])
            if len(idx_a) != len(idx_b):
                return float("inf")
            for a_idx, b_idx in zip(idx_a, idx_b, strict=False):
                mapping[a_idx] = b_idx
        if len(mapping) != n:
            return float("inf")
    else:
        mapping = atom_map
        if len(mapping) != n:
            return float("inf")

    conf_a = mol_a.GetConformer()
    conf_b = mol_b.GetConformer()

    coords_a = np.array(
        [
            [conf_a.GetAtomPosition(i).x, conf_a.GetAtomPosition(i).y, conf_a.GetAtomPosition(i).z]
            for i in range(n)
        ],
        dtype=np.float64,
    )
    coords_b = np.array(
        [
            [conf_b.GetAtomPosition(mapping[i]).x, conf_b.GetAtomPosition(mapping[i]).y, conf_b.GetAtomPosition(mapping[i]).z]
            for i in range(n)
        ],
        dtype=np.float64,
    )

    best = _kabsch_rmsd(coords_a, coords_b)

    groups = _group_by_rank(_canonical_ranks(mol_a))
    if any(len(idxs) > 1 for idxs in groups.values()):
        for perm in _build_permutations(groups):
            coords_b_perm = coords_b[np.array(perm)]
            rmsd = _kabsch_rmsd(coords_a, coords_b_perm)
            if rmsd < best:
                best = rmsd
    return best


def pose_rmsd_bounds(
    score_kcal_mol: float,
    rmsd_lower: float | None,
    rmsd_upper: float | None,
) -> dict[str, float | None]:
    """Package Vina pose RMSD bounds into a serialisable dict."""
    return {
        "scoreKcalMol": score_kcal_mol,
        "rmsdLowerBound": rmsd_lower,
        "rmsdUpperBound": rmsd_upper,
    }


def symmetry_aware_pose_rmsd(
    pose_mol: Chem.Mol,
    reference_mol: Chem.Mol,
) -> float:
    """Convenience: symmetry-aware RMSD between a docked pose and a reference."""
    return symmetry_aware_rmsd(reference_mol, pose_mol)
