"""Logging setup (single place so containers and tests behave identically)."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # already configured (uvicorn reload / repeated import)
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # httpx logs every RCSB request at INFO; keep the console readable.
    logging.getLogger("httpx").setLevel("WARNING")
