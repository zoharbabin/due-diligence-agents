"""Persistent finding corrections for chat-to-pipeline feedback.

When chat discovers a pipeline error (e.g., a finding unsupported by source
documents), it records a correction here.  Corrections persist across chat
sessions and are applied during the next pipeline merge step.

Storage layout::

    _dd/forensic-dd/chat/
        corrections.jsonl          # Append-only finding corrections
"""

from __future__ import annotations

import contextlib
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


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CorrectionAction(StrEnum):
    """Action to take on a finding."""

    DISMISS = "dismiss"
    DOWNGRADE = "downgrade"
    UPGRADE = "upgrade"
    ADJUST = "adjust"


class FindingCorrection(BaseModel):
    """A user/analyst correction to a pipeline finding."""

    id: str = Field(description="Unique ID (UUID hex[:12])")
    timestamp: str = Field(description="ISO-8601 creation time")
    session_id: str = Field(description="Chat session that created this correction")
    finding_id: str = Field(description="ID of the matched finding")
    finding_title: str = Field(description="Title used to match the finding")
    action: CorrectionAction = Field(description="Correction action")
    original_severity: str = Field(default="", description="Original severity before correction")
    new_severity: str | None = Field(default=None, description="New severity (for severity changes)")
    reason: str = Field(description="Analyst justification for the correction")
    subject: str = Field(default="", description="Subject safe name of the finding")
    match_score: float = Field(default=0.0, description="Fuzzy match score (0-100)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_correction_id() -> str:
    """Generate a short unique correction ID."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Correction Store
# ---------------------------------------------------------------------------


class CorrectionStore:
    """Persistent store for finding corrections.

    Parameters
    ----------
    chat_dir:
        Root directory for chat data (``_dd/forensic-dd/chat/``).
    """

    def __init__(self, chat_dir: Path) -> None:
        self._chat_dir = chat_dir
        self._corrections_path = chat_dir / "corrections.jsonl"
        self._corrections_cache: list[FindingCorrection] = []
        self._cache_mtime: float = 0.0

    def ensure_dirs(self) -> None:
        """Create the chat directory if it doesn't exist."""
        self._chat_dir.mkdir(parents=True, exist_ok=True)

    @property
    def correction_count(self) -> int:
        """Total number of stored corrections."""
        self._refresh_cache()
        return len(self._corrections_cache)

    # ----- Write -----

    def save_correction(self, correction: FindingCorrection) -> None:
        """Atomically append a correction to ``corrections.jsonl``."""
        self.ensure_dirs()
        line = correction.model_dump_json() + "\n"

        if self._corrections_path.exists():
            existing = self._corrections_path.read_text(encoding="utf-8")
            new_content = existing + line
        else:
            new_content = line

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._chat_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, self._corrections_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

        self._cache_mtime = 0.0
        logger.debug("Saved correction %s: %s %s", correction.id, correction.action, correction.finding_title[:60])

    # ----- Read -----

    def load_corrections(self, *, subject: str | None = None) -> list[FindingCorrection]:
        """Return all corrections, optionally filtered by subject."""
        self._refresh_cache()
        if subject is None:
            return list(self._corrections_cache)
        return [c for c in self._corrections_cache if c.subject == subject]

    def corrections_by_finding_id(self) -> dict[str, FindingCorrection]:
        """Map finding_id to the latest correction (last-writer-wins)."""
        self._refresh_cache()
        result: dict[str, FindingCorrection] = {}
        for corr in self._corrections_cache:
            result[corr.finding_id] = corr
        return result

    # ----- Matching -----

    @staticmethod
    def match_finding(
        finding_title: str,
        findings: list[dict[str, Any]],
        threshold: int = 65,
    ) -> tuple[dict[str, Any] | None, float]:
        """Fuzzy-match a title against indexed findings.

        Returns ``(matched_finding_dict, score)`` or ``(None, 0.0)``
        if no match meets the *threshold*.
        """
        from rapidfuzz import fuzz

        best_score: float = 0.0
        best_match: dict[str, Any] | None = None
        title_lower = finding_title.lower()

        for f in findings:
            title = f.get("title", "")
            score = fuzz.token_sort_ratio(title_lower, title.lower())
            if score > best_score:
                best_score = score
                best_match = f

        if best_score >= threshold:
            return (best_match, best_score)
        return (None, 0.0)

    # ----- Cache -----

    def _refresh_cache(self) -> None:
        """Reload corrections from disk if the file has been modified."""
        if not self._corrections_path.exists():
            self._corrections_cache = []
            self._cache_mtime = 0.0
            return

        try:
            current_mtime = self._corrections_path.stat().st_mtime
        except OSError:
            return

        if current_mtime <= self._cache_mtime:
            return

        corrections: list[FindingCorrection] = []
        try:
            with self._corrections_path.open(encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        corrections.append(FindingCorrection.model_validate_json(stripped))
                    except Exception:
                        logger.warning("Corrupt correction at line %d — skipping", line_num)
        except OSError as exc:
            logger.warning("Could not read corrections file: %s", exc)
            return

        self._corrections_cache = corrections
        self._cache_mtime = current_mtime
        logger.debug("Refreshed corrections cache: %d corrections", len(corrections))
