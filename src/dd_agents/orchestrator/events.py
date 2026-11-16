"""Append-only run event log (``events.jsonl``).

Writers never raise: progress reporting must not be able to fail a pipeline run.
Readers skip partial last lines and events from a newer schema version.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from dd_agents.models.events import RUN_EVENT_SCHEMA_VERSION, RunEvent, RunEventType

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class RunEventLog:
    """Thread-safe writer. One ``os.write`` per event keeps each line intact."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._seq = self._last_seq()
        self._warned = False

    def _last_seq(self) -> int:
        events = read_events(self.path)
        return events[-1].seq if events else 0

    def reset(self) -> None:
        """Start a fresh log (new run, not a resume)."""
        with self._lock:
            self._seq = 0
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text("", encoding="utf-8")
            except OSError as exc:
                self._warn(exc)

    def emit(
        self,
        type_: RunEventType,
        *,
        run_id: str = "",
        step: str | None = None,
        step_number: int | None = None,
        **data: Any,
    ) -> None:
        """Append one event. Swallows I/O errors (logged once)."""
        with self._lock:
            event = RunEvent(
                seq=self._seq + 1,
                ts=datetime.now(UTC).isoformat(timespec="milliseconds"),
                type=type_,
                run_id=run_id,
                step=step,
                step_number=step_number,
                data=data,
            )
            line = (event.model_dump_json() + "\n").encode("utf-8")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                try:
                    os.write(fd, line)
                finally:
                    os.close(fd)
            except OSError as exc:
                self._warn(exc)
                return
            self._seq = event.seq

    def _warn(self, exc: OSError) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("Run event log unavailable (%s): %s", self.path, exc)


def read_events(path: Path, after_seq: int = 0) -> list[RunEvent]:
    """Read events with ``seq > after_seq``. Missing file is empty. Bad lines are skipped."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    events: list[RunEvent] = []
    for line in raw.splitlines():
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict) or obj.get("schema_version", 0) > RUN_EVENT_SCHEMA_VERSION:
                continue
            event = RunEvent.model_validate(obj)
        except (ValueError, ValidationError):
            continue
        if event.seq > after_seq:
            events.append(event)
    return events
