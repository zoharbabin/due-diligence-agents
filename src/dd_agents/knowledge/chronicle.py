"""Append-only JSONL interaction log for analysis timeline (Issue #180).

Every pipeline run, search query, annotation, and knowledge compilation
is logged as an :class:`AnalysisLogEntry` in a JSONL file. This creates
an auditable timeline that can be injected into LLM prompts to provide
historical context ("what has been analyzed before").

Writes are atomic (temp + ``os.replace``) to prevent corruption.
Corrupt lines are skipped on read with a logged warning.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class InteractionType(StrEnum):
    """Type of interaction recorded in the analysis chronicle."""

    PIPELINE_RUN = "pipeline_run"
    SEARCH = "search"
    QUERY = "query"
    ANNOTATION = "annotation"
    KNOWLEDGE_COMPILATION = "knowledge_compilation"


class FindingsSummary(BaseModel):
    """Summary of findings produced by an interaction."""

    total: int = Field(description="Total number of findings")
    p0: int = Field(default=0, description="Priority 0 (critical) findings")
    p1: int = Field(default=0, description="Priority 1 (high) findings")
    p2: int = Field(default=0, description="Priority 2 (medium) findings")
    p3: int = Field(default=0, description="Priority 3 (low) findings")
    new_since_last: int = Field(default=0, description="Findings new since last interaction")


class AnalysisLogEntry(BaseModel):
    """A single entry in the analysis chronicle JSONL file."""

    id: str = Field(description="Unique entry ID (UUID hex prefix)")
    timestamp: str = Field(description="ISO-8601 timestamp of the interaction")
    interaction_type: InteractionType = Field(description="Type of interaction")
    title: str = Field(max_length=200, description="Human-readable title (max 200 chars)")
    details: dict[str, Any] = Field(default_factory=dict, description="Interaction-specific details")
    findings_summary: FindingsSummary | None = Field(default=None, description="Optional findings summary")
    entities_affected: list[str] = Field(default_factory=list, description="Entity safe_names involved")
    duration_seconds: float | None = Field(default=None, description="Wall-clock duration in seconds")
    cost_usd: float | None = Field(default=None, description="Estimated API cost in USD")
    user_initiated: bool = Field(default=False, description="Whether this was triggered by a user")


def _generate_entry_id() -> str:
    """Generate a short unique ID for a log entry."""
    return uuid.uuid4().hex[:12]


class AnalysisChronicle:
    """Append-only JSONL interaction log.

    Every interaction with the due diligence system is recorded as a
    :class:`AnalysisLogEntry` in a JSONL file. The timeline can be
    summarized and injected into LLM prompts for historical context.

    Parameters
    ----------
    log_path:
        Path to the JSONL file (created on first write).
    """

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    @property
    def log_path(self) -> Path:
        """Absolute path to the JSONL log file."""
        return self._log_path

    def append(self, entry: AnalysisLogEntry) -> None:
        """Append a single entry atomically.

        Reads existing content, appends the new line, writes to a temp
        file, then atomically replaces the original via ``os.replace()``.
        """
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if self._log_path.exists():
            existing = self._log_path.read_text(encoding="utf-8")

        new_line = entry.model_dump_json() + "\n"
        content = existing + new_line

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._log_path.parent),
            suffix=".tmp",
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, str(self._log_path))
        except Exception:
            os.close(fd) if not _is_closed(fd) else None  # noqa: B018
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _read_all(self) -> list[AnalysisLogEntry]:
        """Read all valid entries from the JSONL file.

        Corrupt lines are skipped with a warning.
        """
        if not self._log_path.exists():
            return []

        entries: list[AnalysisLogEntry] = []
        for line_num, line in enumerate(
            self._log_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                entries.append(AnalysisLogEntry.model_validate(data))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping corrupt line %d in %s: %s", line_num, self._log_path, exc)
        return entries

    def read_recent(self, limit: int = 20) -> list[AnalysisLogEntry]:
        """Return the last *limit* entries (most recent last)."""
        entries = self._read_all()
        return entries[-limit:]

    def read_by_type(self, interaction_type: InteractionType) -> list[AnalysisLogEntry]:
        """Return all entries of a given interaction type."""
        return [e for e in self._read_all() if e.interaction_type == interaction_type]

    def read_for_entity(self, entity_safe_name: str) -> list[AnalysisLogEntry]:
        """Return all entries where *entity_safe_name* is in entities_affected."""
        return [e for e in self._read_all() if entity_safe_name in e.entities_affected]

    def generate_timeline_summary(self, max_chars: int = 5000) -> str:
        """Generate a human-readable timeline summary for LLM prompt enrichment.

        Format per line::

            [2026-03-07 14:30] Pipeline Run (full) — 15 customers, 200 documents

        Returns
        -------
        str
            Timeline text, truncated to *max_chars* from the most recent end.
        """
        entries = self._read_all()
        if not entries:
            return "No analysis history recorded."

        lines: list[str] = []
        for entry in entries:
            ts = entry.timestamp[:16].replace("T", " ")
            detail_parts: list[str] = []
            if entry.findings_summary:
                detail_parts.append(f"{entry.findings_summary.total} findings")
            if entry.entities_affected:
                detail_parts.append(f"{len(entry.entities_affected)} entities")
            if entry.duration_seconds is not None:
                detail_parts.append(f"{entry.duration_seconds:.0f}s")
            suffix = " — " + ", ".join(detail_parts) if detail_parts else ""
            lines.append(f"[{ts}] {entry.title}{suffix}")

        # Truncate from the beginning to fit within max_chars
        result = "\n".join(lines)
        if len(result) <= max_chars:
            return result

        # Keep the most recent entries
        truncated_lines: list[str] = []
        remaining = max_chars - len("... (earlier entries truncated)\n")
        for line in reversed(lines):
            if remaining < len(line):
                break
            truncated_lines.insert(0, line)
            remaining -= len(line) + 1  # +1 for newline

        return "... (earlier entries truncated)\n" + "\n".join(truncated_lines)

    def get_stats(self) -> dict[str, Any]:
        """Compute summary statistics over the chronicle.

        Returns
        -------
        dict
            Keys: ``total_entries``, ``by_type``, ``date_range``,
            ``entity_coverage``.
        """
        entries = self._read_all()

        by_type: dict[str, int] = {}
        entities: set[str] = set()
        timestamps: list[str] = []

        for entry in entries:
            key = entry.interaction_type.value
            by_type[key] = by_type.get(key, 0) + 1
            entities.update(entry.entities_affected)
            timestamps.append(entry.timestamp)

        date_range: dict[str, str | None] = {"earliest": None, "latest": None}
        if timestamps:
            date_range["earliest"] = min(timestamps)
            date_range["latest"] = max(timestamps)

        return {
            "total_entries": len(entries),
            "by_type": by_type,
            "date_range": date_range,
            "entity_coverage": sorted(entities),
        }


def _is_closed(fd: int) -> bool:
    """Check if a file descriptor is already closed."""
    try:
        os.fstat(fd)
        return False
    except OSError:
        return True
