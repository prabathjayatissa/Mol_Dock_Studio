"""RCSB PDB retrieval.

Only the public ``files.rcsb.org`` download endpoint is used, with an explicit
timeout, a strict identifier check and clearly separated error cases (bad ID,
not found, network failure) so the UI can tell the user what actually happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import NetworkFetchError, NotFoundError, ValidationFailure

PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")

DownloadFormat = Literal["pdb", "mmcif"]

_EXTENSIONS: dict[str, str] = {"pdb": "pdb", "mmcif": "cif"}


@dataclass
class FetchedEntry:
    entry_id: str
    format: DownloadFormat
    data: bytes
    filename: str
    url: str
    title: str | None = None
    classification: str | None = None
    size_bytes: int = 0


def validate_pdb_id(entry_id: str) -> str:
    """Validate an RCSB identifier.

    The PDB identifier space is exactly four characters starting with a digit
    for the classic format; extended IDs are not supported because the download
    endpoint does not serve them.
    """
    candidate = (entry_id or "").strip().upper()
    if not PDB_ID_PATTERN.match(candidate):
        raise ValidationFailure(
            f"'{entry_id}' is not a valid 4-character PDB identifier (for example 1UBQ or 3PTB).",
            detail={"value": entry_id, "pattern": PDB_ID_PATTERN.pattern},
            remediation="Check the identifier on rcsb.org and try again.",
        )
    return candidate


def parse_title(data: bytes, fmt: DownloadFormat) -> tuple[str | None, str | None]:
    """Best-effort extraction of the entry title and classification."""
    text = data.decode("utf-8", errors="replace")
    title_parts: list[str] = []
    classification: str | None = None
    for line in text.splitlines()[:200]:
        if fmt == "pdb":
            if line.startswith("TITLE"):
                title_parts.append(line[10:].strip())
            elif line.startswith("HEADER") and classification is None:
                classification = line[10:50].strip() or None
        else:
            stripped = line.strip()
            if stripped.startswith("_struct.title"):
                value = stripped.split(None, 1)
                if len(value) == 2:
                    title_parts.append(value[1].strip().strip("'\""))
            elif stripped.startswith("_struct_keywords.pdbx_keywords") and classification is None:
                value = stripped.split(None, 1)
                if len(value) == 2:
                    classification = value[1].strip().strip("'\"")
    title = " ".join(title_parts).strip() or None
    if title:
        title = re.sub(r"\s+", " ", title.rstrip(";"))
    return title, classification


async def fetch_entry(
    entry_id: str, *, fmt: DownloadFormat = "pdb", settings: Settings | None = None
) -> FetchedEntry:
    settings = settings or get_settings()
    candidate = validate_pdb_id(entry_id)
    extension = _EXTENSIONS[fmt]
    url = f"{settings.rcsb_base_url.rstrip('/')}/{candidate}.{extension}"

    try:
        async with httpx.AsyncClient(timeout=settings.rcsb_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise NetworkFetchError(
            f"The RCSB PDB did not respond within {settings.rcsb_timeout_seconds}s.",
            detail={"url": url},
            remediation="Check your network connection, or import the file manually from rcsb.org.",
        ) from exc
    except httpx.HTTPError as exc:
        raise NetworkFetchError(
            f"Could not reach the RCSB PDB: {exc}",
            detail={"url": url},
            remediation="Check your network connection or proxy settings.",
        ) from exc

    if response.status_code == 404:  # noqa: PLR2004
        raise NotFoundError(
            f"Entry {candidate} was not found in the RCSB PDB.",
            detail={"entry": candidate, "url": url},
            remediation="Verify the identifier at https://www.rcsb.org.",
        )
    if response.status_code >= 400:  # noqa: PLR2004
        raise NetworkFetchError(
            f"The RCSB PDB returned HTTP {response.status_code} for {candidate}.",
            detail={"status": response.status_code, "url": url},
        )

    data = response.content
    if not data:
        raise NetworkFetchError(f"The RCSB PDB returned an empty file for {candidate}.", detail={"url": url})

    title, classification = parse_title(data, fmt)
    return FetchedEntry(
        entry_id=candidate,
        format=fmt,
        data=data,
        filename=f"{candidate}.{extension}",
        url=url,
        title=title,
        classification=classification,
        size_bytes=len(data),
    )
