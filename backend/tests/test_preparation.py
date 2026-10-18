"""Phase 2 preparation tests: receptor prep, ligand prep, binding sites.

These use only RDKit + gemmi (available on this machine). AutoDock Vina,
PDB2PQR and Open Babel are intentionally not required here; they belong to
Phases 3+ and are documented as unavailable in ``/api/health``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.scientific


def _import(client, project_id: str, path: Path, *, kind: str | None = None) -> dict:
    data = {"projectId": project_id}
    if kind:
        data["kind"] = kind
    with path.open("rb") as handle:
        response = client.post(
            "/api/structures/import",
            files={"file": (path.name, handle, "chemical/x-pdb")},
            data=data,
        )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Receptor preparation
# ---------------------------------------------------------------------------


def test_prepare_receptor_removes_waters_and_cofactors(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]
    original_atoms = body["structure"]["atomsCount"]

    response = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": False, "keepCofactors": False},
    )
    assert response.status_code == 201, response.text
    prep = response.json()

    assert prep["kind"] == "receptor"
    assert prep["atomsKept"] < original_atoms
    assert prep["atomsRemoved"] == original_atoms - prep["atomsKept"]
    assert prep["residuesKept"] > 0
    assert prep["status"] == "completed"

    # Output structure is linked to its input.
    derived = client.get(f"/api/structures/{prep['outputStructureId']}")
    assert derived.status_code == 200
    assert derived.json()["kind"] == "receptor"
    assert derived.json()["parentStructureId"] == structure_id


def test_prepare_receptor_keep_waters_keeps_more_atoms(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]

    dry = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": False, "keepCofactors": False},
    ).json()
    wet = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": True, "keepCofactors": False},
    ).json()

    assert wet["atomsKept"] >= dry["atomsKept"]
    assert wet["residuesKept"] >= dry["residuesKept"]


def test_prepare_receptor_keep_chains_filters(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]

    # Keep only chain A.
    response = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepChains": ["A"]},
    )
    assert response.status_code == 201, response.text
    prep = response.json()
    assert prep["chainsKept"] <= 1

    # Unknown chain is rejected.
    response = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepChains": ["ZZ"]},
    )
    assert response.status_code == 422, response.text


def test_prepare_receptor_unknown_structure(client, project) -> None:
    response = client.post(
        "/api/preparation/receptor/does-not-exist",
        params={"keepWaters": False, "keepCofactors": False},
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# Ligand preparation
# ---------------------------------------------------------------------------


def test_prepare_ligand_from_smiles_generated_structure(
    client, project, sample_data: Path
) -> None:
    # First create a ligand from SMILES (aspirin), then prepare it.
    smiles_response = client.post(
        "/api/ligands/from-smiles",
        json={
            "projectId": project["id"],
            "name": "aspirin",
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",
            "embed3d": True,
            "seed": 42,
        },
    )
    assert smiles_response.status_code == 201, smiles_response.text
    ligand_structure_id = smiles_response.json()["structure"]["id"]

    response = client.post(
        f"/api/preparation/ligand/{ligand_structure_id}",
        params={"embed3d": True, "seed": 42, "optimize": True},
    )
    assert response.status_code == 201, response.text
    prep = response.json()

    assert prep["kind"] == "ligand"
    assert prep["conformers"] == 1
    assert prep["embedding"] == "ETKDGv3"
    assert prep["optimization"] == "MMFF94"
    assert prep["status"] == "completed"

    derived = client.get(f"/api/structures/{prep['outputStructureId']}")
    assert derived.status_code == 200
    assert derived.json()["kind"] == "ligand"
    assert derived.json()["parentStructureId"] == ligand_structure_id


def test_prepare_ligand_requires_ligand_structure(
    client, project, sample_data: Path
) -> None:
    # 3PTB is a complex (has polymer chains) - not ligand-like.
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]

    response = client.post(
        f"/api/preparation/ligand/{structure_id}",
        params={"embed3d": True},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Binding sites
# ---------------------------------------------------------------------------


def test_define_binding_site_manual(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    receptor_id = body["structure"]["id"]

    # First prepare a receptor (binding sites require receptor-like kinds).
    prep = client.post(
        f"/api/preparation/receptor/{receptor_id}",
        params={"keepWaters": False, "keepCofactors": False},
    ).json()
    receptor_id = prep["outputStructureId"]

    response = client.post(
        "/api/binding-sites",
        json={
            "projectId": project["id"],
            "receptorStructureId": receptor_id,
            "name": "Active site",
            "method": "manual",
            "centerX": 10.0,
            "centerY": 20.0,
            "centerZ": 30.0,
            "sizeX": 22.0,
            "sizeY": 22.0,
            "sizeZ": 22.0,
        },
    )
    assert response.status_code == 201, response.text
    site = response.json()

    assert site["method"] == "manual"
    assert site["centerX"] == 10.0
    assert site["centerY"] == 20.0
    assert site["centerZ"] == 30.0
    assert site["sizeX"] == 22.0
    assert site["receptorStructureId"] == receptor_id


def test_define_binding_site_from_ligand(
    client, project, sample_data: Path
) -> None:
    # Import 3PTB (trypsin + benzamidine complex) as the receptor, and the
    # standalone benzamidine ligand as the reference for the site.
    complex_body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    receptor_id = complex_body["structure"]["id"]

    prep = client.post(
        f"/api/preparation/receptor/{receptor_id}",
        params={"keepWaters": False, "keepCofactors": False},
    ).json()
    receptor_id = prep["outputStructureId"]

    ligand_body = _import(client, project["id"], sample_data / "benzamidine.sdf", kind="ligand")
    ligand_structure_id = ligand_body["structure"]["id"]

    response = client.post(
        "/api/binding-sites",
        json={
            "projectId": project["id"],
            "receptorStructureId": receptor_id,
            "name": "Benzamidine site",
            "method": "ligand",
            "referenceLigandStructureId": ligand_structure_id,
        },
    )
    assert response.status_code == 201, response.text
    site = response.json()

    assert site["method"] == "ligand"
    assert site["sourceLigandStructureId"] == ligand_structure_id
    assert site["sizeX"] >= 22.0  # padded to sane minimum
    assert site["sizeY"] >= 22.0
    assert site["sizeZ"] >= 22.0


def test_define_binding_site_manual_missing_centre(client, project) -> None:
    response = client.post(
        "/api/binding-sites",
        json={
            "projectId": project["id"],
            "receptorStructureId": "does-not-exist",
            "name": "Site",
            "method": "manual",
            # centre missing
        },
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


def test_list_preparations_and_sites(client, project, sample_data: Path) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]

    client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": False, "keepCofactors": False},
    )
    response = client.get(
        "/api/preparation/receptor-preps", params={"projectId": project["id"]}
    )
    assert response.status_code == 200
    assert len(response.json()) >= 1

    response = client.get(
        "/api/preparation/ligand-preps", params={"projectId": project["id"]}
    )
    assert response.status_code == 200

    response = client.get(
        "/api/binding-sites", params={"projectId": project["id"]}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Receptor prep with hydrogen addition
# ---------------------------------------------------------------------------


def test_prepare_receptor_with_hydrogens(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]
    original_atoms = body["structure"]["atomsCount"]

    response = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": False, "keepCofactors": False, "addHydrogens": True},
    )
    assert response.status_code == 201, response.text
    prep = response.json()

    assert prep["atomsKept"] > original_atoms  # hydrogens added
    assert prep["status"] == "completed"

    # Verify the derived structure has hydrogens.
    derived = client.get(f"/api/structures/{prep['outputStructureId']}")
    assert derived.status_code == 200
    assert derived.json()["atomsCount"] > original_atoms


# ---------------------------------------------------------------------------
# Ligand prep with conformer ensembles
# ---------------------------------------------------------------------------


def test_prepare_ligand_multiple_conformers(
    client, project, sample_data: Path
) -> None:
    # Import a ligand SDF (benzamidine), then prepare with multiple conformers.
    body = _import(client, project["id"], sample_data / "benzamidine.sdf", kind="ligand")
    ligand_structure_id = body["structure"]["id"]

    response = client.post(
        f"/api/preparation/ligand/{ligand_structure_id}",
        params={"embed3d": True, "seed": 42, "optimize": True, "maxConformers": 3},
    )
    assert response.status_code == 201, response.text
    prep = response.json()

    assert prep["kind"] == "ligand"
    assert prep["conformers"] == 3
    assert prep["embedding"] == "ETKDGv3"
    assert prep["optimization"] == "MMFF94"
    assert prep["status"] == "completed"


# ---------------------------------------------------------------------------
# PDBQT generation (Meeko)
# ---------------------------------------------------------------------------


def test_generate_pdbqt_for_receptor(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    structure_id = body["structure"]["id"]

    # First prepare the receptor with hydrogens.
    prep = client.post(
        f"/api/preparation/receptor/{structure_id}",
        params={"keepWaters": False, "keepCofactors": False, "addHydrogens": True},
    ).json()
    receptor_id = prep["outputStructureId"]

    response = client.post(f"/api/preparation/pdbqt/{receptor_id}")
    assert response.status_code == 201, response.text
    pdbqt = response.json()

    assert pdbqt["structureId"] == receptor_id
    assert pdbqt["path"].endswith(".pdbqt")
    assert len(pdbqt["sha256"]) == 64
    assert pdbqt["heavyAtoms"] > 0
    assert pdbqt["pdbqtAtoms"] > 0


def test_generate_pdbqt_for_ligand(
    client, project, sample_data: Path
) -> None:
    body = _import(client, project["id"], sample_data / "benzamidine.sdf", kind="ligand")
    structure_id = body["structure"]["id"]

    # First prepare the ligand.
    prep = client.post(
        f"/api/preparation/ligand/{structure_id}",
        params={"embed3d": True, "seed": 42, "optimize": True},
    ).json()
    ligand_id = prep["outputStructureId"]

    response = client.post(f"/api/preparation/pdbqt/{ligand_id}")
    assert response.status_code == 201, response.text
    pdbqt = response.json()

    assert pdbqt["structureId"] == ligand_id
    assert pdbqt["path"].endswith(".pdbqt")
    assert pdbqt["heavyAtoms"] > 0
    assert pdbqt["pdbqtAtoms"] > 0


# ---------------------------------------------------------------------------
# End-to-end docking preparation
# ---------------------------------------------------------------------------


def test_prepare_for_docking_end_to_end(
    client, project, sample_data: Path
) -> None:
    # Import complex (receptor) and ligand as separate structures.
    complex_body = _import(client, project["id"], sample_data / "3PTB.pdb", kind="complex")
    complex_id = complex_body["structure"]["id"]
    ligand_body = _import(client, project["id"], sample_data / "benzamidine.sdf", kind="ligand")
    ligand_id = ligand_body["structure"]["id"]

    # Prepare the receptor first (needed so binding sites can be defined on it).
    prep = client.post(
        f"/api/preparation/receptor/{complex_id}",
        params={"keepWaters": False, "keepCofactors": False, "addHydrogens": True},
    ).json()
    receptor_id = prep["outputStructureId"]

    # Define a binding site on the prepared receptor.
    site = client.post(
        "/api/binding-sites",
        json={
            "projectId": project["id"],
            "receptorStructureId": receptor_id,
            "name": "Docking site",
            "method": "manual",
            "centerX": 10.0,
            "centerY": 10.0,
            "centerZ": 10.0,
            "sizeX": 22.0,
            "sizeY": 22.0,
            "sizeZ": 22.0,
        },
    ).json()

    # End-to-end docking prep starts from the ORIGINAL complex structure
    # (re-prepares receptor from scratch) and the ligand.
    response = client.post(
        "/api/preparation/docking-prep",
        json={
            "receptorStructureId": complex_id,
            "ligandStructureId": ligand_id,
            "bindingSiteId": site["id"],
            "addHydrogens": True,
            "ligandMaxConformers": 2,
        },
    )
    assert response.status_code == 201, response.text
    result = response.json()

    assert result["receptorPrepId"] is not None
    assert result["receptorOutputStructureId"] is not None
    assert result["receptorAtomsKept"] > 0
    assert result["ligandPrepId"] is not None
    assert result["ligandOutputStructureId"] is not None
    assert result["ligandConformers"] == 2
    assert result["receptorPdbqt"]["path"].endswith(".pdbqt")
    assert result["receptorPdbqt"]["heavyAtoms"] > 0
    assert result["ligandPdbqt"]["path"].endswith(".pdbqt")
    assert result["ligandPdbqt"]["heavyAtoms"] > 0
    assert result["bindingSite"] is not None
    assert result["bindingSite"]["id"] == site["id"]
