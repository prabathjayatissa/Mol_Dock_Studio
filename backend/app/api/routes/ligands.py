"""Ligand endpoints: import, SMILES-based creation, descriptors."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, File, Form, UploadFile, status
from sqlalchemy import select

from app.api.deps import AppSettings, DbSession, StoreDep
from app.core.errors import NotFoundError, StructureParseError
from app.db.models import Ligand
from app.schemas.ligands import LigandListOut, LigandOut, LigandSmilesRequest
from app.schemas.structures import ImportResultOut
from app.services.structures import import_structure, structure_detail_payload

router = APIRouter(prefix="/ligands", tags=["ligands"])


@router.post(
    "/import",
    response_model=ImportResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Import a ligand file (SDF, MOL, MOL2, XYZ, PDBQT)",
)
async def import_ligand(
    session: DbSession,
    store: StoreDep,
    settings: AppSettings,
    file: UploadFile = File(...),
    projectId: str = Form(...),
    name: str | None = Form(None),
    format: str | None = Form(None),
) -> ImportResultOut:
    chunk_size = 1 << 20
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            from app.core.errors import UploadRejectedError

            raise UploadRejectedError(
                f"'{file.filename}' exceeds the {settings.max_upload_mb} MB upload limit."
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    outcome = import_structure(
        session,
        project_id=projectId,
        data=data,
        filename=file.filename or "ligand.sdf",
        declared_format=format,
        name=name,
        kind="ligand",
        store=store,
    )
    detail = structure_detail_payload(session, outcome.record.id)
    return ImportResultOut(
        structure=detail,
        warnings=outcome.record.warnings or [],
        statistics=outcome.parsed.summary(),
        ligand=detail.get("ligand"),
        packetUrl=f"/api/structures/{outcome.record.id}/packet",
        provenance=outcome.record.provenance or {},
    )


@router.post(
    "/from-smiles",
    response_model=ImportResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a ligand from a SMILES string with an RDKit 3D conformer",
)
def ligand_from_smiles(payload: LigandSmilesRequest, session: DbSession, store: StoreDep) -> ImportResultOut:
    """Used by the molecule-sketching workflow: a drawn structure arrives as SMILES."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(payload.smiles)
    if mol is None:
        raise StructureParseError(
            f"'{payload.smiles}' is not a valid SMILES string.",
            remediation="Check ring closures, valence and stereochemistry markers.",
        )
    mol = Chem.AddHs(mol)

    sdf_block: str
    if payload.embed3d:
        params = AllChem.ETKDGv3()
        params.randomSeed = payload.seed
        if AllChem.EmbedMolecule(mol, params) != 0:
            raise StructureParseError(
                "RDKit could not generate a 3D conformer for this molecule.",
                detail={"smiles": payload.smiles},
                remediation="Check for unusual valences, or import a prepared 3D structure.",
            )
        with contextlib.suppress(Exception):
            # MMFF parameters are not universal; a force-field failure is not fatal
            # because the ETKDG geometry is still a valid conformer.
            AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        sdf_block = Chem.MolToMolBlock(mol)
    else:
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        sdf_block = Chem.MolToMolBlock(mol)

    # The stored SDF is the source of truth: descriptors are recomputed from it
    # during import, so the ligand record and the 3D file can never disagree.
    sdf_block = (
        f"{payload.name[:200]}\n"
        f"  MolDock 3D\n"
        f"  {payload.smiles}\n"
        + "\n".join(sdf_block.split("\n")[3:])
    )

    outcome = import_structure(
        session,
        project_id=payload.projectId,
        data=sdf_block.encode("utf-8"),
        filename=f"{payload.name[:40] or 'ligand'}.sdf",
        declared_format="sdf",
        name=payload.name,
        kind="ligand",
        source="generated",
        store=store,
        source_metadata={
            "inputSmiles": payload.smiles,
            "embedded3d": payload.embed3d,
            "seed": payload.seed,
            "generator": "RDKit ETKDGv3 + MMFF94",
        },
    )
    detail = structure_detail_payload(session, outcome.record.id)
    return ImportResultOut(
        structure=detail,
        warnings=outcome.record.warnings or [],
        statistics=outcome.parsed.summary(),
        ligand=detail.get("ligand"),
        packetUrl=f"/api/structures/{outcome.record.id}/packet",
        provenance=outcome.record.provenance or {},
    )


@router.get("", response_model=LigandListOut, summary="List ligands in a project")
def list_ligands(session: DbSession, projectId: str) -> LigandListOut:
    rows = session.scalars(
        select(Ligand).where(Ligand.project_id == projectId).order_by(Ligand.created_at)
    ).all()
    return LigandListOut(
        items=[LigandOut.model_validate(row, from_attributes=True) for row in rows],
        total=len(rows),
    )


@router.get("/{ligand_id}", response_model=LigandOut, summary="Ligand detail with computed descriptors")
def get_ligand(ligand_id: str, session: DbSession) -> LigandOut:
    ligand = session.get(Ligand, ligand_id)
    if ligand is None:
        raise NotFoundError(f"Ligand '{ligand_id}' does not exist.")
    return LigandOut.model_validate(ligand, from_attributes=True)
