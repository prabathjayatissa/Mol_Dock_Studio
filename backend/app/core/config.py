"""Application configuration.

All settings are environment driven (prefix ``MOLDOCK_``) so that the same
code runs natively, in Docker, and in tests. Nothing here reaches the network
or the filesystem at import time; call :func:`get_settings` and ``ensure_dirs``
explicitly.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime configuration for the MolDock Studio backend."""

    model_config = SettingsConfigDict(
        env_prefix="MOLDOCK_",
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- application ---
    env: str = "development"
    log_level: str = "INFO"
    data_dir: Path = Field(default=Path("./data"))
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- persistence ---
    database_url: str = ""

    # --- safety limits ---
    max_upload_mb: int = 200
    max_atoms: int = 500_000
    job_timeout_seconds: int = 3600
    max_concurrent_jobs: int = 2

    # --- scientific backends ---
    scientific_backend_mode: str = "native"
    vina_binary: str = ""
    obabel_binary: str = ""
    rcsb_base_url: str = "https://files.rcsb.org/download"
    rcsb_timeout_seconds: int = 30

    # --- surface generation defaults ---
    default_probe_radius: float = 1.4
    surface_grid_spacing: float = 0.8

    @field_validator("data_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_data_dir(self) -> Path:
        """Absolute data directory (relative paths are anchored at the repo root)."""
        if self.data_dir.is_absolute():
            return self.data_dir
        return (REPO_ROOT / self.data_dir).resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.resolved_data_dir / 'moldock.db').as_posix()}"

    @property
    def projects_dir(self) -> Path:
        return self.resolved_data_dir / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.resolved_data_dir / "cache"

    @property
    def jobs_dir(self) -> Path:
        return self.resolved_data_dir / "jobs"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    def ensure_dirs(self) -> None:
        for path in (
            self.resolved_data_dir,
            self.projects_dir,
            self.cache_dir,
            self.jobs_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
