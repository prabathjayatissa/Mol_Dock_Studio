"""Upload safety: filename sanitisation, format detection and size limits.

Uploaded structures, filenames and metadata are untrusted input. Everything a
user supplies passes through this module before it touches the filesystem, and
files are always written beneath a resolved, project-scoped directory.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import UnsupportedFormatError, UploadRejectedError, ValidationFailure

# --- supported molecular formats -------------------------------------------
# key -> (extensions, human label, parser family)
SUPPORTED_FORMATS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "pdb": ((".pdb", ".ent"), "Protein Data Bank", "gemmi"),
    "mmcif": ((".cif", ".mmcif"), "PDBx/mmCIF", "gemmi"),
    "sdf": ((".sdf", ".mol"), "MDL SDF / MOL", "rdkit"),
    "mol2": ((".mol2",), "Tripos MOL2", "rdkit"),
    "pdbqt": ((".pdbqt",), "AutoDock PDBQT", "moldock"),
    "xyz": ((".xyz",), "XYZ coordinates", "rdkit"),
    "fasta": ((".fasta", ".fa", ".faa"), "FASTA sequence", "biopython"),
}

EXTENSION_TO_FORMAT: dict[str, str] = {
    ext: fmt for fmt, (exts, _, _) in SUPPORTED_FORMATS.items() for ext in exts
}

ALLOWED_EXTENSIONS: set[str] = set(EXTENSION_TO_FORMAT)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM = 80


def format_from_filename(filename: str) -> str | None:
    """Map a filename to a supported format key, or ``None`` if unknown."""
    suffix = Path(filename).suffix.lower()
    return EXTENSION_TO_FORMAT.get(suffix)


def safe_filename(filename: str) -> str:
    """Return a filesystem-safe basename.

    Strips directory components, Unicode oddities, control characters and
    anything that is not ``[A-Za-z0-9._-]``. Never returns an empty name and
    never returns a name that resolves outside the target directory.
    """
    if not filename:
        raise ValidationFailure("A filename is required.")

    # Normalise and drop any path information, including Windows separators.
    name = unicodedata.normalize("NFKD", filename).strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).lstrip(".")

    if not name or set(name) <= {".", "_", "-"}:
        raise ValidationFailure("The filename does not contain any usable characters.")

    stem = Path(name).stem[:_MAX_STEM] or "structure"
    suffix = Path(name).suffix.lower()
    if suffix and suffix.lstrip(".") not in {e.lstrip(".") for e in ALLOWED_EXTENSIONS}:
        # Keep the extension but mark it as unrecognised; the caller decides.
        suffix = suffix[:10]
    return f"{stem}{suffix}"


def sniff_format(head: bytes) -> str | None:
    """Content-based format detection used when the extension is unhelpful."""
    text = head.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith(("HEADER", "ATOM  ", "HETATM", "CRYST1", "REMARK", "COMPND")):
        if "AUTODOCK" in text.upper() or "ROOT" in text[:2000]:
            return "pdbqt"
        return "pdb"
    if "data_" in stripped[:200] or "_atom_site." in text:
        return "mmcif"
    if stripped.startswith("MOL2") or "@<TRIPOS>" in text:
        return "mol2"
    if "$$$$" in text[:20000] or "V2000" in text[:5000] or "V3000" in text[:5000]:
        return "sdf"
    lines = [line for line in text.splitlines()[:5]]
    # XYZ: an atom count, a comment line, then "Element x y z".
    if len(lines) >= 3 and len(lines[0].split()) == 1:
        try:
            int(lines[0].split()[0])
        except ValueError:
            pass
        else:
            for candidate in lines[2:5]:
                parts = candidate.split()
                if len(parts) >= 4 and re.fullmatch(r"[A-Za-z]{1,3}", parts[0]):
                    try:
                        [float(value) for value in parts[1:4]]
                    except ValueError:
                        continue
                    return "xyz"
    if stripped.startswith(">") or re.match(
        r"^[ACDEFGHIKLMNPQRSTVWYXBZJUO]+\s*$", stripped.split("\n")[0]
    ):
        return "fasta"
    return None


@dataclass(frozen=True)
class ResolvedUpload:
    """Validated upload metadata."""

    original_filename: str
    safe_name: str
    fmt: str
    size_bytes: int


def resolve_upload(
    filename: str,
    declared_format: str | None,
    content_head: bytes,
    size_bytes: int,
    max_bytes: int,
) -> ResolvedUpload:
    """Validate an upload's name, size and format before parsing."""
    if size_bytes <= 0:
        raise ValidationFailure("The uploaded file is empty.")
    if size_bytes > max_bytes:
        raise UploadRejectedError(
            f"The uploaded file is {size_bytes / 1e6:.1f} MB, which exceeds the "
            f"{max_bytes / 1e6:.0f} MB limit.",
            detail={"size_bytes": size_bytes, "max_bytes": max_bytes},
            remediation="Raise MOLDOCK_MAX_UPLOAD_MB in .env if this file is legitimate.",
        )

    name = safe_filename(filename)
    fmt = (declared_format or "").strip().lower() or None
    if fmt and fmt not in SUPPORTED_FORMATS:
        raise UnsupportedFormatError(
            f"Unsupported format '{declared_format}'.",
            detail={"supported": sorted(SUPPORTED_FORMATS)},
        )
    if fmt is None:
        fmt = format_from_filename(name) or sniff_format(content_head)

    if fmt is None:
        raise UnsupportedFormatError(
            f"Could not determine the structure format for '{filename}'.",
            detail={"supported_extensions": sorted(ALLOWED_EXTENSIONS)},
            remediation="Rename the file with a supported extension or pass an explicit format.",
        )
    return ResolvedUpload(
        original_filename=filename, safe_name=name, fmt=fmt, size_bytes=size_bytes
    )


def ensure_within(base: Path, candidate: Path) -> Path:
    """Reject path traversal: ``candidate`` must live inside ``base``."""
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()
    if base_resolved != candidate_resolved and base_resolved not in candidate_resolved.parents:
        raise ValidationFailure(
            "Resolved file path escapes the project directory.",
            detail={"base": str(base_resolved), "candidate": str(candidate_resolved)},
        )
    return candidate_resolved
