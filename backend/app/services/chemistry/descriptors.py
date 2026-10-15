"""Ligand descriptors computed with RDKit.

Every number produced here is *computed*, never measured. The originating
structure record stores ``descriptor_source = "computed"`` and the UI labels the
panel accordingly, so a LogP estimate is never mistaken for an experimental
value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import StructureParseError


@dataclass
class LigandDescriptors:
    smiles: str | None = None
    inchi_key: str | None = None
    formula: str | None = None
    molecular_weight: float | None = None
    exact_mass: float | None = None
    logp: float | None = None
    tpsa: float | None = None
    h_bond_donors: int | None = None
    h_bond_acceptors: int | None = None
    rotatable_bonds: int | None = None
    formal_charge: int | None = None
    heavy_atoms: int | None = None
    aromatic_rings: int | None = None
    ring_count: int | None = None
    stereocenters: int | None = None
    fraction_csp3: float | None = None
    valid: bool = True
    messages: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "smiles": self.smiles,
            "inchiKey": self.inchi_key,
            "formula": self.formula,
            "molecularWeight": _round(self.molecular_weight, 3),
            "exactMass": _round(self.exact_mass, 4),
            "logp": _round(self.logp, 3),
            "tpsa": _round(self.tpsa, 2),
            "hBondDonors": self.h_bond_donors,
            "hBondAcceptors": self.h_bond_acceptors,
            "rotatableBonds": self.rotatable_bonds,
            "formalCharge": self.formal_charge,
            "heavyAtoms": self.heavy_atoms,
            "aromaticRings": self.aromatic_rings,
            "ringCount": self.ring_count,
            "stereocenters": self.stereocenters,
            "fractionCsp3": _round(self.fraction_csp3, 3),
            "valid": self.valid,
            "messages": self.messages,
        }


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _hydrogen_normalised(mol: Any) -> Any:
    """A copy of ``mol`` with all hydrogens explicit.

    RDKit computes most descriptors identically whether or not hydrogens are
    explicit, but ``NumHAcceptors`` is sensitive to the representation (aspirin
    gives 4 with explicit H and 3 without). Descriptors must depend only on the
    molecular graph, so they are always computed on an explicit-H copy and the
    same ligand therefore yields the same numbers whichever file it came from.
    """
    from rdkit import Chem

    try:
        return Chem.AddHs(mol, addCoords=False)
    except Exception:  # noqa: BLE001 - unsanitised/exotic molecules keep their form
        return mol


def _descriptors_from_mol(mol: Any, *, sanitize_messages: list[dict[str, Any]] | None = None) -> LigandDescriptors:
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

    descriptors = LigandDescriptors(messages=list(sanitize_messages or []))
    descriptors.smiles = Chem.MolToSmiles(Chem.RemoveHs(mol)) if mol.GetNumAtoms() else None
    try:
        descriptors.inchi_key = Chem.MolToInchiKey(mol) if mol.GetNumAtoms() else None
    except Exception:  # noqa: BLE001 - InChI is optional
        descriptors.inchi_key = None

    graph = _hydrogen_normalised(mol)
    descriptors.formula = rdMolDescriptors.CalcMolFormula(graph)
    descriptors.molecular_weight = Descriptors.MolWt(graph)
    descriptors.exact_mass = Descriptors.ExactMolWt(graph)
    descriptors.logp = Crippen.MolLogP(graph)
    descriptors.tpsa = rdMolDescriptors.CalcTPSA(graph)
    descriptors.h_bond_donors = Lipinski.NumHDonors(graph)
    descriptors.h_bond_acceptors = Lipinski.NumHAcceptors(graph)
    descriptors.rotatable_bonds = Lipinski.NumRotatableBonds(graph)
    descriptors.formal_charge = Chem.GetFormalCharge(graph)
    descriptors.heavy_atoms = graph.GetNumHeavyAtoms()
    descriptors.aromatic_rings = rdMolDescriptors.CalcNumAromaticRings(graph)
    descriptors.ring_count = rdMolDescriptors.CalcNumRings(graph)
    descriptors.stereocenters = len(Chem.FindMolChiralCenters(graph, includeUnassigned=True, useLegacyImplementation=False))
    descriptors.fraction_csp3 = rdMolDescriptors.CalcFractionCSP3(graph)

    # Chemical validity checks that matter before any preparation step.
    unassigned = [
        atom.GetIdx()
        for atom in mol.GetAtoms()
        if atom.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED and atom.GetDegree() >= 3 and atom.GetSymbol() == "C"
    ]
    radicals = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetNumRadicalElectrons()]
    if radicals:
        descriptors.valid = False
        descriptors.messages.append(
            {
                "code": "radicals",
                "severity": "error",
                "message": f"{len(radicals)} atom(s) carry unpaired electrons; the molecule is a radical and "
                "cannot be docked as-is.",
                "atomIndices": radicals[:20],
            }
        )
    if mol.GetNumAtoms() == 0:
        descriptors.valid = False
        descriptors.messages.append({"code": "empty", "severity": "error", "message": "The molecule has no atoms."})
    if not descriptors.h_bond_donors and mol.GetNumAtoms() == 0:
        descriptors.valid = False
    if unassigned and descriptors.stereocenters:
        descriptors.messages.append(
            {
                "code": "unassigned_stereocenters",
                "severity": "warning",
                "message": f"{len(unassigned)} potential stereocentre(s) have no assigned configuration. "
                "Stereochemistry can be enumerated during ligand preparation (Phase 2).",
                "atomIndices": unassigned[:20],
            }
        )
    return descriptors


def descriptors_from_smiles(smiles: str) -> LigandDescriptors:
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise StructureParseError(
            f"'{smiles}' is not a valid SMILES string.",
            remediation="Check the stereochemistry markers and ring closures.",
        )
    return _descriptors_from_mol(mol)


def descriptors_from_file(path: Path, fmt: str = "sdf") -> LigandDescriptors:
    """Compute descriptors for the first molecule of a structure file."""
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    messages: list[dict[str, Any]] = []
    mol = None
    if fmt in {"sdf", "mol"}:
        mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=True)
        if mol is None:
            mol = Chem.MolFromMolFile(str(path), removeHs=False, sanitize=False)
            messages.append(
                {
                    "code": "sanitization_failed",
                    "severity": "warning",
                    "message": "RDKit could not sanitise this molecule; descriptors are computed on the "
                    "unsanitised structure and should be treated as indicative only.",
                }
            )
    elif fmt == "mol2":
        mol = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=True)
        if mol is None:
            mol = Chem.MolFromMol2File(str(path), removeHs=False, sanitize=False)
            messages.append(
                {
                    "code": "sanitization_failed",
                    "severity": "warning",
                    "message": "RDKit could not sanitise this MOL2 file; descriptors are indicative only.",
                }
            )
    else:
        raise StructureParseError(
            f"Ligand descriptors cannot be computed for format '{fmt}'.",
            remediation="Convert the file to SDF/MOL2 first (Open Babel or RDKit).",
        )

    if mol is None:
        raise StructureParseError(f"RDKit could not parse '{path.name}' as a molecule.")

    return _descriptors_from_mol(mol, sanitize_messages=messages)


def smiles_from_file(path: Path, fmt: str = "sdf") -> str | None:
    return descriptors_from_file(path, fmt).smiles
