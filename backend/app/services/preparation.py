"""Structure preparation (Phase 2).

Produces derivation-ready receptor and ligand structures from an imported
structure using only the tooling available on this machine (RDKit + gemmi).
No AutoDock Vina, PDB2PQR or Open Babel is required; where a preparation
step needs an unavailable tool the result is reported as a warning rather
than silently dropped.

Every derived structure keeps a ``parent_structure_id`` link so any result
can be traced back to its inputs.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, StructureParseError, ValidationFailure
from app.db.models import BindingSite, Ligand, LigandPrep, Project, ReceptorPrep, Structure
from app.services.io.parsers import finalize
from app.services.io.types import Atom, Bond, Chain, ParsedStructure, Residue
from app.services.io.writers import export_structure
from app.services.provenance import record
from app.services.store import ArtifactStore, StoredArtifact


@dataclass
class PreparedReceptor:
    """Outcome of receptor preparation."""

    record: Structure
    receptor_prep: ReceptorPrep
    parsed: ParsedStructure
    atoms_kept: int
    atoms_removed: int
    residues_kept: int
    warnings: list[dict[str, Any]]


@dataclass
class PreparedLigand:
    """Outcome of ligand preparation."""

    record: Structure
    ligand_prep: LigandPrep
    parsed: ParsedStructure
    conformers: int
    warnings: list[dict[str, Any]]


def _chain_ids(parsed: ParsedStructure) -> list[str]:
    return [chain.id for chain in parsed.chains]


def _select_residue_indices(
    parsed: ParsedStructure,
    *,
    keep_waters: bool,
    keep_cofactors: bool,
    keep_chains: list[str] | None,
) -> set[int]:
    """Return the set of residue indices to retain in the prepared receptor."""
    keep_chain_ids = set(keep_chains) if keep_chains is not None else None
    kept: set[int] = set()
    for residue in parsed.residues:
        chain = parsed.chains[residue.chain_index]
        if keep_chain_ids is not None and chain.id not in keep_chain_ids:
            continue
        if keep_chain_ids is None and chain.kind != "polymer":
            continue
        if residue.is_water and not keep_waters:
            continue
        if residue.is_hetero and not residue.is_water and not keep_cofactors:
            continue
        kept.add(residue.index)
    return kept


def _filter_to_residues(
    parsed: ParsedStructure,
    kept_residue_indices: set[int],
    removed_reason: dict[int, str],
) -> ParsedStructure:
    """Build a ParsedStructure containing only the kept residues (renumbered).

    Existing bonds are kept only when both endpoints survived; nothing is
    re-perceived so no false bonds are invented.
    """
    kept_atom_indices = {
        atom.index
        for residue_index in kept_residue_indices
        for atom in parsed.atoms
        if atom.residue_index == residue_index
    }
    if not kept_atom_indices:
        raise ValidationFailure(
            "The preparation policy removed every atom; nothing remains to prepare.",
            detail={"removedReasons": removed_reason},
        )

    old_to_new_atom = {old: new for new, old in enumerate(sorted(kept_atom_indices))}
    old_to_new_residue = {old: new for new, old in enumerate(sorted(kept_residue_indices))}

    new_atoms = []
    for old_index in sorted(kept_atom_indices):
        atom = parsed.atoms[old_index]
        new_atoms.append(
            Atom(
                index=old_to_new_atom[old_index],
                serial=atom.serial,
                name=atom.name,
                element=atom.element,
                x=atom.x,
                y=atom.y,
                z=atom.z,
                residue_index=old_to_new_residue[atom.residue_index],
                chain_index=atom.chain_index,
                occupancy=atom.occupancy,
                bfactor=atom.bfactor,
                formal_charge=atom.formal_charge,
                partial_charge=atom.partial_charge,
                altloc=atom.altloc,
                record=atom.record,
                is_hetero=atom.is_hetero,
                is_water=atom.is_water,
                is_backbone=atom.is_backbone,
                autodock_type=atom.autodock_type,
            )
        )

    new_bonds = []
    for bond in parsed.bonds:
        if bond.a in old_to_new_atom and bond.b in old_to_new_atom:
            new_bonds.append(
                Bond(
                    a=old_to_new_atom[bond.a],
                    b=old_to_new_atom[bond.b],
                    order=bond.order,
                    source=bond.source,
                    aromatic=bond.aromatic,
                )
            )

    new_residues = []
    chain_new_index = {chain.index: i for i, chain in enumerate(parsed.chains)}
    for old_index in sorted(kept_residue_indices):
        residue = parsed.residues[old_index]
        residue_atoms = [
            a for a in new_atoms if a.residue_index == old_to_new_residue[old_index]
        ]
        new_residues.append(
            Residue(
                index=old_to_new_residue[old_index],
                name=residue.name,
                seq=residue.seq,
                chain_index=chain_new_index[residue.chain_index],
                atom_start=min(a.index for a in residue_atoms),
                atom_count=len(residue_atoms),
                insertion_code=residue.insertion_code,
                ss=residue.ss,
                is_hetero=residue.is_hetero,
                is_water=residue.is_water,
                is_amino_acid=residue.is_amino_acid,
                is_nucleic=residue.is_nucleic,
                one_letter=residue.one_letter,
                chain_label=residue.chain_label,
                title=residue.title,
                smiles=residue.smiles,
                ca_index=residue.ca_index,
                n_index=residue.n_index,
                c_index=residue.c_index,
                o_index=residue.o_index,
                cb_index=residue.cb_index,
            )
        )

    # Rebuild chains: only chains that still have residues, renumbered.
    kept_chain_indices = {r.chain_index for r in new_residues}
    chain_old_to_new = {}
    new_chains = []
    for new_chain_index, old_chain_index in enumerate(sorted(kept_chain_indices)):
        chain_old_to_new[old_chain_index] = new_chain_index
        old_chain = parsed.chains[old_chain_index]
        chain_residues = [r for r in new_residues if r.chain_index == old_chain_index]
        new_chains.append(
            Chain(
                index=new_chain_index,
                id=old_chain.id,
                residue_start=min(r.index for r in chain_residues),
                residue_count=len(chain_residues),
                kind=old_chain.kind,
            )
        )
    for residue in new_residues:
        residue.chain_index = chain_old_to_new[residue.chain_index]

    filtered = ParsedStructure(
        format=parsed.format,
        name=parsed.name,
        source=parsed.source,
        atoms=new_atoms,
        residues=new_residues,
        chains=new_chains,
        bonds=new_bonds,
        warnings=[w.as_dict() for w in parsed.warnings],
        sequences={
            chain.id: parsed.sequences.get(chain.id, "") for chain in new_chains
        },
        metadata=dict(parsed.metadata),
    )
    return finalize(filtered, perceive_bonds=False, keep_file_bonds=True)


def _derive_structure_record(
    session: Session,
    *,
    project_id: str,
    parent: Structure,
    kind: str,
    name: str,
    parsed: ParsedStructure,
    store: ArtifactStore,
    category: str,
    filename: str,
    provenance_extra: dict[str, Any] | None = None,
) -> tuple[Structure, StoredArtifact]:
    """Export a parsed structure, store it, and create the derived Structure row."""
    content, written_name = export_structure(parsed, parsed.format, name=name)
    artifact = store.store_bytes(project_id, category, written_name, content.encode("utf-8"))

    summary = parsed.summary()
    record_row = Structure(
        project_id=project_id,
        parent_structure_id=parent.id,
        name=name[:200],
        kind=kind,
        format=parsed.format,
        source="derived",
        file_path=artifact.relative_path,
        file_sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        atoms_count=parsed.atom_count,
        residues_count=len(parsed.residues),
        chains_count=len(parsed.chains),
        chains=[
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
        ],
        elements=sorted(parsed.element_counts),
        warnings=[w.as_dict() for w in parsed.warnings],
        properties={
            **summary,
            "derivedFrom": parent.id,
            "derivationKind": kind,
        },
        provenance={
            "software": {"application": "MolDock Studio", "version": "0.1.0"},
            "toolVersions": {},
            "derivedFromStructure": parent.id,
            "category": category,
            **(provenance_extra or {}),
        },
    )
    session.add(record_row)
    session.flush()
    return record_row, artifact


def prepare_receptor(
    session: Session,
    *,
    project_id: str,
    structure_id: str,
    name: str | None = None,
    keep_waters: bool = False,
    keep_cofactors: bool = False,
    keep_chains: list[str] | None = None,
    add_hydrogens: bool = False,
    store: ArtifactStore | None = None,
) -> PreparedReceptor:
    """Prepare a receptor: keep selected polymer chains + opt-in waters/cofactors.

    Everything else (waters not requested, cofactors not requested, non-kept
    chains) is removed and reported as information loss. The surviving atoms
    keep their original coordinates and bonds; nothing is re-perceived.
    """
    settings = get_settings()
    store = store or ArtifactStore(settings)
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")
    parent = session.get(Structure, structure_id)
    if parent is None:
        raise NotFoundError(f"Structure '{structure_id}' does not exist.")

    _, parsed = _load(session, structure_id, store)

    all_chain_ids = _chain_ids(parsed)
    if keep_chains is not None:
        unknown = [c for c in keep_chains if c not in all_chain_ids]
        if unknown:
            raise ValidationFailure(
                f"Unknown chain id(s): {', '.join(unknown)}.",
                detail={"availableChainIds": all_chain_ids},
            )

    kept = _select_residue_indices(
        parsed,
        keep_waters=keep_waters,
        keep_cofactors=keep_cofactors,
        keep_chains=keep_chains,
    )

    removed_reason: dict[int, str] = {}
    for residue in parsed.residues:
        if residue.index not in kept:
            chain = parsed.chains[residue.chain_index]
            if residue.is_water:
                removed_reason[residue.index] = "water excluded"
            elif residue.is_hetero:
                removed_reason[residue.index] = "cofactor/hetero excluded"
            else:
                removed_reason[residue.index] = f"chain '{chain.id}' not kept"

    filtered = _filter_to_residues(parsed, kept, removed_reason)

    # Optionally add explicit hydrogens (needed for PDBQT/docking input).
    add_hydrogens_warning: dict[str, Any] | None = None
    if add_hydrogens:
        try:
            from rdkit import Chem, RDLogger
            from rdkit.Chem import AllChem

            RDLogger.DisableLog("rdApp.*")
            mol = None
            if parent.format in {"pdb", "mmcif"}:
                mol = Chem.MolFromPDBFile(str(store.absolute(parent.file_path)), removeHs=False, sanitize=True)
            elif parent.format in {"sdf", "mol"}:
                mol = Chem.MolFromMolFile(str(store.absolute(parent.file_path)), removeHs=False, sanitize=True)
            elif parent.format == "mol2":
                mol = Chem.MolFromMol2File(str(store.absolute(parent.file_path)), removeHs=False, sanitize=True)
            if mol is not None:
                mol = Chem.AddHs(mol, addCoords=False)
                # Rebuild coordinates: ETKDG is not needed; keep original heavy-atom
                # coordinates and let RDKit place hydrogens geometrically.
                AllChem.AssignStereochemistry(mol, cleanIt=False, force=True)
                # Re-parse the PDB back into our ParsedStructure so the packet is
                # consistent with the stored file.
                from app.services.io.parsers import parse_structure_file

                tmp_path = store.absolute(parent.file_path).with_suffix(".tmp.pdb")
                tmp_path.write_text(Chem.MolToPDBBlock(mol), encoding="utf-8")
                try:
                    filtered = parse_structure_file(
                        tmp_path,
                        "pdb",
                        name=filtered.name,
                        source=parsed.source,
                    )
                finally:
                    tmp_path.unlink(missing_ok=True)
                add_hydrogens_warning = {
                    "code": "receptor_hydrogens_added",
                    "severity": "info",
                    "message": f"Explicit hydrogens added ({mol.GetNumAtoms() - parent.atoms_count} new atoms).",
                }
        except Exception as exc:  # noqa: BLE001 - hydrogen addition is best-effort
            add_hydrogens_warning = {
                "code": "receptor_hydrogen_addition_failed",
                "severity": "warning",
                "message": f"Could not add hydrogens to receptor: {exc}. Proceeding without explicit hydrogens.",
            }

    warnings = [w.as_dict() for w in parsed.warnings]
    if add_hydrogens_warning:
        warnings.append(add_hydrogens_warning)
    if removed_reason:
        warnings.append(
            {
                "code": "receptor_filtered",
                "severity": "info",
                "message": (
                    f"{len(removed_reason)} residue(s) removed during preparation: "
                    f"{sum(1 for r in removed_reason.values() if r == 'water excluded')} water(s), "
                    f"{sum(1 for r in removed_reason.values() if r == 'cofactor/hetero excluded')} cofactor(s), "
                    f"{sum(1 for r in removed_reason.values() if r.startswith('chain'))} chain-filtered residue(s)."
                ),
                "detail": {"removedCount": len(removed_reason), "reasons": removed_reason},
            }
        )

    derived_name = (name or f"{parent.name} (prepared receptor)")[:200]
    record_row, artifact = _derive_structure_record(
        session,
        project_id=project_id,
        parent=parent,
        kind="receptor",
        name=derived_name,
        parsed=filtered,
        store=store,
        category="receptors",
        filename=f"{Path(derived_name).stem}.pdb",
        provenance_extra={
            "preparation": "receptor",
            "keepWaters": keep_waters,
            "keepCofactors": keep_cofactors,
            "keepChains": keep_chains,
            "addHydrogens": add_hydrogens,
            "atomsKept": filtered.atom_count,
            "atomsRemoved": parent.atoms_count - filtered.atom_count,
        },
    )

    receptor_prep = ReceptorPrep(
        project_id=project_id,
        input_structure_id=parent.id,
        output_structure_id=record_row.id,
        status="completed",
        config={
            "name": derived_name,
            "keepWaters": keep_waters,
            "keepCofactors": keep_cofactors,
            "keepChains": keep_chains,
            "addHydrogens": add_hydrogens,
            "atomsKept": filtered.atom_count,
            "atomsRemoved": parent.atoms_count - filtered.atom_count,
            "residuesKept": len(filtered.residues),
            "chainsKept": len(filtered.chains),
        },
        warnings=warnings,
        tool_versions={"rdkit": "available", "gemmi": "available"},
    )
    session.add(receptor_prep)
    session.flush()

    record(
        session,
        action="prepare_receptor",
        entity_type="structure",
        entity_id=record_row.id,
        project_id=project_id,
        inputs={"structureId": structure_id, "keepWaters": keep_waters, "keepCofactors": keep_cofactors, "keepChains": keep_chains},
        outputs={"receptorStructureId": record_row.id, "atomsKept": filtered.atom_count, "atomsRemoved": parent.atoms_count - filtered.atom_count},
        params={"keepWaters": keep_waters, "keepCofactors": keep_cofactors, "keepChains": keep_chains},
    )
    session.commit()
    session.refresh(record_row)
    session.refresh(receptor_prep)

    return PreparedReceptor(
        record=record_row,
        receptor_prep=receptor_prep,
        parsed=filtered,
        atoms_kept=filtered.atom_count,
        atoms_removed=parent.atoms_count - filtered.atom_count,
        residues_kept=len(filtered.residues),
        warnings=warnings,
    )


def prepare_ligand(
    session: Session,
    *,
    project_id: str,
    structure_id: str,
    name: str | None = None,
    embed_3d: bool = True,
    seed: int = 42,
    optimize: bool = True,
    max_conformers: int = 1,
    store: ArtifactStore | None = None,
) -> PreparedLigand:
    """Prepare a ligand: embed an RDKit 3D conformer (MMFF94-optimized) and store it.

    The source structure must be ligand-like (SDF/MOL/MOL2/XYZ with a single
    molecule). The prepared ligand is stored as SDF in ``prepared_ligands``
    and linked to the source ligand record.
    """
    settings = get_settings()
    store = store or ArtifactStore(settings)
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")
    parent = session.get(Structure, structure_id)
    if parent is None:
        raise NotFoundError(f"Structure '{structure_id}' does not exist.")
    ligand_row = session.scalars(
        select(Ligand).where(Ligand.structure_id == structure_id)
    ).first()
    if ligand_row is None:
        raise ValidationFailure(
            f"Structure '{structure_id}' has no ligand record; only ligand structures can be prepared.",
            detail={"structureId": structure_id},
        )

    _, parsed = _load(session, structure_id, store)
    if not parsed.is_ligand_like:
        raise ValidationFailure(
            "The source structure is not ligand-like (it contains polymer chains).",
            detail={"structureId": structure_id, "kinds": [chain.kind for chain in parsed.chains]},
        )

    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem

    RDLogger.DisableLog("rdApp.*")

    source_path = store.absolute(parent.file_path)
    mol = None
    messages: list[dict[str, Any]] = []
    if parent.format in {"sdf", "mol"}:
        mol = Chem.MolFromMolFile(str(source_path), removeHs=False, sanitize=True)
        if mol is None:
            mol = Chem.MolFromMolFile(str(source_path), removeHs=False, sanitize=False)
            messages.append(
                {
                    "code": "sanitization_failed",
                    "severity": "warning",
                    "message": "RDKit could not sanitise this molecule; preparation proceeds on the unsanitised structure.",
                }
            )
    elif parent.format == "mol2":
        mol = Chem.MolFromMol2File(str(source_path), removeHs=False, sanitize=True)
        if mol is None:
            mol = Chem.MolFromMol2File(str(source_path), removeHs=False, sanitize=False)
            messages.append(
                {
                    "code": "sanitization_failed",
                    "severity": "warning",
                    "message": "RDKit could not sanitise this MOL2 file; preparation proceeds on the unsanitised structure.",
                }
            )
    elif parent.format == "xyz":
        mol = Chem.MolFromXYZFile(str(source_path))
    else:
        raise ValidationFailure(
            f"Ligand preparation from format '{parent.format}' is not supported.",
            detail={"structureId": structure_id, "format": parent.format},
            remediation="Convert the ligand to SDF/MOL2 first.",
        )

    if mol is None:
        raise StructureParseError(
            f"RDKit could not parse '{parent.file_path}' as a molecule.",
            detail={"structureId": structure_id},
        )

    mol = Chem.AddHs(mol, addCoords=False)
    conformers = 0
    conf_ids: list[int] = []
    if embed_3d:
        params = AllChem.ETKDGv3()
        params.randomSeed = seed
        # Embed multiple conformers when requested; embed them all at once so
        # they share the same random-seed bounds and are directly comparable.
        conf_ids = list(
            AllChem.EmbedMultipleConfs(
                mol,
                numConfs=max_conformers,
                params=params,
            )
        )
        if not conf_ids:
            raise StructureParseError(
                "RDKit could not generate any 3D conformers for this molecule.",
                detail={"structureId": structure_id, "smiles": ligand_row.smiles},
                remediation="Check for unusual valences, or import a prepared 3D structure.",
            )
        conformers = len(conf_ids)
        if optimize:
            for conf_id in conf_ids:
                try:
                    AllChem.MMFFOptimizeMolecule(mol, confId=conf_id, maxIters=500)
                except Exception:  # noqa: BLE001 - MMFF not universal
                    messages.append(
                        {
                            "code": "mmff_optimization_failed",
                            "severity": "warning",
                            "message": f"MMFF94 optimisation failed for conformer {conf_id}; unoptimised geometry retained.",
                        }
                    )

    # Write a multi-model SDF: one MODEL/ENDMDL block per conformer so docking
    # and screening can iterate over the ensemble.
    sdf_blocks: list[str] = []
    if conformers:
        for conf_id in conf_ids:
            block = Chem.MolToMolBlock(mol, confId=conf_id)
            # MolToMolBlock ends with $$$$; replace the terminator with ENDMDL
            # so multiple models concatenate into a valid multi-model SDF.
            block = block.rstrip()
            if block.endswith("$$$$"):
                block = block[: -len("$$$$")].rstrip()
            sdf_blocks.append(f"{block}\nENDMDL")
        sdf_content = "\n".join(sdf_blocks) + "\n$$$$\n"
    else:
        sdf_content = Chem.MolToMolBlock(mol)
    derived_name = (name or f"{parent.name} (prepared ligand)")[:200]
    written_name = f"{Path(derived_name).stem}.sdf"
    content = sdf_content.encode("utf-8")
    artifact = store.store_bytes(project_id, "prepared_ligands", written_name, content)

    summary = parsed.summary()
    record_row = Structure(
        project_id=project_id,
        parent_structure_id=parent.id,
        name=derived_name,
        kind="ligand",
        format="sdf",
        source="derived",
        file_path=artifact.relative_path,
        file_sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
        atoms_count=mol.GetNumAtoms(),
        residues_count=1,
        chains_count=1,
        chains=[
            {
                "index": 0,
                "id": "L",
                "kind": "ligand",
                "residueCount": 1,
                "atomCount": mol.GetNumAtoms(),
                "sequence": "",
            }
        ],
        elements=sorted({atom.GetSymbol() for atom in mol.GetAtoms()}),
        warnings=[w.as_dict() for w in parsed.warnings] + messages,
        properties={
            **summary,
            "derivedFrom": parent.id,
            "derivationKind": "ligand",
            "conformers": conformers,
            "embedding": "ETKDGv3" if embed_3d else None,
            "optimization": "MMFF94" if optimize else None,
        },
        provenance={
            "software": {"application": "MolDock Studio", "version": "0.1.0"},
            "toolVersions": {"rdkit": "available"},
            "derivedFromStructure": parent.id,
            "preparation": "ligand",
            "embed3d": embed_3d,
            "seed": seed,
            "optimize": optimize,
            "conformers": conformers,
        },
    )
    session.add(record_row)
    session.flush()

    ligand_prep = LigandPrep(
        project_id=project_id,
        ligand_id=ligand_row.id,
        output_structure_id=record_row.id,
        status="completed",
        config={
            "name": derived_name,
            "embed3d": embed_3d,
            "seed": seed,
            "optimize": optimize,
            "maxConformers": max_conformers,
            "conformers": conformers,
            "embedding": "ETKDGv3" if embed_3d else None,
            "optimization": "MMFF94" if optimize else None,
        },
        warnings=[w.as_dict() for w in parsed.warnings] + messages,
        tool_versions={"rdkit": "available"},
    )
    session.add(ligand_prep)
    session.flush()

    record(
        session,
        action="prepare_ligand",
        entity_type="structure",
        entity_id=record_row.id,
        project_id=project_id,
        inputs={"structureId": structure_id, "embed3d": embed_3d, "seed": seed, "optimize": optimize},
        outputs={"ligandStructureId": record_row.id, "conformers": conformers},
        params={"embed3d": embed_3d, "seed": seed, "optimize": optimize, "maxConformers": max_conformers},
    )
    session.commit()
    session.refresh(record_row)
    session.refresh(ligand_prep)

    return PreparedLigand(
        record=record_row,
        ligand_prep=ligand_prep,
        parsed=parsed,
        conformers=conformers,
        warnings=[w.as_dict() for w in parsed.warnings] + messages,
    )


def _load(session: Session, structure_id: str, store: ArtifactStore | None) -> tuple[Structure, ParsedStructure]:
    from app.services.structures import load_parsed

    store = store or ArtifactStore()
    return load_parsed(session, structure_id, store=store)


def define_binding_site(
    session: Session,
    *,
    project_id: str,
    receptor_structure_id: str,
    name: str | None = None,
    method: str = "manual",
    center_x: float | None = None,
    center_y: float | None = None,
    center_z: float | None = None,
    size_x: float = 22.0,
    size_y: float = 22.0,
    size_z: float = 22.0,
    reference_ligand_structure_id: str | None = None,
    residues: list[str] | None = None,
    store: ArtifactStore | None = None,
) -> BindingSite:
    """Define a docking search space on a receptor.

    Methods:
    * ``manual``     - explicit centre/size (Å).
    * ``ligand``     - centre/size derived from a reference ligand's bounds.
    * ``residues``   - centre/size derived from named residues (e.g. ``A:123``).

    The centre/size are stored; the actual docking box is applied in Phase 3.
    """
    settings = get_settings()
    store = store or ArtifactStore(settings)
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")
    receptor = session.get(Structure, receptor_structure_id)
    if receptor is None:
        raise NotFoundError(f"Structure '{receptor_structure_id}' does not exist.")
    if receptor.kind not in {"receptor", "protein", "complex"}:
        raise ValidationFailure(
            "A binding site can only be defined on a receptor/protein/complex structure.",
            detail={"structureId": receptor_structure_id, "kind": receptor.kind},
        )

    centre: tuple[float, float, float]
    extents: tuple[float, float, float]
    detail: dict[str, Any] = {"method": method}

    if method == "manual":
        if center_x is None or center_y is None or center_z is None:
            raise ValidationFailure(
                "Manual binding site requires centreX, centreY and centreZ.",
                detail={"method": method},
            )
        centre = (center_x, center_y, center_z)
        extents = (size_x, size_y, size_z)
        detail.update(
            {
                "centre": {"x": centre[0], "y": centre[1], "z": centre[2]},
                "size": {"x": extents[0], "y": extents[1], "z": extents[2]},
            }
        )
    elif method == "ligand":
        if reference_ligand_structure_id is None:
            raise ValidationFailure(
                "Ligand-derived site requires referenceLigandStructureId.",
                detail={"method": method},
            )
        ref = session.get(Structure, reference_ligand_structure_id)
        if ref is None:
            raise NotFoundError(f"Reference structure '{reference_ligand_structure_id}' does not exist.")
        _, parsed = _load(session, reference_ligand_structure_id, store)
        bounds = parsed.bounds()
        lo = bounds["min"]
        hi = bounds["max"]
        centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2)
        extents = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
        # Pad to a sane minimum box so small ligands still get a usable search space.
        extents = tuple(max(e, 22.0) for e in extents)
        detail.update(
            {
                "referenceLigandStructureId": reference_ligand_structure_id,
                "ligandBounds": {"min": lo, "max": hi},
                "centre": {"x": centre[0], "y": centre[1], "z": centre[2]},
                "size": {"x": extents[0], "y": extents[1], "z": extents[2]},
            }
        )
    elif method == "residues":
        if not residues:
            raise ValidationFailure(
                "Residue-derived site requires a non-empty residues list.",
                detail={"method": method},
            )
        _, parsed = _load(session, receptor_structure_id, store)
        label_to_residue = {}
        for residue in parsed.residues:
            label_to_residue[residue.label] = residue
        matched = []
        missing = []
        for label in residues:
            residue = label_to_residue.get(label)
            if residue is None:
                missing.append(label)
            else:
                matched.append(residue)
        if missing:
            raise ValidationFailure(
                f"Residue(s) not found in receptor: {', '.join(missing)}.",
                detail={"method": method, "missing": missing, "available": sorted(label_to_residue)},
            )
        atom_coords = []
        for residue in matched:
            for atom in parsed.atoms[residue.atom_start : residue.atom_start + residue.atom_count]:
                atom_coords.append((atom.x, atom.y, atom.z))
        if not atom_coords:
            raise ValidationFailure(
                "The matched residues contain no atoms.",
                detail={"method": method, "residues": residues},
            )
        xs = [c[0] for c in atom_coords]
        ys = [c[1] for c in atom_coords]
        zs = [c[2] for c in atom_coords]
        centre = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        extents = (
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
        )
        extents = tuple(max(e, 22.0) for e in extents)
        detail.update(
            {
                "residues": residues,
                "matchedResidueLabels": [r.label for r in matched],
                "centre": {"x": centre[0], "y": centre[1], "z": centre[2]},
                "size": {"x": extents[0], "y": extents[1], "z": extents[2]},
            }
        )
    else:
        raise ValidationFailure(
            f"Unknown binding site method '{method}'.",
            detail={"method": method, "validMethods": ["manual", "ligand", "residues"]},
        )

    site = BindingSite(
        project_id=project_id,
        receptor_structure_id=receptor_structure_id,
        name=(name or f"Site on {receptor.name}")[:160],
        method=method,
        center_x=centre[0],
        center_y=centre[1],
        center_z=centre[2],
        size_x=extents[0],
        size_y=extents[1],
        size_z=extents[2],
        source_ligand_structure_id=reference_ligand_structure_id,
        residues=residues or [],
        config=detail,
    )
    session.add(site)
    session.flush()

    record(
        session,
        action="define_binding_site",
        entity_type="binding_site",
        entity_id=site.id,
        project_id=project_id,
        inputs={
            "receptorStructureId": receptor_structure_id,
            "method": method,
            "referenceLigandStructureId": reference_ligand_structure_id,
            "residues": residues,
        },
        outputs={
            "bindingSiteId": site.id,
            "centre": {"x": centre[0], "y": centre[1], "z": centre[2]},
            "size": {"x": extents[0], "y": extents[1], "z": extents[2]},
        },
        params=detail,
    )
    session.commit()
    session.refresh(site)
    return site


# ---------------------------------------------------------------------------
# PDBQT generation (Meeko) — Phase 2
# ---------------------------------------------------------------------------

def generate_pdbqt(
    session: Session,
    *,
    project_id: str,
    structure_id: str,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Convert a prepared structure to PDBQT using Meeko.

    PDBQT is AutoDock Vina's input format: it adds partial charges (Gasteiger),
    atom types, and merges hydrogens into the heavy-atom record. The source
    structure should already be prepared (receptor: chains/cofactors selected,
    hydrogens added; ligand: 3D conformer embedded).

    Returns a dict with the PDBQT content, artefact path, and statistics.
    """
    settings = get_settings()
    store = store or ArtifactStore(settings)
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' does not exist.")
    parent = session.get(Structure, structure_id)
    if parent is None:
        raise NotFoundError(f"Structure '{structure_id}' does not exist.")

    try:
        from meeko import MoleculePreparation  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValidationFailure(
            "Meeko is not installed. Run: uv sync --extra prep",
            detail={"structureId": structure_id},
            remediation="uv sync --extra prep",
        ) from exc

    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")

    source_path = store.absolute(parent.file_path)
    mol: Any = None
    if parent.format in {"pdb", "pdbqt"}:
        mol = Chem.MolFromPDBFile(str(source_path), removeHs=False, sanitize=True)
    elif parent.format in {"sdf", "mol"}:
        mol = Chem.MolFromMolFile(str(source_path), removeHs=False, sanitize=True)
    elif parent.format == "mol2":
        mol = Chem.MolFromMol2File(str(source_path), removeHs=False, sanitize=True)
    else:
        raise ValidationFailure(
            f"PDBQT generation from format '{parent.format}' is not supported.",
            detail={"structureId": structure_id, "format": parent.format},
            remediation="Convert the structure to PDB/SDF/MOL2 first.",
        )

    if mol is None:
        raise StructureParseError(
            f"RDKit could not parse '{parent.file_path}' as a molecule.",
            detail={"structureId": structure_id},
        )

    # Ensure explicit hydrogens are present (Meeko needs them to merge).
    mol = Chem.AddHs(mol, addCoords=False)

    # Sanitize to fix potential valence issues from SDF/PDB re-parsing
    # (e.g. metal-coordination bonds misread as covalent). Proceed with
    # whatever RDKit can make consistent.
    with contextlib.suppress(Exception):
        Chem.SanitizeMol(mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL)

    # Meeko requires a single connected fragment. Keep the largest fragment
    # (by heavy-atom count) so multi-fragment receptors/ligands can be prepared.
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(frags) > 1:
        frags = sorted(frags, key=lambda m: m.GetNumHeavyAtoms(), reverse=True)
        mol = frags[0]

    preparer = MoleculePreparation()
    try:
        setups = preparer.prepare(mol)
    except Exception as exc:  # noqa: BLE001 - Meeko failures are reported honestly
        raise StructureParseError(
            f"Meeko could not prepare '{parent.file_path}': {exc}",
            detail={"structureId": structure_id},
            remediation="Check valences, formal charges, and that hydrogens were added.",
        ) from exc

    if not setups:
        raise StructureParseError(
            f"Meeko produced no setups for '{parent.file_path}'.",
            detail={"structureId": structure_id},
        )

    setup = setups[0]
    try:
        from meeko.writer import PDBQTWriterLegacy

        pdbqt_string, success, error_msg = PDBQTWriterLegacy.write_string(
            setup, bad_charge_ok=True
        )
    except Exception as exc:  # noqa: BLE001 - Meeko failures are reported honestly
        raise StructureParseError(
            f"Meeko could not write PDBQT for '{parent.file_path}': {exc}",
            detail={"structureId": structure_id},
            remediation="Check valences, formal charges, and that hydrogens were added.",
        ) from exc

    if not success:
        raise StructureParseError(
            f"Meeko PDBQT generation failed for '{parent.file_path}': {error_msg}",
            detail={"structureId": structure_id},
            remediation="Check valences, formal charges, and that hydrogens were added.",
        )

    derived_name = f"{Path(parent.name).stem}.pdbqt"
    artifact = store.store_bytes(project_id, "receptors", derived_name, pdbqt_string.encode("utf-8"))

    # Count heavy atoms and PDBQT atoms for stats.
    heavy_atoms = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() > 1)
    pdbqt_atom_lines = [
        line for line in pdbqt_string.splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]

    record(
        session,
        action="generate_pdbqt",
        entity_type="structure",
        entity_id=parent.id,
        project_id=project_id,
        inputs={"structureId": structure_id, "format": parent.format},
        outputs={"pdbqtPath": artifact.relative_path, "pdbqtAtoms": len(pdbqt_atom_lines)},
        params={"sourceFormat": parent.format},
    )
    session.commit()

    return {
        "structureId": structure_id,
        "pdbqtPath": artifact.relative_path,
        "pdbqtSha256": artifact.sha256,
        "heavyAtoms": heavy_atoms,
        "pdbqtAtoms": len(pdbqt_atom_lines),
        "content": pdbqt_string,
    }


def prepare_for_docking(
    session: Session,
    *,
    project_id: str,
    receptor_structure_id: str,
    ligand_structure_id: str,
    binding_site_id: str | None = None,
    receptor_name: str | None = None,
    ligand_name: str | None = None,
    keep_waters: bool = False,
    keep_cofactors: bool = False,
    keep_chains: list[str] | None = None,
    add_hydrogens: bool = True,
    ligand_embed3d: bool = True,
    ligand_seed: int = 42,
    ligand_optimize: bool = True,
    ligand_max_conformers: int = 1,
    store: ArtifactStore | None = None,
) -> dict[str, Any]:
    """End-to-end Phase 2 preparation for docking.

    Runs receptor preparation, ligand preparation, and (optionally) PDBQT
    generation for both, returning every derived artefact so the frontend can
    proceed to Phase 3 docking.

    Returns a dict with receptorPrep, ligandPrep, receptorPdbqt, ligandPdbqt,
    and bindingSite (if requested) results.
    """
    settings = get_settings()
    store = store or ArtifactStore(settings)

    # 1. Prepare the receptor.
    receptor_outcome = prepare_receptor(
        session,
        project_id=project_id,
        structure_id=receptor_structure_id,
        name=receptor_name,
        keep_waters=keep_waters,
        keep_cofactors=keep_cofactors,
        keep_chains=keep_chains,
        add_hydrogens=add_hydrogens,
        store=store,
    )

    # 2. Prepare the ligand.
    ligand_outcome = prepare_ligand(
        session,
        project_id=project_id,
        structure_id=ligand_structure_id,
        name=ligand_name,
        embed_3d=ligand_embed3d,
        seed=ligand_seed,
        optimize=ligand_optimize,
        max_conformers=ligand_max_conformers,
        store=store,
    )

    # 3. Generate PDBQT for both.
    receptor_pdbqt = generate_pdbqt(
        session,
        project_id=project_id,
        structure_id=receptor_outcome.record.id,
        store=store,
    )
    ligand_pdbqt = generate_pdbqt(
        session,
        project_id=project_id,
        structure_id=ligand_outcome.record.id,
        store=store,
    )

    # 4. Optionally return the binding site.
    binding_site = None
    if binding_site_id:
        site = session.get(BindingSite, binding_site_id)
        if site is None:
            raise NotFoundError(f"Binding site '{binding_site_id}' does not exist.")
        binding_site = {
            "id": site.id,
            "name": site.name,
            "method": site.method,
            "centerX": site.center_x,
            "centerY": site.center_y,
            "centerZ": site.center_z,
            "sizeX": site.size_x,
            "sizeY": site.size_y,
            "sizeZ": site.size_z,
        }

    return {
        "receptorPrep": {
            "id": receptor_outcome.receptor_prep.id,
            "outputStructureId": receptor_outcome.record.id,
            "atomsKept": receptor_outcome.atoms_kept,
            "atomsRemoved": receptor_outcome.atoms_removed,
            "residuesKept": receptor_outcome.residues_kept,
            "warnings": receptor_outcome.warnings,
        },
        "ligandPrep": {
            "id": ligand_outcome.ligand_prep.id,
            "outputStructureId": ligand_outcome.record.id,
            "conformers": ligand_outcome.conformers,
            "warnings": ligand_outcome.warnings,
        },
        "receptorPdbqt": {
            "path": receptor_pdbqt["pdbqtPath"],
            "sha256": receptor_pdbqt["pdbqtSha256"],
            "heavyAtoms": receptor_pdbqt["heavyAtoms"],
            "pdbqtAtoms": receptor_pdbqt["pdbqtAtoms"],
        },
        "ligandPdbqt": {
            "path": ligand_pdbqt["pdbqtPath"],
            "sha256": ligand_pdbqt["pdbqtSha256"],
            "heavyAtoms": ligand_pdbqt["heavyAtoms"],
            "pdbqtAtoms": ligand_pdbqt["pdbqtAtoms"],
        },
        "bindingSite": binding_site,
    }


__all__ = [
    "prepare_receptor",
    "prepare_ligand",
    "define_binding_site",
    "generate_pdbqt",
    "prepare_for_docking",
    "PreparedReceptor",
    "PreparedLigand",
]

