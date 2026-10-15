"""Structure service: import, inspection, export.

This module is the single place where a coordinate file becomes a database
record, so provenance and warnings are always produced the same way regardless
of which endpoint triggered the import.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import SUPPORTED_FORMATS, resolve_upload, sniff_format
from app.db.models import Ligand, Project, Structure
from app.services.chemistry.descriptors import LigandDescriptors, descriptors_from_file
from app.services.io.packet import build_packet
from app.services.io.parsers import ligand_summary, parse_structure_file
from app.services.io.types import ParsedStructure
from app.services.io.writers import export_structure
from app.services.provenance import record, software_identity, tool_versions
from app.services.store import ArtifactStore

LIGAND_FORMATS = {"sdf", "mol", "mol2", "xyz"}
MACROMOLECULE_FORMATS = {"pdb", "mmcif"}


@dataclass
class ImportOutcome:
    record: Structure
    parsed: ParsedStructure
    ligand: Ligand | None
    packet: dict[str, Any]


def infer_kind(parsed: ParsedStructure, fmt: str) -> str:
    """Classify an imported structure.

    ``complex`` is used when a macromolecule file also contains non-polymer
    residues (ligands, ions, waters excluded), which is the common case for a
    crystallographic structure with a bound ligand.
    """
    if fmt == "fasta":
        return "protein"
    if fmt == "pdbqt":
        return "receptor" if any(chain.kind == "polymer" for chain in parsed.chains) else "ligand"

    has_polymer = any(chain.kind == "polymer" for chain in parsed.chains)
    non_water_hetero = sum(
        1 for residue in parsed.residues if residue.is_hetero and not residue.is_water
    )
    molecules = sum(1 for residue in parsed.residues)

    if has_polymer:
        return "complex" if non_water_hetero else "protein"
    if fmt in LIGAND_FORMATS:
        return "library" if molecules > 1 else "ligand"
    return "ligand"


def _chains_payload(parsed: ParsedStructure) -> list[dict[str, Any]]:
    return [
        {
            "index": chain.index,
            "id": chain.id,
            "kind": chain.kind,
            "residueCount": chain.residue_count,
            "atomCount": sum(
                residue.atom_count
                for residue in parsed.residues
                if residue.chain_index == chain.index
            ),
            "sequence": parsed.sequences.get(chain.id, ""),
        }
        for chain in parsed.chains
    ]


def create_ligand_record(
    session: Session,
    *,
    project_id: str,
    structure: Structure,
    descriptors: LigandDescriptors,
    name: str | None = None,
) -> Ligand:
    ligand = Ligand(
        project_id=project_id,
        structure_id=structure.id,
        name=(name or structure.name)[:200],
        smiles=descriptors.smiles,
        inchi_key=descriptors.inchi_key,
        formula=descriptors.formula,
        molecular_weight=descriptors.molecular_weight,
        logp=descriptors.logp,
        tpsa=descriptors.tpsa,
        h_bond_donors=descriptors.h_bond_donors,
        h_bond_acceptors=descriptors.h_bond_acceptors,
        rotatable_bonds=descriptors.rotatable_bonds,
        formal_charge=descriptors.formal_charge,
        heavy_atoms=descriptors.heavy_atoms,
        aromatic_rings=descriptors.aromatic_rings,
        stereocenters=descriptors.stereocenters,
        descriptor_source="computed",
        valid=descriptors.valid,
        validation_messages=descriptors.messages,
        properties={
            "ringCount": descriptors.ring_count,
            "fractionCsp3": descriptors.fraction_csp3,
            "exactMass": descriptors.exact_mass,
            "stereocentersUnassigned": sum(
                1 for message in descriptors.messages if message.get("code") == "unassigned_stereocenters"
            ),
        },
        provenance={
            "tool": "RDKit",
            "toolVersion": tool_versions().get("rdkit"),
            "descriptorSource": "computed",
            "note": "Descriptors are computed from the imported 2D/3D structure, not measured.",
        },
    )
    session.add(ligand)
    return ligand


def _link_warnings(session: Session, structure: Structure, ligand: Ligand | None) -> None:
    if ligand is None or not structure.warnings:
        return
    existing = list(ligand.validation_messages or [])
    existing.extend(
        {"code": warning.get("code"), "severity": warning.get("severity"), "message": warning.get("message")}
        for warning in structure.warnings
    )
    ligand.validation_messages = existing


def import_structure(
    session: Session,
    *,
    project_id: str,
    data: bytes,
    filename: str,
    declared_format: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    source: str = "uploaded",
    store: ArtifactStore | None = None,
    compute_ligand_descriptors: bool = True,
    source_metadata: dict[str, Any] | None = None,
) -> ImportOutcome:
    """Validate, store, parse and register an imported structure."""
    settings = get_settings()
    store = store or ArtifactStore(settings)

    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")

    upload = resolve_upload(
        filename,
        declared_format,
        data[:4096],
        len(data),
        settings.max_upload_bytes,
    )
    artifact = store.store_bytes(project_id, "structures", upload.safe_name, data)

    parsed = parse_structure_file(
        artifact.absolute_path,
        upload.fmt,
        name=name or Path(upload.safe_name).stem,
        source=source,
    )
    resolved_kind = kind or infer_kind(parsed, upload.fmt)
    if kind and kind not in {"protein", "ligand", "complex", "receptor", "pose", "library"}:
        raise ValidationFailure(f"Unknown structure kind '{kind}'.")

    summary = parsed.summary()
    record_row = Structure(
        project_id=project_id,
        name=(name or Path(upload.safe_name).stem)[:200],
        kind=resolved_kind,
        format=upload.fmt,
        source=source,
        file_path=artifact.relative_path,
        file_sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        atoms_count=parsed.atom_count,
        residues_count=len(parsed.residues),
        chains_count=len(parsed.chains),
        chains=_chains_payload(parsed),
        elements=sorted(parsed.element_counts),
        warnings=[warning.as_dict() for warning in parsed.warnings],
        properties={
            **summary,
            "originalFilename": upload.original_filename,
            "parserFamily": SUPPORTED_FORMATS[upload.fmt][2],
            "formatLabel": SUPPORTED_FORMATS[upload.fmt][1],
            "sequences": parsed.sequences,
            "ligandSummary": ligand_summary(parsed) if resolved_kind in {"ligand", "library"} else None,
        },
        provenance={
            "software": software_identity(),
            "toolVersions": tool_versions(),
            "importedAt": None,
            "source": source,
            "format": upload.fmt,
            "originalFilename": upload.original_filename,
            "fileSha256": artifact.sha256,
            "declaredFormat": declared_format,
            "detectedFormat": sniff_format(data[:4096]) or upload.fmt,
            "byteSize": artifact.size_bytes,
            "secondaryStructureMethod": parsed.metadata.get("secondary_structure_method"),
            "bondSources": parsed.metadata.get("bond_sources", []),
            "sourceMetadata": source_metadata or {},
        },
    )
    session.add(record_row)
    session.flush()  # assign the primary key for provenance and ligand links

    ligand: Ligand | None = None
    if compute_ligand_descriptors and resolved_kind == "ligand" and upload.fmt in {
        "sdf",
        "mol",
        "mol2",
        "xyz",
    }:
        try:
            descriptors = descriptors_from_file(artifact.absolute_path, upload.fmt)
            ligand = create_ligand_record(
                session,
                project_id=project_id,
                structure=record_row,
                descriptors=descriptors,
                name=record_row.name,
            )
        except Exception as exc:  # noqa: BLE001 - descriptor failure must not lose the import
            record_row.warnings = [
                *list(record_row.warnings or []),
                {
                    "code": "descriptor_failure",
                    "severity": "warning",
                    "message": f"Ligand descriptors could not be computed: {exc}",
                },
            ]

    _link_warnings(session, record_row, ligand)

    record(
        session,
        action="import",
        entity_type="structure",
        entity_id=record_row.id,
        project_id=project_id,
        inputs={"filename": upload.original_filename, "format": upload.fmt, "source": source},
        outputs={"structureId": record_row.id, "sha256": artifact.sha256, "atoms": parsed.atom_count},
        params={
            "kind": resolved_kind,
            "declaredFormat": declared_format,
            "storedPath": artifact.relative_path,
        },
    )
    record_row.provenance = {**(record_row.provenance or {}), "importedAt": record_row.created_at.isoformat()}
    session.commit()
    session.refresh(record_row)

    packet = build_packet(
        parsed,
        structure_id=record_row.id,
        kind=resolved_kind,
        properties=record_row.properties,
        provenance=record_row.provenance,
    )
    return ImportOutcome(record=record_row, parsed=parsed, ligand=ligand, packet=packet)


def get_structure(session: Session, structure_id: str) -> Structure:
    record_row = session.get(Structure, structure_id)
    if record_row is None:
        raise NotFoundError(f"Structure '{structure_id}' does not exist.")
    return record_row


def load_parsed(session: Session, structure_id: str, *, store: ArtifactStore | None = None) -> tuple[Structure, ParsedStructure]:
    record_row = get_structure(session, structure_id)
    store = store or ArtifactStore()
    path = store.absolute(record_row.file_path)
    if not path.exists():
        raise NotFoundError(
            f"The stored coordinate file for structure '{structure_id}' is missing.",
            detail={"path": record_row.file_path},
        )
    parsed = parse_structure_file(
        path,
        record_row.format,
        name=record_row.name,
        source=record_row.source,
        enforce_atom_limit=False,
    )
    return record_row, parsed


def build_packet_for(session: Session, structure_id: str, *, store: ArtifactStore | None = None) -> dict[str, Any]:
    record_row, parsed = load_parsed(session, structure_id, store=store)
    return build_packet(
        parsed,
        structure_id=record_row.id,
        kind=record_row.kind,
        properties=record_row.properties,
        provenance=record_row.provenance,
    )


def export_structure_content(
    session: Session, structure_id: str, fmt: str, *, store: ArtifactStore | None = None
) -> tuple[str, str]:
    record_row, parsed = load_parsed(session, structure_id, store=store)
    content, filename = export_structure(parsed, fmt, name=record_row.name)
    record(
        session,
        action="export",
        entity_type="structure",
        entity_id=record_row.id,
        project_id=record_row.project_id,
        inputs={"structureId": structure_id},
        outputs={"format": fmt, "filename": filename, "bytes": len(content)},
        params={"requestedFormat": fmt},
    )
    session.commit()
    return content, filename


def structure_detail_payload(session: Session, structure_id: str) -> dict[str, Any]:
    record_row = get_structure(session, structure_id)
    ligand = session.scalars(select(Ligand).where(Ligand.structure_id == structure_id)).first()
    return {
        "id": record_row.id,
        "projectId": record_row.project_id,
        "name": record_row.name,
        "kind": record_row.kind,
        "format": record_row.format,
        "source": record_row.source,
        "fileSha256": record_row.file_sha256,
        "sizeBytes": record_row.size_bytes,
        "atomsCount": record_row.atoms_count,
        "residuesCount": record_row.residues_count,
        "chainsCount": record_row.chains_count,
        "createdAt": record_row.created_at,
        "warnings": record_row.warnings or [],
        "properties": record_row.properties or {},
        "provenance": record_row.provenance or {},
        "chains": record_row.chains or [],
        "ligand": (
            {
                "id": ligand.id,
                "projectId": ligand.project_id,
                "structureId": ligand.structure_id,
                "name": ligand.name,
                "smiles": ligand.smiles,
                "inchiKey": ligand.inchi_key,
                "formula": ligand.formula,
                "molecularWeight": ligand.molecular_weight,
                "logp": ligand.logp,
                "tpsa": ligand.tpsa,
                "hBondDonors": ligand.h_bond_donors,
                "hBondAcceptors": ligand.h_bond_acceptors,
                "rotatableBonds": ligand.rotatable_bonds,
                "formalCharge": ligand.formal_charge,
                "heavyAtoms": ligand.heavy_atoms,
                "aromaticRings": ligand.aromatic_rings,
                "stereocenters": ligand.stereocenters,
                "descriptorSource": ligand.descriptor_source,
                "valid": ligand.valid,
                "validationMessages": ligand.validation_messages or [],
                "createdAt": ligand.created_at,
            }
            if ligand
            else None
        ),
    }


def delete_structure(session: Session, structure_id: str, *, store: ArtifactStore | None = None) -> None:
    store = store or ArtifactStore()
    record_row = get_structure(session, structure_id)
    for structure in session.scalars(
        select(Structure).where(Structure.parent_structure_id == structure_id)
    ).all():
        structure.parent_structure_id = None
    file_path = record_row.file_path
    session.delete(record_row)
    session.commit()
    with contextlib.suppress(Exception):
        # A missing or already-deleted artefact must not break the operation.
        store.delete_artifact(file_path)
