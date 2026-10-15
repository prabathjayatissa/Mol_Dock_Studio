"""Child-process entry point for background jobs.

Runs inside a fresh interpreter (``spawn`` start method), so it must be
importable as ``app.services.jobs.child:child_main``. All heavy scientific work
happens here, isolated from the API process: a crash or a runaway allocation
takes down the child, never the server.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any

from app.core.errors import MolDockError
from app.core.logging import configure_logging
from app.services.jobs.progress import ProgressReporter
from app.services.jobs.registry import resolve_handler


def child_main(
    job_id: str,
    kind: str,
    params: dict[str, Any],
    log_path: str,
    progress_path: str,
    result_path: str,
) -> None:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    configure_logging("INFO")
    logger = logging.getLogger(f"moldock.job.{kind}")
    handler_stdout = log_file.open("a", encoding="utf-8", buffering=1)

    reporter = ProgressReporter(Path(progress_path))
    payload: dict[str, Any]

    try:
        handler = resolve_handler(kind)
        reporter.state("preparing", f"Starting {kind}")
        logger.info("job %s (%s) started with params %s", job_id, kind, params)
        print(f"[moldock] job {job_id} ({kind}) starting", file=handler_stdout)
        result = handler(params, reporter)
        payload = {"ok": True, "result": result}
        logger.info("job %s completed", job_id)
    except MolDockError as exc:
        logger.warning("job %s failed: %s", job_id, exc.message)
        payload = {"ok": False, "error": exc.to_payload()}
    except Exception as exc:  # noqa: BLE001 - the child must never crash silently
        logger.exception("job %s crashed", job_id)
        payload = {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
                "detail": {"traceback": traceback.format_exc()[-4000:]},
            },
        }
    finally:
        handler_stdout.flush()
        handler_stdout.close()

    result_file = Path(result_path)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover - manual invocation
    if len(sys.argv) != 7:  # noqa: PLR2004
        raise SystemExit("usage: child_main job_id kind params_json log progress result")
    child_main(
        sys.argv[1],
        sys.argv[2],
        json.loads(sys.argv[3]),
        sys.argv[4],
        sys.argv[5],
        sys.argv[6],
    )
