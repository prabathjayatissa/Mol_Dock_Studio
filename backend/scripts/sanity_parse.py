"""Ad-hoc parse sanity check. Run: .venv/bin/python scripts/sanity_parse.py"""

from __future__ import annotations

from pathlib import Path

from app.services.io.parsers import parse_structure_file

DATA = Path(__file__).resolve().parent.parent / "app" / "data"


def main() -> None:
    for name, fmt in [
        ("1UBQ.pdb", "pdb"),
        ("3PTB.pdb", "pdb"),
        ("1STP.pdb", "pdb"),
        ("benzamidine.sdf", "sdf"),
        ("imatinib.sdf", "sdf"),
    ]:
        path = DATA / name
        structure = parse_structure_file(path, fmt, name=path.stem, source="sanity")
        summary = structure.summary()
        print(f"\n=== {name} -> {format}")
        print(
            "  atoms={atoms} heavy={heavy_atoms} residues={residues} chains={chains} "
            "bonds={bonds} waters={waters} hetero={hetero_residues}".format(**summary)
        )
        print("  bond sources:", structure.metadata.get("bond_sources"))
        print("  ss method:", structure.metadata.get("secondary_structure_method"), summary["secondary_structure"])
        print("  elements:", summary["elements"])
        for chain in structure.chains:
            print(f"  chain {chain.id}: kind={chain.kind} residues={chain.residue_count}")
        for warning in structure.warnings:
            print(f"  WARN [{warning.severity}] {warning.code} x{warning.count}: {warning.message}")


if __name__ == "__main__":
    main()
