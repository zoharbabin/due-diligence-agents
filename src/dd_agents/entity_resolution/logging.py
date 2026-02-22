"""Match logging for entity resolution.

Accumulates match results (matches, unmatched, rejected) and writes the
consolidated ``entity_matches.json`` file (FRESH tier, rebuilt every run).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class MatchLogger:
    """Accumulator and writer for the entity match log.

    Collects all resolution outcomes produced by :class:`EntityResolver`
    and serialises them to ``entity_matches.json``.
    """

    def __init__(self) -> None:
        self.matches: list[dict[str, Any]] = []
        self.unmatched: list[dict[str, Any]] = []
        self.rejected: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def add_match(
        self,
        source_name: str,
        source_type: str,
        matched_name: str,
        pass_num: int,
        method: str,
        confidence: float,
        canonical_name: str,
    ) -> None:
        """Record a successful match."""
        self.matches.append(
            {
                "source_name": source_name,
                "source": source_type,
                "matched_name": matched_name,
                "target": "customers.csv",
                "match_pass": pass_num,
                "match_method": method,
                "confidence": confidence,
                "canonical_name": canonical_name,
            }
        )

    def add_unmatched(self, entry: dict[str, Any]) -> None:
        """Record an unmatched entity (pass 6 -- manual review queue)."""
        self.unmatched.append(entry)

    def add_rejected(self, entry: dict[str, Any]) -> None:
        """Record a rejected entity (exclusion list or post-match exclusion)."""
        self.rejected.append(entry)

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_match_log(self) -> dict[str, Any]:
        """Return the complete match log dict for ``entity_matches.json``."""
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "matches": self.matches,
            "unmatched": self.unmatched,
            "rejected": self.rejected,
        }

    def write(self, path: Path) -> dict[str, Any]:
        """Write ``entity_matches.json`` to *path* and return the log dict."""
        log = self.get_match_log()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(log, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return log
