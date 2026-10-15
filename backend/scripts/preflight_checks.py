"""Batched preflight checks.

Runs every assumption the test suite makes about real sample files and RDKit
behaviour in ONE interpreter process (this machine is heavily loaded, so process
startup dominates). Nothing here is a substitute for the test suite; it exists to
catch the obvious breakages before paying for a full pytest run.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.io.parsers import parse_structure_file  # noqa: E402

DATA = BACKEND / "app" / "data"

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        FAILURES.append(label)


print("=== 1UBQ ===")
ubq = parse_structure_file(DATA / "1UBQ.pdb", "pdb", name="1UBQ", source="test")
print("atoms", ubq.atom_count, "residues", len(ubq.residues), "chains", len(ubq.chains))
print("elements", ubq.element_counts)
print("ss method", ubq.metadata.get("secondary_structure_method"))
print("ss content", ubq.secondary_structure_content)
print("warnings", [w for w in ubq.warnings])
check("1UBQ 660 atoms", ubq.atom_count == 660, ubq.atom_count)
check("1UBQ 134 residues", len(ubq.residues) == 134, len(ubq.residues))
check("1UBQ one chain", len(ubq.chains) == 1, len(ubq.chains))
check("1UBQ element counts", ubq.element_counts == {"N": 105, "C": 378, "O": 176, "S": 1}, ubq.element_counts)
seq = ubq.sequences["A"]
check(
    "1UBQ sequence length 76",
    len(seq) == 76,
    seq,
)
check(
    "1UBQ sequence exact",
    seq == "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG",
    seq,
)

coords = [(a.x, a.y, a.z) for a in ubq.atoms]
cx = sum(c[0] for c in coords) / len(coords)
cy = sum(c[1] for c in coords) / len(coords)
cz = sum(c[2] for c in coords) / len(coords)
rg = math.sqrt(sum((c[0] - cx) ** 2 + (c[1] - cy) ** 2 + (c[2] - cz) ** 2 for c in coords) / len(coords))
print("1UBQ Rg", round(rg, 2))
check("1UBQ Rg ~11.8", 11.0 < rg < 12.8, round(rg, 3))

content = ubq.secondary_structure_content
print("ss fractions", {k: round(v / 76, 3) for k, v in content.items()})
check("1UBQ helix fraction", 0.10 < content["helix"] / 76 < 0.35, content["helix"])
check("1UBQ sheet fraction", 0.25 < content["sheet"] / 76 < 0.55, content["sheet"])

print()
print("=== 3PTB ===")
tryp = parse_structure_file(DATA / "3PTB.pdb", "pdb", name="3PTB", source="test")
print("atoms", tryp.atom_count, "residues", len(tryp.residues), "chains", len(tryp.chains))
print("elements", tryp.element_counts)
print("ss method", tryp.metadata.get("secondary_structure_method"))
print("hetero", [r.name for r in tryp.residues if r.is_hetero and not r.is_water])
print("warnings", tryp.warnings)
check("3PTB 1701 atoms", tryp.atom_count == 1701, tryp.atom_count)
check("3PTB 287 residues", len(tryp.residues) == 287, len(tryp.residues))
hetero = sorted({r.name for r in tryp.residues if r.is_hetero and not r.is_water})
check("3PTB hetero {BEN, CA}", hetero == ["BEN", "CA"], hetero)
check("3PTB one Ca", tryp.element_counts.get("Ca") == 1, tryp.element_counts.get("Ca"))
check("3PTB 2 chains" if len(tryp.chains) == 2 else "3PTB chains recorded",
      len(tryp.chains) == 1, len(tryp.chains))

s_bonds = []
for bond in tryp.bonds:
    a, b = tryp.atoms[bond.a], tryp.atoms[bond.b]
    if a.element == "S" and b.element == "S":
        s_bonds.append(math.dist(a.coords, b.coords))
print("SS bonds", len(s_bonds), [round(d, 3) for d in sorted(s_bonds)])
check("3PTB 6 disulfides", len(s_bonds) == 6, len(s_bonds))
check("SS lengths 2.0-2.1", all(2.00 < d < 2.10 for d in s_bonds), s_bonds)

bond_sources: dict[str, int] = {}
for bond in tryp.bonds:
    bond_sources[bond.source] = bond_sources.get(bond.source, 0) + 1
print("bond sources", bond_sources)
check("3PTB has file bonds", "file" in bond_sources, bond_sources)
print("unresolved connections warning:", [w for w in tryp.warnings if w.code == "unresolved_connections"])

print()
print("=== diagnostic: atoms in implausible bonds ===")
for label, structure in (("1UBQ", ubq), ("3PTB", tryp)):
    for warning in structure.warnings:
        if warning.code != "implausible_bond_lengths":
            continue
        for example in warning.detail.get("examples", []):
            ai, bi = example["a"], example["b"]
            for idx in (ai, bi):
                atom = structure.atoms[idx]
                res = structure.residues[atom.residue_index]
                print(
                    f"  {label} atom {idx}: {atom.name} {atom.element} "
                    f"residue {res.name}{res.seq} chain {structure.chains[atom.chain_index].id} "
                    f"aa={res.is_amino_acid} water={res.is_water} hetero={atom.is_hetero}"
                )

ben = next(r for r in tryp.residues if r.name == "BEN")
ben_atoms = [tryp.atoms[i] for i in range(ben.atom_start, ben.atom_start + ben.atom_count)]
print("BEN atoms", ben.atom_count)
protein_atoms = [a for a in tryp.atoms if not a.is_water and not a.is_hetero]
min_dist = min(math.dist(ligand_atom.coords, protein_atom.coords) for ligand_atom in ben_atoms for protein_atom in protein_atoms)
print("BEN closest protein contact", round(min_dist, 3))
check("BEN contact 2.5-4.0", 2.5 < min_dist < 4.0, round(min_dist, 3))

ben_heavy = [a for a in ben_atoms if a.element != "H"]
check("BEN no covalent protein bond", not any(
    (tryp.atoms[bond.a] in ben_atoms) != (tryp.atoms[bond.b] in ben_atoms)
    and tryp.atoms[bond.a].element in {"C", "N", "O"}
    and tryp.atoms[bond.b].element in {"C", "N", "O"}
    for bond in tryp.bonds
    if (tryp.atoms[bond.a] in ben_atoms) or (tryp.atoms[bond.b] in ben_atoms)
), "checked")

peptide = []
res = tryp.residues
for i in range(len(res) - 1):
    a, b = res[i], res[i + 1]
    if a.is_amino_acid and b.is_amino_acid and a.chain_index == b.chain_index and a.c_index is not None and b.n_index is not None:
        peptide.append(math.dist(tryp.atoms[a.c_index].coords, tryp.atoms[b.n_index].coords))
peptide.sort()
print("peptide bonds", len(peptide), "median", round(peptide[len(peptide) // 2], 3), "max", round(peptide[-1], 3))
check("peptide count > 200", len(peptide) > 200, len(peptide))
check("peptide median 1.33", abs(peptide[len(peptide) // 2] - 1.33) < 0.03, peptide[len(peptide) // 2])
check("peptide max < 1.6", peptide[-1] < 1.6, peptide[-1])

print()
print("=== benzamidine.sdf ===")
ben_sdf = parse_structure_file(DATA / "benzamidine.sdf", "sdf", name="benzamidine", source="test")
print("atoms", ben_sdf.atom_count, "bonds", len(ben_sdf.bonds), "elements", ben_sdf.element_counts)
print("connectivity_source", ben_sdf.metadata.get("connectivity_source"))
check("SDF 17 atoms", ben_sdf.atom_count == 17, ben_sdf.atom_count)
check("SDF 17 bonds", len(ben_sdf.bonds) == 17, len(ben_sdf.bonds))
check("SDF file bonds", {b.source for b in ben_sdf.bonds} == {"file"}, {b.source for b in ben_sdf.bonds})

print()
print("=== RDKit descriptors ===")
from app.services.chemistry.descriptors import descriptors_from_file  # noqa: E402

for name, expected_mw in (("benzamidine.sdf", 120.15), ("aspirin.sdf", 180.16),
                          ("caffeine.sdf", 194.19), ("ethanol.sdf", 46.07)):
    d = descriptors_from_file(DATA / name, "sdf")
    print(f"{name}: formula={d.formula} MW={d.molecular_weight} logP={d.logp} HBD={d.h_bond_donors} HBA={d.h_bond_acceptors} rot={d.rotatable_bonds}")
    check(f"{name} MW", abs(d.molecular_weight - expected_mw) < 0.5, d.molecular_weight)

d = descriptors_from_file(DATA / "benzamidine.sdf", "sdf")
check("benzamidine formula", d.formula == "C7H8N2", d.formula)
check("benzamidine HBD >= 2", d.h_bond_donors >= 2, d.h_bond_donors)

print()
print("=== descriptor consistency: explicit H vs implicit H ===")
from rdkit import Chem, RDLogger  # noqa: E402

from app.services.chemistry.descriptors import (  # noqa: E402
    _descriptors_from_mol,
    descriptors_from_smiles,
)

RDLogger.DisableLog("rdApp.*")
SMILES_FOR = {
    "benzamidine.sdf": "N=C(N)c1ccccc1",
    "aspirin.sdf": "CC(=O)Oc1ccccc1C(=O)O",
    "caffeine.sdf": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "ethanol.sdf": "CCO",
}
for name, smiles in SMILES_FOR.items():
    with_h = Chem.MolFromMolFile(str(DATA / name), removeHs=False, sanitize=True)
    without_h = Chem.MolFromSmiles(smiles)
    d_h = _descriptors_from_mol(with_h)
    d_i = _descriptors_from_mol(without_h)
    print(
        f"{name}: logP(explicitH)={d_h.logp} logP(implicitH)={d_i.logp} "
        f"| TPSA {d_h.tpsa} vs {d_i.tpsa} | HBD {d_h.h_bond_donors} vs {d_i.h_bond_donors} "
        f"| HBA {d_h.h_bond_acceptors} vs {d_i.h_bond_acceptors}"
    )
    check(
        f"{name} logP independent of explicit H",
        abs((d_h.logp or 0) - (d_i.logp or 0)) < 0.01,
        (d_h.logp, d_i.logp),
    )
    check(
        f"{name} TPSA independent of explicit H",
        (d_h.tpsa or 0) == (d_i.tpsa or 0),
        (d_h.tpsa, d_i.tpsa),
    )

print()
print("=== extra reference values for tests ===")
for smi, label in (
    ("c1ccccc1", "benzene"),
    ("Nc1ncnc2n(cnc12)C3OC(CO)C(O)C3O", "adenosine"),
    ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "caffeine"),
):
    dd = descriptors_from_smiles(smi)
    print(f"{label}: formula={dd.formula} MW={dd.molecular_weight} logP={dd.logp} HBD={dd.h_bond_donors} HBA={dd.h_bond_acceptors} rings={dd.aromatic_rings}")

asp_norm = _descriptors_from_mol(Chem.AddHs(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")))
print(f"aspirin + AddHs: HBA={asp_norm.h_bond_acceptors} HBD={asp_norm.h_bond_donors} heavy={asp_norm.heavy_atoms} rot={asp_norm.rotatable_bonds} logP={asp_norm.logp}")
print(f"benzamidine.sdf SMILES: {descriptors_from_file(DATA / 'benzamidine.sdf', 'sdf').smiles}")
print(f"benzamidine HBD/HBA: {d.h_bond_donors}/{d.h_bond_acceptors}")

from rdkit import Chem  # noqa: E402

mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
try:
    block = Chem.MolToMolBlock(mol)
    print("no-conformer MolToMolBlock: produced", len(block.splitlines()), "lines")
    check("no-conformer MolToMolBlock works", block.strip() != "")
except Exception as exc:  # noqa: BLE001
    print("no-conformer MolToMolBlock raised:", type(exc).__name__, exc)
    check("no-conformer MolToMolBlock works", False, exc)

print()
print("=== surface single sphere ===")
import numpy as np  # noqa: E402

from app.services.geometry.surface import generate_surface  # noqa: E402

mesh = generate_surface(np.zeros((1, 3)), np.array([1.7]), mode="vdw", grid_spacing=0.4)
analytic_area = 4 * math.pi * 1.7**2
analytic_volume = 4 / 3 * math.pi * 1.7**3
print("area", round(mesh.area, 2), "vs", round(analytic_area, 2))
print("volume", round(mesh.volume, 2), "vs", round(analytic_volume, 2))
check("sphere area rel<0.06", abs(mesh.area - analytic_area) / analytic_area < 0.06,
      abs(mesh.area - analytic_area) / analytic_area)
check("sphere volume rel<0.06", abs(mesh.volume - analytic_volume) / analytic_volume < 0.06,
      abs(mesh.volume - analytic_volume) / analytic_volume)
check("mesh float32 verts", mesh.vertices.dtype == np.float32, mesh.vertices.dtype)
check("mesh uint32 faces", mesh.faces.dtype == np.uint32, mesh.faces.dtype)

print()
print("=== grid budget (8 atoms over 100 A cube) ===")
corners = np.array([[x, y, z] for x in (0.0, 100.0) for y in (0.0, 100.0) for z in (0.0, 100.0)])
budget = generate_surface(corners, np.full(len(corners), 1.7), mode="vdw", grid_spacing=0.35)
print("grid_shape", budget.grid_shape, "spacing_used", round(budget.spacing_used, 4), "warnings", len(budget.warnings))
check("budget respected", int(np.prod(budget.grid_shape)) <= 6_000_000, np.prod(budget.grid_shape))
check("budget warns", bool(budget.warnings), budget.warnings)
check("budget coarsened spacing", budget.spacing_used > 0.35, budget.spacing_used)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURES:")
    for failure in FAILURES:
        print(" -", failure)
    sys.exit(1)
print("all preflight checks passed")
