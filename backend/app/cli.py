"""Command line utilities.

    python -m app.cli capabilities     # what can this machine actually run?
    python -m app.cli init-db          # create tables
    python -m app.cli fetch-test-data  # (re)download the redistributable test set
    python -m app.cli inspect FILE     # parse one structure and print a summary
    python -m app.cli serve            # run the API (equivalent to uvicorn app.main:app)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app import __version__
from app.core.capabilities import detect_capabilities
from app.core.config import BACKEND_ROOT, get_settings
from app.core.logging import configure_logging
from app.core.roadmap import PHASES

DATA_DIR = BACKEND_ROOT / "app" / "data"

# --- redistributable test data ---------------------------------------------
# RCSB PDB entries are released into the public domain (CC0 1.0) by the
# wwPDB/RCSB PDB; see app/data/LICENSES.md. Ligands are generated locally with
# RDKit from public SMILES strings, so no third-party licence applies.
TEST_ENTRIES: dict[str, str] = {
    "1UBQ.pdb": "1UBQ",
    "3PTB.pdb": "3PTB",
    "1STP.pdb": "1STP",
}

LIGAND_SMILES: dict[str, str] = {
    "benzamidine": "NC(=N)c1ccccc1",
    "aspirin": "CC(=O)Oc1ccccc1C(=O)O",
    "ethanol": "CCO",
    "caffeine": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "imatinib": "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1",
}


def cmd_capabilities(_args: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"MolDock Studio {__version__}")
    print(f"  python          {sys.version.split()[0]}  ({sys.executable})")
    print(f"  backend mode    {settings.scientific_backend_mode}")
    print(f"  data directory  {settings.resolved_data_dir}")
    print(f"  database        {settings.resolved_database_url.split('://', 1)[0]}")
    print("\nScientific capabilities:")
    for capability in detect_capabilities(settings):
        status = capability.status.upper()
        detail = capability.version or capability.location or ""
        print(f"  [{status:<15}] {capability.label:<42} {detail}")
        if capability.status != "available" and capability.remediation:
            print(f"                    -> {capability.remediation}")
    print("\nPhases:")
    for phase in PHASES:
        print(f"  [{str(phase['status']).upper():<12}] {phase['id']:<8} {phase['name']}")
    return 0


def cmd_init_db(_args: argparse.Namespace) -> int:
    from app.db.session import init_db

    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    print(f"Database initialised at {settings.resolved_database_url}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    from app.services.io.parsers import parse_structure_file
    from app.services.store import sha256_of

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 2
    fmt = args.format
    if not fmt:
        from app.core.security import format_from_filename

        fmt = format_from_filename(path.name)
        if fmt is None:
            print(f"error: cannot infer a format for '{path.name}'; pass --format", file=sys.stderr)
            return 2

    structure = parse_structure_file(path, fmt, name=path.stem, source="cli")
    summary = structure.summary()
    print(f"File            {path}")
    print(f"Format          {fmt}  (parser family: {structure.format})")
    print(f"SHA-256         {sha256_of(path)}")
    print(f"Atoms           {summary['atoms']} ({summary['heavy_atoms']} heavy)")
    print(f"Residues        {summary['residues']}  ({summary['waters']} waters, "
          f"{summary['hetero_residues']} other hetero)")
    print(f"Chains          {summary['chains']}")
    print(f"Bonds           {summary['bonds']}  sources: {structure.metadata.get('bond_sources')}")
    print(f"Elements        {summary['elements']}")
    ss = summary["secondary_structure"]
    print(f"Secondary str.  helix={ss['helix']} sheet={ss['sheet']} coil={ss['coil']} "
          f"(method: {structure.metadata.get('secondary_structure_method')})")
    print(f"Bounding radius {summary['bounding_radius']} A")
    if structure.sequences:
        for chain, sequence in structure.sequences.items():
            print(f"Sequence {chain}     {len(sequence)} residues: {sequence[:60]}{'...' if len(sequence) > 60 else ''}")
    if structure.warnings:
        print("\nWarnings / information loss:")
        for warning in structure.warnings:
            count = f" (x{warning.count})" if warning.count != 1 else ""
            print(f"  [{warning.severity}] {warning.code}{count}: {warning.message}")
    else:
        print("\nNo warnings: nothing was dropped or converted during parsing.")
    return 0


def cmd_fetch_test_data(args: argparse.Namespace) -> int:
    import httpx
    from rdkit import Chem
    from rdkit.Chem import AllChem

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    base = settings.rcsb_base_url.rstrip("/")
    force = bool(args.force)
    failures = 0

    for filename, entry_id in TEST_ENTRIES.items():
        target = DATA_DIR / filename
        if target.exists() and not force:
            print(f"skip  {filename} (already present)")
            continue
        url = f"{base}/{entry_id}.pdb"
        try:
            response = httpx.get(url, timeout=settings.rcsb_timeout_seconds, follow_redirects=True)
            response.raise_for_status()
            target.write_bytes(response.content)
            print(f"ok    {filename}  ({len(response.content) / 1024:.0f} kB from {url})")
        except Exception as exc:  # noqa: BLE001 - CLI reporting
            failures += 1
            print(f"FAIL  {filename}: {exc}", file=sys.stderr)

    for name, smiles in LIGAND_SMILES.items():
        target = DATA_DIR / f"{name}.sdf"
        if target.exists() and not force:
            print(f"skip  {name}.sdf (already present)")
            continue
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            failures += 1
            print(f"FAIL  {name}: invalid SMILES", file=sys.stderr)
            continue
        mol = Chem.AddHs(mol)
        params = AllChem.ETKDGv3()
        params.randomSeed = 0xC0FFEE
        if AllChem.EmbedMolecule(mol, params) != 0:
            failures += 1
            print(f"FAIL  {name}: conformer generation failed", file=sys.stderr)
            continue
        AllChem.MMFFOptimizeMolecule(mol, maxIters=800)
        mol.SetProp("_Name", name)
        target.write_text(Chem.MolToMolBlock(mol) + "\n$$$$\n", encoding="utf-8")
        print(f"ok    {name}.sdf  ({mol.GetNumAtoms()} atoms, generated with RDKit ETKDGv3 + MMFF94)")

    if failures:
        print(f"\n{failures} item(s) failed.", file=sys.stderr)
        return 1
    print(f"\nTest data ready in {DATA_DIR}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="MolDock Studio utilities")
    parser.add_argument("--version", action="version", version=f"MolDock Studio {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities = subparsers.add_parser("capabilities", help="Report available scientific tools")
    capabilities.set_defaults(func=cmd_capabilities)

    init_db = subparsers.add_parser("init-db", help="Create database tables")
    init_db.set_defaults(func=cmd_init_db)

    inspect = subparsers.add_parser("inspect", help="Parse one structure file and print a summary")
    inspect.add_argument("path")
    inspect.add_argument("--format", default=None, help="Override format detection")
    inspect.add_argument("--json", action="store_true", help="Print the raw summary as JSON")
    inspect.set_defaults(func=cmd_inspect)

    fetch = subparsers.add_parser("fetch-test-data", help="Download the redistributable test set")
    fetch.add_argument("--force", action="store_true", help="Re-download even if the files exist")
    fetch.set_defaults(func=cmd_fetch_test_data)

    serve = subparsers.add_parser("serve", help="Run the API server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "json", False):
        # kept for scripting: emit a machine-readable structure summary
        from app.services.io.parsers import parse_structure_file

        path = Path(args.path).expanduser().resolve()
        structure = parse_structure_file(path, args.format or path.suffix.lstrip("."), source="cli")
        print(json.dumps(structure.summary(), indent=2, default=str))
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
