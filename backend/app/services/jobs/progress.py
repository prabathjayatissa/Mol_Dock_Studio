"""Progress reporting from a child job process to the parent.

The child appends one JSON object per line to a progress file; the parent polls
that file. This avoids pickling queues through the spawn boundary and survives a
killed child (whatever was flushed remains readable).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class ProgressReporter:
    """Write progress events to the job's progress file."""

    def __init__(self, path: Path, *, min_interval: float = 0.05) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_write = 0.0
        self._min_interval = min_interval

    def _write(self, event: dict[str, Any], *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < self._min_interval:
            return
        self._last_write = now
        event = {"time": time.time(), **event}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def state(self, state: str, message: str = "") -> None:
        self._write({"state": state, "message": message, "progress": 0.0}, force=True)

    def progress(self, fraction: float, message: str = "") -> None:
        self._write({"progress": max(0.0, min(1.0, float(fraction))), "message": message})

    def log(self, message: str) -> None:
        self._write({"log": message}, force=True)

    def result(self, payload: dict[str, Any]) -> None:
        self._write({"result": payload}, force=True)


def read_progress(path: Path) -> dict[str, Any]:
    """Read the latest state/progress/message from a progress file."""
    summary: dict[str, Any] = {"progress": None, "message": "", "state": None, "lines": 0}
    if not path.exists():
        return summary
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                summary["lines"] += 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "progress" in event and event["progress"] is not None:
                    summary["progress"] = float(event["progress"])
                if event.get("message"):
                    summary["message"] = str(event["message"])
                if event.get("state"):
                    summary["state"] = str(event["state"])
                if event.get("log"):
                    summary["message"] = str(event["log"])
    except OSError:
        return summary
    return summary
