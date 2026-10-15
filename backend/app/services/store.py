"""Artifact store: where molecular data actually lives.

Large artefacts are files, not database rows. Every artefact is written beneath
``<data>/projects/<project_id>/<category>/`` with a sanitised name and a
content hash, and the database stores the relative path plus the checksum so a
stored file can always be verified.

Layout::

    data/
      projects/<project_id>/
        structures/    imported and derived coordinate files
        ligands/       ligand inputs
        receptors/     prepared receptors (Phase 2)
        poses/         docking output (Phase 3)
        surfaces/      cached surface meshes
        reports/       figures and reports
      cache/           shared caches (keyed by content hash)
      jobs/<job_id>/   job stdout/stderr logs and scratch files
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, UploadRejectedError, ValidationFailure
from app.core.security import ensure_within, safe_filename

CATEGORIES = {
    "structures",
    "ligands",
    "receptors",
    "prepared_ligands",
    "poses",
    "surfaces",
    "reports",
    "exports",
    "scratch",
}


@dataclass(frozen=True)
class StoredArtifact:
    relative_path: str
    absolute_path: Path
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
        }


def sha256_of(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactStore:
    """Filesystem operations for project artefacts."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # --- paths ------------------------------------------------------------
    @property
    def root(self) -> Path:
        return self.settings.resolved_data_dir

    def project_dir(self, project_id: str) -> Path:
        path = self.root / "projects" / safe_filename(project_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def category_dir(self, project_id: str, category: str) -> Path:
        if category not in CATEGORIES:
            raise UploadRejectedError(f"Unknown artefact category '{category}'.")
        path = self.project_dir(project_id) / category
        path.mkdir(parents=True, exist_ok=True)
        return path

    def job_dir(self, job_id: str) -> Path:
        path = self.settings.jobs_dir / safe_filename(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cache_dir(self, category: str = "shared") -> Path:
        path = self.settings.cache_dir / safe_filename(category)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def absolute(self, relative_path: str) -> Path:
        """Resolve a stored relative path, refusing to escape the data root."""
        candidate = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValidationFailure(
                "Stored artefact path escapes the data directory.",
                detail={"path": relative_path},
            )
        return candidate

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    # --- writes -----------------------------------------------------------
    def store_bytes(
        self, project_id: str, category: str, filename: str, data: bytes
    ) -> StoredArtifact:
        directory = self.category_dir(project_id, category)
        name = safe_filename(filename)
        target = ensure_within(directory, directory / name)
        target.write_bytes(data)
        return StoredArtifact(
            relative_path=self.relative(target),
            absolute_path=target,
            sha256=sha256_of_bytes(data),
            size_bytes=len(data),
        )

    def store_file(self, project_id: str, category: str, filename: str, source: Path) -> StoredArtifact:
        directory = self.category_dir(project_id, category)
        name = safe_filename(filename)
        target = ensure_within(directory, directory / name)
        shutil.copyfile(source, target)
        return StoredArtifact(
            relative_path=self.relative(target),
            absolute_path=target,
            sha256=sha256_of(target),
            size_bytes=target.stat().st_size,
        )

    def duplicate(
        self, source_relative: str, project_id: str, category: str, filename: str
    ) -> StoredArtifact:
        source = self.absolute(source_relative)
        if not source.exists():
            raise NotFoundError(f"Stored artefact not found: {source_relative}")
        return self.store_file(project_id, category, filename, source)

    def write_text(self, project_id: str, category: str, filename: str, text: str) -> StoredArtifact:
        return self.store_bytes(project_id, category, filename, text.encode("utf-8"))

    def read_text(self, relative_path: str) -> str:
        return self.absolute(relative_path).read_text(encoding="utf-8", errors="replace")

    # --- cache ------------------------------------------------------------
    def cached(self, namespace: str, key: str, suffix: str) -> Path:
        """A stable cache path for ``key``.

        The key is hashed rather than sanitised: cache keys are structured
        (JSON, parameter lists) and sanitising them can collide two different
        parameter sets into the same filename. A digest cannot.
        """
        directory = self.cache_dir(namespace)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return directory / f"{digest}{suffix}"

    # --- lifecycle --------------------------------------------------------
    def delete_project(self, project_id: str) -> None:
        path = self.root / "projects" / safe_filename(project_id)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def delete_artifact(self, relative_path: str) -> None:
        path = self.absolute(relative_path)
        if path.exists():
            path.unlink()


def get_store() -> ArtifactStore:
    return ArtifactStore()


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"
