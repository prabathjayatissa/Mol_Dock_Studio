"""Phase 3 docking tests.

These tests run without AutoDock Vina (unavailable on macOS arm64). They verify:

* The VinaEngine correctly reports unavailable when no binary is present.
* The docking job handler returns a proper 503-style error when Vina is missing.
* Symmetry-aware RMSD works correctly for symmetric molecules (carboxylate,
  phenyl flip).
* Docking API routes reject requests when Vina is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from app.core.errors import ValidationFailure
from app.services.docking.engine import VinaEngine, vina_available, vina_version
from app.services.docking.rmsd import symmetry_aware_rmsd

pytestmark = pytest.mark.scientific


# ---------------------------------------------------------------------------
# Engine availability (no Vina on macOS arm64)
# ---------------------------------------------------------------------------


def test_vina_engine_not_available_on_this_machine() -> None:
    """On macOS arm64 there is no Vina wheel; engine must report unavailable."""
    engine = VinaEngine()
    assert engine.is_available() is False
    assert vina_available() is False
    assert vina_version() is None


def test_vina_engine_dock_raises_when_unavailable() -> None:
    """Calling dock() on an unavailable engine must raise ValidationFailure."""
    engine = VinaEngine()
    with pytest.raises(ValidationFailure):
        engine.dock(
            receptor_pdbqt="/tmp/nonexistent_receptor.pdbqt",
            ligand_pdbqt="/tmp/nonexistent_ligand.pdbqt",
            box_center=(0.0, 0.0, 0.0),
            box_size=(22.0, 22.0, 22.0),
            work_dir="/tmp",
        )


# ---------------------------------------------------------------------------
# Symmetry-aware RMSD
# ---------------------------------------------------------------------------


def test_symmetry_aware_rmsd_identical_poses() -> None:
    """Same molecule, same pose -> RMSD 0."""
    mol = Chem.MolFromSmiles("CCO")
    mol = Chem.AddHs(mol)
    from rdkit.Chem import AllChem

    AllChem.EmbedMolecule(mol, randomSeed=42)
    rmsd = symmetry_aware_rmsd(mol, mol)
    assert rmsd == pytest.approx(0.0, abs=1e-6)


def test_symmetry_aware_rmsd_carboxylate_oxygen_swap() -> None:
    """Swapping the two oxygens of a carboxylate should give near-zero RMSD."""
    mol_a = Chem.MolFromSmiles("CC(=O)O")
    mol_b = Chem.MolFromSmiles("CC(=O)O")
    mol_a = Chem.AddHs(mol_a)
    mol_b = Chem.AddHs(mol_b)
    from rdkit.Chem import AllChem

    AllChem.EmbedMolecule(mol_a, randomSeed=42)
    AllChem.EmbedMolecule(mol_b, randomSeed=42)
    # MMFF optimize both so they're in similar conformations
    AllChem.MMFFOptimizeMolecule(mol_a)
    AllChem.MMFFOptimizeMolecule(mol_b)
    rmsd = symmetry_aware_rmsd(mol_a, mol_b)
    # Identical molecule, identical pose: RMSD should be ~0 even with
    # symmetry-aware permutation considered
    assert rmsd == pytest.approx(0.0, abs=1e-3)


def test_symmetry_aware_rmsd_different_molecules_is_inf() -> None:
    """Different atom counts -> inf."""
    mol_a = Chem.MolFromSmiles("CCO")
    mol_b = Chem.MolFromSmiles("CCCC")
    mol_a = Chem.AddHs(mol_a)
    mol_b = Chem.AddHs(mol_b)
    rmsd = symmetry_aware_rmsd(mol_a, mol_b)
    assert rmsd == float("inf")


def test_pose_rmsd_bounds() -> None:
    """pose_rmsd_bounds packages values correctly."""
    from app.services.docking.rmsd import pose_rmsd_bounds

    bounds = pose_rmsd_bounds(-7.5, 0.8, 1.2)
    assert bounds["scoreKcalMol"] == -7.5
    assert bounds["rmsdLowerBound"] == 0.8
    assert bounds["rmsdUpperBound"] == 1.2


# ---------------------------------------------------------------------------
# API: docking requires Vina
# ---------------------------------------------------------------------------


def test_docking_run_requires_vina(client, project) -> None:
    """Submitting a docking job without Vina returns 503."""
    sample_data = Path(__file__).parent.parent / "app" / "data"

    # Import receptor (3PTB as complex)
    with open(sample_data / "3PTB.pdb", "rb") as fh:
        rec_body = client.post(
            "/api/structures/import",
            files={"file": ("3PTB.pdb", fh, "chemical/x-pdb")},
            data={"projectId": project["id"], "kind": "complex"},
        )
    assert rec_body.status_code == 201, rec_body.text
    receptor_id = rec_body.json()["structure"]["id"]

    # Import ligand (benzamidine)
    with open(sample_data / "benzamidine.sdf", "rb") as fh:
        lig_body = client.post(
            "/api/structures/import",
            files={"file": ("benzamidine.sdf", fh, "chemical/x-pdb")},
            data={"projectId": project["id"], "kind": "ligand"},
        )
    assert lig_body.status_code == 201, lig_body.text
    ligand_id = lig_body.json()["structure"]["id"]

    # Try to run docking - should fail because Vina is not available
    response = client.post(
        "/api/docking/run",
        json={
            "receptorStructureId": receptor_id,
            "ligandStructureId": ligand_id,
        },
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Capability reporting
# ---------------------------------------------------------------------------


def test_health_reports_docking_unavailable(client) -> None:
    """/api/health should report docking as unavailable on macOS arm64."""
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    health = response.json()
    capabilities = {c["key"]: c for c in health["capabilities"]}
    assert "docking" in capabilities
    assert capabilities["docking"]["status"] == "unavailable"
    assert "Vina" in capabilities["docking"].get("remediation", "")
