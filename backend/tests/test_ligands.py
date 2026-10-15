"""Ligand import, SMILES-to-3D generation and computed descriptors.

Descriptors are *computed* values, never experimental ones. The tests check them
against well-known literature values for small molecules so that a broken RDKit
call or a unit error is caught immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chemistry.descriptors import (
    descriptors_from_file,
    descriptors_from_smiles,
)

pytestmark = pytest.mark.scientific


# --- descriptor values (RDKit output cross-checked against literature) ------
@pytest.mark.parametrize(
    ("smiles", "formula", "mw", "logp_approx"),
    [
        ("c1ccccc1", "C6H6", 78.11, 1.69),
        ("CCO", "C2H6O", 46.07, -0.00),
        ("CC(=O)Oc1ccccc1C(=O)O", "C9H8O4", 180.16, 1.31),
        # Crippen logP (RDKit) for caffeine is -1.03; the XlogP3 literature value
        # is -0.07. The two implementations disagree, so the pinned RDKit value is
        # used here and the UI always labels logP as "computed".
        ("CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "C8H10N4O2", 194.19, -1.03),
        # Adenosine (adenine + ribofuranose): C10H13N5O4, MW 267.24. RDKit's
        # Crippen logP is about -1.98 — very hydrophilic, as the 4 donors / 8
        # acceptors and 139.5 A^2 TPSA suggest.
        ("Nc1ncnc2n(cnc12)C3OC(CO)C(O)C3O", "C10H13N5O4", 267.24, -1.98),
    ],
)
def test_descriptors_match_literature_values(
    smiles: str, formula: str, mw: float, logp_approx: float
) -> None:
    descriptors = descriptors_from_smiles(smiles)
    assert descriptors.formula == formula
    assert descriptors.molecular_weight == pytest.approx(mw, abs=0.05)
    assert descriptors.logp == pytest.approx(logp_approx, abs=0.35)


def test_aspirin_lipinski_profile() -> None:
    descriptors = descriptors_from_smiles("CC(=O)Oc1ccccc1C(=O)O")
    assert descriptors.h_bond_donors == 1
    # Lipinski's definition counts every N/O acceptor; the h-bond acceptor count
    # is representation-independent because descriptors are computed on an
    # explicit-hydrogen copy (see app/services/chemistry/descriptors.py).
    assert descriptors.h_bond_acceptors == 4
    assert descriptors.rotatable_bonds == 2
    assert descriptors.aromatic_rings == 1
    assert descriptors.heavy_atoms == 13
    assert descriptors.valid is True


def test_benzene_has_no_donors_or_acceptors() -> None:
    descriptors = descriptors_from_smiles("c1ccccc1")
    assert descriptors.h_bond_donors == 0
    assert descriptors.h_bond_acceptors == 0
    assert descriptors.rotatable_bonds == 0
    assert descriptors.aromatic_rings == 1
    assert descriptors.ring_count == 1


def test_inchi_key_is_reported() -> None:
    descriptors = descriptors_from_smiles("c1ccccc1")
    assert descriptors.inchi_key is not None
    assert descriptors.inchi_key.startswith("UHOVQNZJYSORNB")


def test_charged_species_report_formal_charge() -> None:
    descriptors = descriptors_from_smiles("[Na+]")
    assert descriptors.formal_charge == 1
    descriptors = descriptors_from_smiles("C(=O)([O-])C")
    assert descriptors.formal_charge == -1


def test_invalid_smiles_is_rejected() -> None:
    from app.core.errors import StructureParseError

    with pytest.raises(StructureParseError):
        descriptors_from_smiles("C1CC")  # unclosed ring


def test_descriptors_from_the_sample_sdf(sample_data: Path) -> None:
    descriptors = descriptors_from_file(sample_data / "benzamidine.sdf", "sdf")
    # Benzamidine: C7H8N2, MW 120.15.
    assert descriptors.formula == "C7H8N2"
    assert descriptors.molecular_weight == pytest.approx(120.15, abs=0.05)
    assert descriptors.h_bond_donors >= 2
    assert descriptors.valid


# --- API -------------------------------------------------------------------
def test_ligand_from_smiles_creates_a_3d_structure(client, project) -> None:
    response = client.post(
        "/api/ligands/from-smiles",
        json={"projectId": project["id"], "smiles": "c1ccccc1", "name": "Benzene", "embed3d": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["ligand"]["formula"] == "C6H6"
    assert body["ligand"]["molecularWeight"] == pytest.approx(78.11, abs=0.05)
    assert body["ligand"]["descriptorSource"] == "computed"
    assert body["statistics"]["atoms"] == 12  # 6 C + 6 H with explicit hydrogens
    assert body["structure"]["kind"] == "ligand"
    assert body["packetUrl"].endswith("/packet")
    assert body["provenance"]["sourceMetadata"]["generator"].startswith("RDKit")


def test_ligand_from_smiles_without_3d(client, project) -> None:
    response = client.post(
        "/api/ligands/from-smiles",
        json={"projectId": project["id"], "smiles": "CCO", "name": "Ethanol", "embed3d": False},
    )
    assert response.status_code == 201, response.text
    assert response.json()["ligand"]["formula"] == "C2H6O"


def test_ligand_from_smiles_rejects_bad_smiles(client, project) -> None:
    response = client.post(
        "/api/ligands/from-smiles",
        json={"projectId": project["id"], "smiles": "C1CC", "name": "Broken"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "structure_parse_error"


def test_ligand_import_and_listing(client, project, sample_data: Path) -> None:
    with (sample_data / "benzamidine.sdf").open("rb") as handle:
        response = client.post(
            "/api/ligands/import",
            files={"file": ("benzamidine.sdf", handle, "chemical/x-mdl-sdfile")},
            data={"projectId": project["id"], "name": "Benzamidine"},
        )
    assert response.status_code == 201, response.text
    ligand_id = response.json()["ligand"]["id"]

    listed = client.get("/api/ligands", params={"projectId": project["id"]})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == ligand_id

    detail = client.get(f"/api/ligands/{ligand_id}")
    assert detail.status_code == 200
    assert detail.json()["molecularWeight"] == pytest.approx(120.15, abs=0.05)


def test_unknown_ligand_returns_404(client) -> None:
    response = client.get("/api/ligands/lig_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
