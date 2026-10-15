"""Error types and JSON error envelopes."""

from __future__ import annotations

from typing import Any


class MolDockError(Exception):
    """Base class for expected, user-facing failures.

    ``code`` is a stable machine-readable identifier, ``message`` is written for
    a scientist, ``detail`` carries structured context (offsets, filenames,
    offending records) and ``remediation`` tells the user what to do next.
    """

    status_code = 400
    code = "moldock_error"

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        self.remediation = remediation

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message, "detail": self.detail}
        if self.remediation:
            payload["remediation"] = self.remediation
        return payload


class NotFoundError(MolDockError):
    status_code = 404
    code = "not_found"


class ConflictError(MolDockError):
    status_code = 409
    code = "conflict"


class UnsupportedFormatError(MolDockError):
    status_code = 415
    code = "unsupported_format"


class StructureParseError(MolDockError):
    status_code = 422
    code = "structure_parse_error"


class UploadRejectedError(MolDockError):
    status_code = 413
    code = "upload_rejected"


class ValidationFailure(MolDockError):
    status_code = 422
    code = "validation_failure"


class CapabilityUnavailableError(MolDockError):
    """A scientific tool required for the request is not installed.

    Raised instead of silently degrading or substituting a fake result.
    """

    status_code = 503
    code = "capability_unavailable"


class JobError(MolDockError):
    status_code = 500
    code = "job_error"


class NetworkFetchError(MolDockError):
    status_code = 502
    code = "network_fetch_error"
