"""Upload safety: filenames, format sniffing, size limits and path traversal.

These are the tests that guard the boundary between "a user typed something" and
"a file on disk".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import UnsupportedFormatError, UploadRejectedError, ValidationFailure
from app.core.security import (
    ensure_within,
    format_from_filename,
    resolve_upload,
    safe_filename,
    sniff_format,
)
from app.services.store import ArtifactStore, sha256_of_bytes


# --- filenames -------------------------------------------------------------
def test_safe_filename_strips_directory_components() -> None:
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert safe_filename("/absolute/path/receptor.pdb") == "receptor.pdb"


def test_safe_filename_replaces_unsafe_characters() -> None:
    assert safe_filename("my receptor (final!!).pdb") == "my_receptor_final_.pdb"
    assert safe_filename("a b\tc.pdb") == "a_b_c.pdb"


def test_safe_filename_never_starts_with_a_dot() -> None:
    # A leading dot would create a hidden file; it is stripped.
    assert safe_filename("...hidden.pdb") == "hidden.pdb"


def test_safe_filename_rejects_unusable_names() -> None:
    with pytest.raises(ValidationFailure):
        safe_filename("")
    with pytest.raises(ValidationFailure):
        safe_filename("..")
    with pytest.raises(ValidationFailure):
        safe_filename("///")


def test_safe_filename_keeps_ascii_only() -> None:
    name = safe_filename("café_β.pdb")
    assert name.isascii()
    assert name.endswith(".pdb")


def test_safe_filename_truncates_long_stems() -> None:
    name = safe_filename("x" * 500 + ".pdb")
    assert len(name) <= 84


# --- format detection -------------------------------------------------------
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("x.pdb", "pdb"),
        ("x.ent", "pdb"),
        ("x.cif", "mmcif"),
        ("x.mmcif", "mmcif"),
        ("x.sdf", "sdf"),
        ("x.mol", "sdf"),
        ("x.mol2", "mol2"),
        ("x.pdbqt", "pdbqt"),
        ("x.xyz", "xyz"),
        ("x.fasta", "fasta"),
        ("x.fa", "fasta"),
        ("X.PDB", "pdb"),
        ("x.docx", None),
        ("x", None),
    ],
)
def test_format_from_filename(filename: str, expected: str | None) -> None:
    assert format_from_filename(filename) == expected


def test_sniff_format_pdb() -> None:
    head = b"HEADER    HYDROLASE                               01-JAN-90   1XYZ\nATOM      1  N   GLY A   1\n"
    assert sniff_format(head) == "pdb"


def test_sniff_format_pdbqt_is_detected_before_pdb() -> None:
    head = b"REMARK  AUTODOCK\nROOT\nATOM      1  C   LIG A   1\n"
    assert sniff_format(head) == "pdbqt"


def test_sniff_format_mmcif() -> None:
    assert sniff_format(b"data_1UBQ\n_entry.id 1UBQ\n_atom_site.group_PDB\n") == "mmcif"


def test_sniff_format_sdf_and_mol2_and_xyz_and_fasta() -> None:
    assert sniff_format(b"\n     RDKit          3D\n\n  9  9  0  0  0  0  0  0  0  0999 V2000\n") == "sdf"
    assert sniff_format(b"@<TRIPOS>MOLECULE\nligand\n") == "mol2"
    assert sniff_format(b"3\nwater\nO 0.0 0.0 0.0\nH 0.0 0.0 0.96\nH 0.93 0.0 0.0\n") == "xyz"
    assert sniff_format(b">sp|P0CG48|UBIQUITIN\nMQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQR\n") == "fasta"


def test_sniff_format_returns_none_for_noise() -> None:
    assert sniff_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64) is None


# --- resolve_upload ---------------------------------------------------------
def test_resolve_upload_prefers_declared_format() -> None:
    upload = resolve_upload("ligand.bin", "sdf", b"anything", 100, 1000)
    assert upload.fmt == "sdf"
    assert upload.safe_name == "ligand.bin"


def test_resolve_upload_falls_back_to_content() -> None:
    upload = resolve_upload("mystery.dat", None, b"ATOM      1  N   GLY A   1\n", 100, 1000)
    assert upload.fmt == "pdb"


def test_resolve_upload_rejects_empty_file() -> None:
    with pytest.raises(ValidationFailure):
        resolve_upload("x.pdb", None, b"", 0, 1000)


def test_resolve_upload_rejects_oversized_file() -> None:
    with pytest.raises(UploadRejectedError) as excinfo:
        resolve_upload("x.pdb", None, b"ATOM", 5_000, 1_000)
    assert excinfo.value.detail["max_bytes"] == 1_000
    assert "MOLDOCK_MAX_UPLOAD_MB" in (excinfo.value.remediation or "")


def test_resolve_upload_rejects_unknown_declared_format() -> None:
    with pytest.raises(UnsupportedFormatError):
        resolve_upload("x.pdb", "topology", b"ATOM", 10, 1000)


def test_resolve_upload_rejects_undetectable_format() -> None:
    with pytest.raises(UnsupportedFormatError):
        resolve_upload("mystery.weird", None, b"\x00\x01\x02\x03", 4, 1000)


# --- path containment -------------------------------------------------------
def test_ensure_within_accepts_child_paths(tmp_path: Path) -> None:
    base = tmp_path / "project"
    base.mkdir()
    assert ensure_within(base, base / "file.pdb") == (base / "file.pdb").resolve()


def test_ensure_within_rejects_traversal(tmp_path: Path) -> None:
    base = tmp_path / "project"
    other = tmp_path / "elsewhere"
    base.mkdir()
    other.mkdir()
    with pytest.raises(ValidationFailure):
        ensure_within(base, other / "file.pdb")
    with pytest.raises(ValidationFailure):
        ensure_within(base, base / ".." / "elsewhere" / "file.pdb")


def test_store_absolute_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    store = ArtifactStore(settings)
    with pytest.raises(ValidationFailure):
        store.absolute("../../../etc/passwd")
    # A legitimate relative path resolves beneath the data root.
    assert store.absolute("projects/prj_x/structures/a.pdb").is_relative_to(settings.resolved_data_dir)


def test_store_rejects_unknown_category(tmp_path: Path) -> None:
    from app.core.config import Settings

    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    store = ArtifactStore(settings)
    with pytest.raises(UploadRejectedError):
        store.category_dir("prj_test", "not_a_category")


def test_store_hashes_content(tmp_path: Path) -> None:
    from app.core.config import Settings

    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_dirs()
    store = ArtifactStore(settings)
    artifact = store.store_bytes("prj_hash", "structures", "tiny.pdb", b"ATOM\n")
    assert artifact.sha256 == sha256_of_bytes(b"ATOM\n")
    assert artifact.size_bytes == 5
    assert artifact.absolute_path.read_bytes() == b"ATOM\n"
    assert artifact.relative_path.startswith("projects/prj_hash/structures/")
