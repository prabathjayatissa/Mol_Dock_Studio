"""Built-in job handlers.

``generate_surface_job`` is the real Phase 1 heavy job: surface generation is
O(grid x atoms) and is kept off the request thread for large structures.

``pipeline_self_test_job`` is a genuine diagnostic, not a placeholder: it lets a
user (and the test suite) verify that the job pipeline reports progress, honours
cancellation and enforces timeouts on their machine.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.errors import NotFoundError, ValidationFailure
from app.services.docking.engine import resolve_docking_engine
from app.services.docking.rmsd import symmetry_aware_pose_rmsd
from app.services.io.parsers import parse_structure_file
from app.services.preparation import generate_pdbqt
from app.services.store import ArtifactStore


def _load_structure(store: ArtifactStore, relative_path: str, fmt: str):
    path = store.absolute(relative_path)
    if not path.exists():
        raise NotFoundError(f"Structure file is missing from the store: {relative_path}")
    return parse_structure_file(path, fmt, name=path.stem, source="stored")


def generate_surface_job(params: dict[str, Any], progress) -> dict[str, Any]:
    """Compute a surface mesh and cache it, returning the cache path and stats."""
    from app.services.surfaces import (  # local import keeps the child light
        SurfaceRequest,
        generate_and_cache,
    )

    progress.state("running", "Reading structure")
    request = SurfaceRequest(**params)
    store = ArtifactStore()
    structure = _load_structure(store, request.structure_path, request.structure_format)
    progress.progress(0.1, f"Loaded {structure.atom_count} atoms")

    def step(fraction: float, message: str) -> None:
        progress.progress(fraction, message)

    stats, cache_path = generate_and_cache(structure, request, store, on_progress=step)
    progress.progress(1.0, "Surface ready")
    return {"cachePath": cache_path, "stats": stats}


def pipeline_self_test_job(params: dict[str, Any], progress) -> dict[str, Any]:
    """Exercise the job pipeline: report progress on a fixed schedule.

    Parameters
    ----------
    steps:
        Number of progress updates to emit.
    seconds_per_step:
        Wall-clock delay between updates. ``cancel`` and ``timeout`` tests use
        this to hold the job open.
    """
    steps = int(params.get("steps", 5))
    seconds_per_step = float(params.get("seconds_per_step", 0.4))
    progress.state("running", "Self-test running")
    for step_index in range(steps):
        time.sleep(seconds_per_step)
        progress.progress((step_index + 1) / steps, f"Step {step_index + 1}/{steps}")
    progress.state("running", "Self-test finished")
    return {
        "steps": steps,
        "secondsPerStep": seconds_per_step,
        "elapsed": round(steps * seconds_per_step, 3),
        "note": "Job pipeline executed in an isolated child process.",
    }


def docking_job(params: dict[str, Any], progress) -> dict[str, Any]:
    """Run an AutoDock Vina docking calculation in a background job.

    Parameters
    ----------
    params:
        receptorStructureId, ligandStructureId, bindingSiteId (optional),
        projectId, numModes, energyRange, exhaustiveness, seed.
    progress:
        ProgressReporter for the child process.

    Returns
    -------
    dict
        Docking run result with ranked poses (stored as job.result).
    """
    from sqlalchemy import select

    from app.db.models import (
        BindingSite,
        DockingJob,
        DockingPose,
        Ligand,
        Structure,
    )
    from app.db.session import session_scope

    receptor_id = params["receptorStructureId"]
    ligand_id = params["ligandStructureId"]
    binding_site_id = params.get("bindingSiteId")
    project_id = params.get("projectId")
    num_modes = int(params.get("numModes", 9))
    energy_range = float(params.get("energyRange", 3.0))
    exhaustiveness = int(params.get("exhaustiveness", 8))
    seed = params.get("seed")

    progress.state("running", "Loading structures")
    store = ArtifactStore()

    with session_scope() as session:
        receptor = session.get(Structure, receptor_id)
        ligand = session.get(Structure, ligand_id)
        if receptor is None:
            raise NotFoundError(f"Receptor structure '{receptor_id}' not found.")
        if ligand is None:
            raise NotFoundError(f"Ligand structure '{ligand_id}' not found.")
        receptor_project_id = receptor.project_id
        ligand_project_id = ligand.project_id
        project_id = project_id or receptor_project_id or ligand_project_id

        # Generate PDBQT for receptor and ligand.
        progress.progress(0.15, "Preparing receptor PDBQT")
        receptor_pdbqt = generate_pdbqt(
            session,
            project_id=project_id,
            structure_id=receptor_id,
            store=store,
        )
        progress.progress(0.35, "Preparing ligand PDBQT")
        ligand_pdbqt = generate_pdbqt(
            session,
            project_id=project_id,
            structure_id=ligand_id,
            store=store,
        )

        # Determine the search box.
        box_center = (0.0, 0.0, 0.0)
        box_size = (22.0, 22.0, 22.0)
        if binding_site_id:
            site = session.get(BindingSite, binding_site_id)
            if site is None:
                raise NotFoundError(f"Binding site '{binding_site_id}' not found.")
            box_center = (site.center_x, site.center_y, site.center_z)
            box_size = (site.size_x, site.size_y, site.size_z)

        # Load reference ligand for symmetry-aware RMSD (crystal pose).
        reference_mol = None
        ligand_row = session.scalars(
            select(Ligand).where(Ligand.structure_id == ligand_id)
        ).first()
        if ligand_row is not None and ligand_row.smiles:
            from rdkit import Chem

            reference_mol = Chem.MolFromSmiles(ligand_row.smiles)

    # Run Vina docking (outside the session - engine is subprocess-based).
    engine = resolve_docking_engine()
    if not engine.is_available():
        raise ValidationFailure(
            "AutoDock Vina is not available on this machine.",
            detail={"engine": "vina"},
            remediation=(
                "Install AutoDock Vina (linux/amd64 via Docker, or build from source) "
                "and set MOLDOCK_VINA_BINARY to its path."
            ),
        )

    progress.state("running", "Running AutoDock Vina")
    progress.progress(0.5, "Vina docking in progress")

    result = engine.dock(
        receptor_pdbqt=receptor_pdbqt["path"],
        ligand_pdbqt=ligand_pdbqt["path"],
        box_center=box_center,
        box_size=box_size,
        num_modes=num_modes,
        energy_range=energy_range,
        exhaustiveness=exhaustiveness,
        seed=seed,
    )

    # Compute symmetry-aware RMSD against the reference (crystal) pose.
    progress.progress(0.9, "Computing pose RMSD")
    from rdkit import Chem

    for pose in result.poses:
        if pose.file_path and reference_mol is not None:
            pose_mol = Chem.MolFromPDBFile(pose.file_path, removeHs=False, sanitize=False)
            if pose_mol is not None:
                pose.rmsd_lower_bound = symmetry_aware_pose_rmsd(pose_mol, reference_mol)

    # Persist the docking job and poses to the database.
    with session_scope() as session:
        docking_job_row = DockingJob(
            project_id=project_id,
            engine="vina",
            engine_version=engine.version,
            receptor_file=receptor_pdbqt["path"],
            ligand_file=ligand_pdbqt["path"],
            config={
                "numModes": num_modes,
                "energyRange": energy_range,
                "exhaustiveness": exhaustiveness,
                "seed": seed,
                "boxCenter": list(box_center),
                "boxSize": list(box_size),
            },
            command=result.command,
            output_files=result.output_files,
            summary={
                "numPoses": len(result.poses),
                "bestScore": result.poses[0].score_kcal_mol if result.poses else None,
            },
        )
        session.add(docking_job_row)
        session.flush()

        for pose in result.poses:
            pose_row = DockingPose(
                project_id=project_id,
                docking_job_id=docking_job_row.id,
                pose_index=pose.rank,
                rank=pose.rank,
                score_kcal_mol=pose.score_kcal_mol,
                rmsd_lower_bound=pose.rmsd_lower_bound,
                rmsd_upper_bound=pose.rmsd_upper_bound,
                file_path=pose.file_path,
                meta=pose.meta,
            )
            session.add(pose_row)
        session.commit()

    progress.progress(1.0, "Docking complete")

    return {
        "engine": result.engine,
        "engineVersion": result.engine_version,
        "receptorFile": result.receptor_file,
        "ligandFile": result.ligand_file,
        "boxCenter": list(result.box_center),
        "boxSize": list(result.box_size),
        "numModes": result.num_modes,
        "energyRange": result.energy_range,
        "exhaustiveness": result.exhaustiveness,
        "numPoses": len(result.poses),
        "poses": [
            {
                "rank": p.rank,
                "scoreKcalMol": p.score_kcal_mol,
                "rmsdLowerBound": p.rmsd_lower_bound,
                "rmsdUpperBound": p.rmsd_upper_bound,
                "filePath": p.file_path,
                "meta": p.meta,
            }
            for p in result.poses
        ],
        "command": result.command,
        "workDir": result.work_dir,
        "outputFiles": result.output_files,
        "rawOutput": result.raw_output,
        "note": (
            "Docking scores are approximate AutoDock Vina scoring-function "
            "outputs, not measured binding affinities or clinical evidence."
        ),
    }
