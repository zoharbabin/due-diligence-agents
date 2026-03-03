"""Cross-document entity deduplication.

Groups resolved entities by canonical name across source files,
tracking mention counts and variant names.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class CrossDocumentDeduplicator:
    """Groups resolved entities by canonical name across source files.

    Tracks: canonical -> {source_files, mention_count, variants}
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def add_resolution(
        self,
        source_name: str,
        canonical_name: str,
        source_file: str,
    ) -> None:
        """Record a resolution from *source_name* to *canonical_name* in *source_file*."""
        if canonical_name not in self._entries:
            self._entries[canonical_name] = {
                "canonical": canonical_name,
                "source_files": set(),
                "mention_count": 0,
                "variants": set(),
            }
        entry = self._entries[canonical_name]
        entry["source_files"].add(source_file)
        entry["mention_count"] += 1
        if source_name != canonical_name:
            entry["variants"].add(source_name)

    def get_summary(self) -> dict[str, Any]:
        """Return the deduplication summary as a serializable dict."""
        result: dict[str, Any] = {}
        for canonical, entry in sorted(self._entries.items()):
            result[canonical] = {
                "canonical": entry["canonical"],
                "source_files": sorted(entry["source_files"]),
                "mention_count": entry["mention_count"],
                "variants": sorted(entry["variants"]),
            }
        return result

    def write_summary(self, path: Path) -> None:
        """Write the dedup summary to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.get_summary(), indent=2))
