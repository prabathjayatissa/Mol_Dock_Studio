"""Scientific data model.

Design rules (see docs/architecture.md):

* Large artefacts (coordinates, prepared receptors, poses, surfaces, logs) live
  as files under the data directory; the database stores metadata, checksums
  and the links that make results traceable.
* Every derived entity points at its inputs, so a pose can always be traced
  back to the receptor preparation and ligand preparation that produced it.
* Nothing here is phase specific: the tables for preparation, docking,
  interactions and screening exist from Phase 0 and are populated as each
  phase lands.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, id_factory


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("prj")
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Provenance of the project itself: who/what created it and with which build.
    origin: Mapped[dict[str, Any]] = mapped_column(default=dict)

    structures: Mapped[list[Structure]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Structure(TimestampMixin, Base):
    """An imported or derived molecular structure (protein, ligand, complex)."""

    __tablename__ = "structures"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("str")
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # protein | ligand | complex | receptor | pose | library
    kind: Mapped[str] = mapped_column(String(32), default="protein", index=True)
    # pdb | mmcif | sdf | mol2 | pdbqt | xyz | fasta
    format: Mapped[str] = mapped_column(String(16))
    # uploaded | rcsb | derived | generated
    source: Mapped[str] = mapped_column(String(32), default="uploaded")
    file_path: Mapped[str] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    atoms_count: Mapped[int] = mapped_column(Integer, default=0)
    residues_count: Mapped[int] = mapped_column(Integer, default=0)
    chains_count: Mapped[int] = mapped_column(Integer, default=0)
    chains: Mapped[list[Any]] = mapped_column(default=list)
    elements: Mapped[list[Any]] = mapped_column(default=list)

    # Parsing/preparation warnings and information-loss report.
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    # Free-form descriptors: bounding box, SS content, ligand SMILES, etc.
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Import parameters, software versions and transformations applied.
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)

    project: Mapped[Project] = relationship(back_populates="structures")
    ligand: Mapped[Ligand | None] = relationship(
        back_populates="structure", cascade="all, delete-orphan", uselist=False
    )
    parent: Mapped[Structure | None] = relationship(remote_side="Structure.id", back_populates="derived")
    derived: Mapped[list[Structure]] = relationship(back_populates="parent")


class Ligand(TimestampMixin, Base):
    """Chemical identity and computed descriptors for a ligand structure."""

    __tablename__ = "ligands"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("lig")
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    structure_id: Mapped[str] = mapped_column(
        ForeignKey("structures.id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    inchi_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    formula: Mapped[str | None] = mapped_column(String(120), nullable=True)
    molecular_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    logp: Mapped[float | None] = mapped_column(Float, nullable=True)
    tpsa: Mapped[float | None] = mapped_column(Float, nullable=True)
    h_bond_donors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h_bond_acceptors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotatable_bonds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    formal_charge: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heavy_atoms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aromatic_rings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stereocenters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'computed' (RDKit) vs 'reported' (from the file's data block). The UI must
    # never present a computed descriptor as an experimental measurement.
    descriptor_source: Mapped[str] = mapped_column(String(32), default="computed")
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_messages: Mapped[list[Any]] = mapped_column(default=list)
    properties: Mapped[dict[str, Any]] = mapped_column(default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)

    structure: Mapped[Structure] = relationship(back_populates="ligand")


class ReceptorPrep(TimestampMixin, Base):
    """A receptor-preparation run (Phase 2)."""

    __tablename__ = "receptor_preps"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("rpr")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    input_structure_id: Mapped[str] = mapped_column(ForeignKey("structures.id", ondelete="CASCADE"))
    output_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)


class LigandPrep(TimestampMixin, Base):
    """A ligand-preparation run (Phase 2)."""

    __tablename__ = "ligand_preps"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("lpr")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    ligand_id: Mapped[str] = mapped_column(ForeignKey("ligands.id", ondelete="CASCADE"))
    output_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)


class BindingSite(TimestampMixin, Base):
    """A docking search space (Phase 2/3)."""

    __tablename__ = "binding_sites"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("bst")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    receptor_structure_id: Mapped[str] = mapped_column(ForeignKey("structures.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160), default="Site 1")
    # ligand | residues | point | manual
    method: Mapped[str] = mapped_column(String(24), default="manual")
    center_x: Mapped[float] = mapped_column(Float)
    center_y: Mapped[float] = mapped_column(Float)
    center_z: Mapped[float] = mapped_column(Float)
    size_x: Mapped[float] = mapped_column(Float, default=22.0)
    size_y: Mapped[float] = mapped_column(Float, default=22.0)
    size_z: Mapped[float] = mapped_column(Float, default=22.0)
    source_ligand_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    residues: Mapped[list[Any]] = mapped_column(default=list)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DockingConfig(TimestampMixin, Base):
    """A reusable docking configuration (Phase 3)."""

    __tablename__ = "docking_configs"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("dcf")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="Default")
    engine: Mapped[str] = mapped_column(String(32), default="vina")
    receptor_prep_id: Mapped[str | None] = mapped_column(
        ForeignKey("receptor_preps.id", ondelete="SET NULL"), nullable=True
    )
    binding_site_id: Mapped[str | None] = mapped_column(
        ForeignKey("binding_sites.id", ondelete="SET NULL"), nullable=True
    )
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Job(TimestampMixin, Base):
    """A background job. State machine: queued -> preparing -> running -> terminal."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("job")
    )

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(48), index=True)
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[dict[str, Any]] = mapped_column(default=dict)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queued_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Full reproducibility record: command line, versions, configuration.
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DockingJob(TimestampMixin, Base):
    """Docking-run specific detail hanging off a Job (Phase 3)."""

    __tablename__ = "docking_jobs"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("djb")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    engine: Mapped[str] = mapped_column(String(32), default="vina")
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receptor_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    ligand_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    command: Mapped[list[Any]] = mapped_column(default=list)
    output_files: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DockingPose(TimestampMixin, Base):
    """One ranked pose from a docking run (Phase 3)."""

    __tablename__ = "docking_poses"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("pos")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    docking_job_id: Mapped[str] = mapped_column(ForeignKey("docking_jobs.id", ondelete="CASCADE"), index=True)
    structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    pose_index: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer)
    score_kcal_mol: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmsd_lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmsd_upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class InteractionAnalysis(TimestampMixin, Base):
    """A protein-ligand interaction analysis run (Phase 4)."""

    __tablename__ = "interaction_analyses"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("ifa")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    complex_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    methods: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ScreeningRun(TimestampMixin, Base):
    """A virtual-screening campaign (Phase 5)."""

    __tablename__ = "screening_runs"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("scr")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    library_structure_id: Mapped[str | None] = mapped_column(
        ForeignKey("structures.id", ondelete="SET NULL"), nullable=True
    )
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_path: Mapped[str | None] = mapped_column(Text, nullable=True)


class Report(TimestampMixin, Base):
    """A generated figure set or scientific report (Phase 4/5)."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("rpt")
    )

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200), default="")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ProvenanceRecord(TimestampMixin, Base):
    """Append-only audit trail.

    Every import, export, preparation, docking run and analysis writes one row
    so that any scientific result can be traced back to its inputs, the
    software versions used and the parameters applied.
    """

    __tablename__ = "provenance_records"

    id: Mapped[str] = mapped_column(
        String(48), primary_key=True, default=id_factory("prv")
    )

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(48), index=True)
    entity_id: Mapped[str] = mapped_column(String(48), index=True)
    action: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    outputs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(default=dict)
    software: Mapped[dict[str, Any]] = mapped_column(default=dict)


Index("ix_structures_project_kind", Structure.project_id, Structure.kind)
Index("ix_jobs_project_state", Job.project_id, Job.state)
