"""One-shot diagnostic. Run: PYTHONPATH=. .venv/bin/python scripts/diagnose.py"""

from __future__ import annotations

from pathlib import Path

import gemmi

from app.services.io.parsers import (
    _gemmi_connections,
    _gemmi_ss_ranges,
    parse_structure_file,
    parse_with_gemmi,
)

DATA = Path(__file__).resolve().parent.parent / "app" / "data"


def section(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


def main() -> None:
    for fname in ("1UBQ.pdb", "1STP.pdb", "3PTB.pdb"):
        section(f"SS ranges {fname}")
        doc = gemmi.read_structure(str(DATA / fname))
        ranges = _gemmi_ss_ranges(doc)
        print("  H:", ranges["H"])
        print("  E (first 4):", ranges["E"][:4], "total", len(ranges["E"]))

        parsed = parse_with_gemmi(DATA / fname, "pdb", name=fname, source="diag")
        print("  ss source metadata:", parsed.metadata.get("secondary_structure_source"))
        print("  first residue chain_label:", repr(parsed.residues[0].chain_label))
        print("  chains:", [(c.id, c.kind) for c in parsed.chains])
        from collections import Counter

        print("  ss counter:", Counter(r.ss for r in parsed.residues))
        print("  geometric fallback?", parsed.metadata.get("secondary_structure_method"))

    section("connections 3PTB")
    doc = gemmi.read_structure(str(DATA / "3PTB.pdb"))
    parsed = parse_with_gemmi(DATA / "3PTB.pdb", "pdb", name="3PTB", source="diag")
    print("  gemmi connections:", len(doc.connections))
    for c in list(doc.connections)[:3]:
        print(
            "   ",
            c.partner1.chain_name,
            c.partner1.res_id.seqid,
            c.partner1.atom_name,
            "<->",
            c.partner2.chain_name,
            c.partner2.res_id.seqid,
            c.partner2.atom_name,
            getattr(c, "type", None),
        )
    file_bonds = _gemmi_connections(doc, parsed)
    print("  file bonds from CONECT:", len(file_bonds))
    disulfide_atoms = {
        tuple(sorted((b.a, b.b)))
        for b in file_bonds
        if parsed.atoms[b.a].element == "S" and parsed.atoms[b.b].element == "S"
    }
    print("  S-S bonds:", len(disulfide_atoms))
    print("  sample:", [(parsed.atoms[b.a].name, parsed.atoms[b.b].name) for b in file_bonds][:4])

    section("implausible bonds 1UBQ")
    p = parse_structure_file(DATA / "1UBQ.pdb", "pdb", name="1UBQ", source="diag")
    for w in p.warnings:
        if w.code == "implausible_bond_lengths":
            print(" ", w.detail.get("examples"))

    section("implausible bonds benzamidine.sdf")
    lig = parse_structure_file(DATA / "benzamidine.sdf", "sdf", name="benzamidine", source="diag")
    print("  bonds:", len(lig.bonds), "atoms:", lig.atom_count)
    from app.services.io.bonds import validate_bond_lengths

    problems = validate_bond_lengths(lig.atoms, lig.bonds)
    print("  problems:", len(problems))
    for problem in problems[:10]:
        a, b = problem["a"], problem["b"]
        print(
            f"    {lig.atoms[a].name:4s}{lig.atoms[a].element:2s} - {lig.atoms[b].name:4s}"
            f"{lig.atoms[b].element:2s} d={problem['distance']} expected={problem['expected']}"
        )
    for w in lig.warnings:
        print("  WARN", w.code, w.count)

    section("altlocs present?")
    for fname in ("1UBQ.pdb", "1STP.pdb", "3PTB.pdb"):
        doc = gemmi.read_structure(str(DATA / fname))
        n_alt = 0
        codes = set()
        for model in doc:
            for chain in model:
                for residue in chain:
                    for atom in residue:
                        code = str(atom.altloc).replace("\x00", "").strip()
                        if code:
                            n_alt += 1
                            codes.add(code)
        print(f"  {fname}: {n_alt} atoms with altloc, codes={codes or '{}'}")


if __name__ == "__main__":
    main()
