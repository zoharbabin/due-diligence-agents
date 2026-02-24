"""Extraction quality tracking -- records how each file was extracted.

Produces ``extraction_quality.json`` in the PERMANENT tier so that
downstream agents and audits know the provenance of every extracted
document.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.models.inventory import ExtractionQualityEntry

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class ExtractionQualityTracker:
    """Accumulates per-file extraction quality and persists to JSON.

    Each entry is an :class:`ExtractionQualityEntry` (from
    ``dd_agents.models.inventory``).  The tracker also exposes
    aggregate statistics via :meth:`get_stats`.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ExtractionQualityEntry] = {}
        # Parallel timestamps dict -- not part of the pydantic model but
        # written into the JSON for auditability.
        self._timestamps: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        filepath: str,
        method: str,
        bytes_extracted: int,
        confidence: float,
        fallback_chain: list[str] | None = None,
        failure_reasons: list[str] | None = None,
    ) -> ExtractionQualityEntry:
        """Record extraction quality for a single file.

        Parameters
        ----------
        filepath:
            Source file path (relative, e.g. ``./Acme/MSA.pdf``).
        method:
            The extraction method that produced the final output.
        bytes_extracted:
            Number of bytes in the extracted text.
        confidence:
            Confidence score ``[0.0, 1.0]``.
        fallback_chain:
            Ordered list of methods attempted (including the final one).
        failure_reasons:
            Diagnostic strings for each gate failure in the chain.

        Returns
        -------
        ExtractionQualityEntry
            The recorded entry.
        """
        entry = ExtractionQualityEntry(
            file_path=filepath,
            method=method,
            bytes_extracted=bytes_extracted,
            confidence=confidence,
            fallback_chain=fallback_chain or [method],
            failure_reasons=failure_reasons or [],
        )
        self._entries[filepath] = entry
        self._timestamps[filepath] = datetime.now(UTC).isoformat()
        return entry

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Write all entries to *path* as JSON.

        Creates parent directories as needed.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, dict[str, Any]] = {}
        for fp, entry in sorted(self._entries.items()):
            d = entry.model_dump()
            d["timestamp"] = self._timestamps.get(fp, datetime.now(UTC).isoformat())
            data[fp] = d
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def load(self, path: Path) -> None:
        """Load entries from an existing ``extraction_quality.json``.

        Silently resets to empty if the file does not exist or is
        malformed.
        """
        self._entries.clear()
        self._timestamps.clear()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for fp, d in raw.items():
                ts = d.pop("timestamp", None)
                self._entries[fp] = ExtractionQualityEntry(**d)
                if ts:
                    self._timestamps[fp] = ts
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
            logger.warning("Could not load extraction quality from %s: %s", path, exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate extraction statistics.

        Returns a dict with keys:

        - ``total`` -- number of tracked files
        - ``by_method`` -- ``{method: count}``
        - ``avg_confidence`` -- mean confidence across all entries
        - ``total_bytes`` -- sum of extracted bytes
        - ``failed`` -- count of entries with confidence == 0.0
        """
        total = len(self._entries)
        by_method: dict[str, int] = {}
        total_confidence = 0.0
        total_bytes = 0
        failed = 0

        for entry in self._entries.values():
            by_method[entry.method] = by_method.get(entry.method, 0) + 1
            total_confidence += entry.confidence
            total_bytes += entry.bytes_extracted
            if entry.confidence == 0.0:
                failed += 1

        return {
            "total": total,
            "by_method": by_method,
            "avg_confidence": (total_confidence / total) if total else 0.0,
            "total_bytes": total_bytes,
            "failed": failed,
        }

    @property
    def entries(self) -> list[ExtractionQualityEntry]:
        """Return all entries as a list (ordered by filepath)."""
        return [self._entries[k] for k in sorted(self._entries)]

    def __len__(self) -> int:
        return len(self._entries)
