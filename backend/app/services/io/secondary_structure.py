"""Secondary-structure assignment.

Two sources, in priority order:

1. ``HELIX``/``SHEET`` records when the file provides them (crystallographers'
   own assignment).
2. A geometric CA-based heuristic (the classic CA(i)-CA(i+3)/CA(i+4) distance
   test for helices and CA-pair patterns for beta strands).

The heuristic is *not* DSSP: it does not measure hydrogen bonds, so it is
documented in the UI as a geometric estimate. It is deterministic, dependency
free and adequate for cartoon rendering.
"""

from __future__ import annotations

import math

from app.services.io.types import Residue, StructureWarning

HELIX_ALPHA = (4.6, 5.6, 5.7, 6.9)  # d(i,i+3) range, d(i,i+4) range
HELIX_310 = (5.6, 6.5, 6.9, 7.9)
SHEET_PAIR_MAX = 5.5


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.dist(a, b)


def _ca_trace(residues: list[Residue], coords: list[tuple[float, float, float]]) -> list[int]:
    """Indices of residues that contribute a CA to the trace."""
    return [idx for idx, res in enumerate(residues) if res.ca_index is not None and not res.is_water]


def assign_geometric_secondary_structure(
    residues: list[Residue], coords: list[tuple[float, float, float]], *, min_run: int = 2
) -> int:
    """Assign helix/sheet/coil from CA geometry. Returns residues assigned.

    ``coords`` maps residue index -> CA coordinate.
    """
    if len(residues) < 4:
        return 0

    trace = _ca_trace(residues, coords)
    if len(trace) < 4:
        return 0

    assigned = 0

    # --- helices -----------------------------------------------------------
    for params in (HELIX_ALPHA, HELIX_310):
        d3_min, d3_max, d4_min, d4_max = params
        span = 4 if params is HELIX_ALPHA else 3
        flags: list[int] = []
        for pos in range(len(trace) - 4):
            i = trace[pos]
            i3 = trace[pos + 3]
            i4 = trace[pos + 4]
            # Only consider consecutive residues in the same chain.
            if residues[i].chain_index != residues[i4].chain_index:
                continue
            d3 = _distance(coords[i], coords[i3])
            d4 = _distance(coords[i], coords[i4])
            if d3_min <= d3 <= d3_max and d4_min <= d4 <= d4_max:
                flags.append(pos)

        # Require a consecutive run of flags so that single turns in loops do
        # not become helices (same spirit as DSSP's minimum helix length).
        run: list[int] = []
        runs: list[list[int]] = []
        for pos in flags:
            if run and pos == run[-1] + 1:
                run.append(pos)
            else:
                if run:
                    runs.append(run)
                run = [pos]
        if run:
            runs.append(run)

        for positions in runs:
            if len(positions) < min_run:
                continue
            for pos in positions:
                # A helix start at i covers residues i..i+3 (alpha) / i..i+2 (3-10).
                for step in range(span):
                    if pos + step < len(trace):
                        residue = residues[trace[pos + step]]
                        if residue.ss == "C":
                            residue.ss = "H"
                            assigned += 1

    # --- beta strands ------------------------------------------------------
    candidates: dict[int, int] = {}
    positions = list(range(len(trace)))
    for p in positions:
        i = trace[p]
        if residues[i].ss != "C":
            continue
        for q in positions:
            if p == q:
                continue
            j = trace[q]
            if residues[j].ss != "C":
                continue
            if residues[i].chain_index != residues[j].chain_index:
                continue
            if abs(i - j) < 3:
                continue
            d_ij = _distance(coords[i], coords[j])
            if d_ij > SHEET_PAIR_MAX:
                continue
            # Neighbouring CA traces must also be close for a strand register.
            neighbours_i = [x for x in (p - 1, p + 1) if 0 <= x < len(trace)]
            neighbours_j = [x for x in (q - 1, q + 1) if 0 <= x < len(trace)]
            contacts = 0
            for ni in neighbours_i:
                for nj in neighbours_j:
                    if residues[trace[ni]].chain_index != residues[i].chain_index:
                        continue
                    if _distance(coords[trace[ni]], coords[trace[nj]]) <= SHEET_PAIR_MAX:
                        contacts += 1
            if contacts >= 1:
                candidates[i] = candidates.get(i, 0) + 1
                candidates[j] = candidates.get(j, 0) + 1

    flagged = set(candidates)
    for i in sorted(flagged):
        if residues[i].ss != "C":
            continue
        bridged = (i - 1 in flagged and residues[i - 1].chain_index == residues[i].chain_index) or (
            i + 1 in flagged and residues[i + 1].chain_index == residues[i].chain_index
        )
        if bridged or candidates[i] >= 2:
            residues[i].ss = "E"
            assigned += 1

    return assigned


SsrRange = tuple[str, int, str, str, int, str]


def apply_file_secondary_structure(residues: list[Residue], ranges: dict[str, list[SsrRange]]) -> int:
    """Apply HELIX/SHEET ranges parsed from the coordinate file.

    ``ranges`` maps ``"H"``/``"E"`` to tuples of
    ``(chain_start, seq_start, icode_start, chain_end, seq_end, icode_end)``.
    Returns the number of residues relabelled.
    """
    by_key: dict[tuple[str, int, str], list[Residue]] = {}
    for residue in residues:
        by_key.setdefault(
            (residue.chain_label, residue.seq, residue.insertion_code.strip()), []
        ).append(residue)

    relabelled = 0
    for ss_type, entries in ranges.items():
        for chain_a, seq_a, icode_a, _chain_b, seq_b, icode_b in entries:
            icode_start = icode_a.strip()
            icode_end = icode_b.strip()
            # SHEET strands may be written in either direction.
            if (seq_a, icode_start) > (seq_b, icode_end):
                seq_a, seq_b = seq_b, seq_a
                icode_start, icode_end = icode_end, icode_start
            for (chain_label, seq, icode), matching in by_key.items():
                if chain_label != chain_a:
                    continue
                if not ((seq_a, icode_start) <= (seq, icode) <= (seq_b, icode_end)):
                    continue
                for residue in matching:
                    # First record wins: an overlapping HELIX/SHEET record must
                    # not silently relabel a residue that is already assigned.
                    if residue.ss == "C":
                        residue.ss = ss_type  # type: ignore[assignment]
                        relabelled += 1
    return relabelled


def build_ss_warning(residues: list[Residue], method: str) -> StructureWarning | None:
    content = {"H": 0, "E": 0}
    for residue in residues:
        if residue.ss in content:
            content[residue.ss] += 1
    if content["H"] == 0 and content["E"] == 0:
        return StructureWarning(
            code="no_secondary_structure",
            message=(
                "No secondary structure could be assigned. The cartoon representation will "
                "render this structure as a single coil."
            ),
            severity="info",
        )
    return None
