"""Version chain detection: group files by base name, order by version/date/tier.

Detects version indicators in filenames (v1, v2, final, signed, draft, etc.),
groups related files, orders them by authority, and marks superseded files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dd_agents.models.inventory import FileEntry

# ---------------------------------------------------------------------------
# Version keyword rankings (higher = more authoritative)
# ---------------------------------------------------------------------------

_KEYWORD_RANKS: dict[str, int] = {
    "signed": 10,
    "executed": 10,
    "final": 9,
    "definitive": 9,
    "closing": 8,
    "amended": 7,
    "current": 6,
    "redline": 3,
    "markup": 3,
    "track changes": 3,
    "draft": 2,
    "wip": 2,
    "superseded": 1,
    "void": 1,
    "old": 1,
    "expired": 1,
    "deprecated": 1,
}

_NEUTRAL_RANK = 5  # default when no keyword found

# Regex for explicit version numbers: v1, v2, v10, V3, etc.
# Use lookbehind/ahead instead of \b since _ is a word char.
_VERSION_NUM_RE = re.compile(r"(?:^|[_\-\s.])v(\d+)(?=[_\-\s.]|$)", re.IGNORECASE)

# Regex to strip version indicators and common suffixes for base-name comparison
_STRIP_RE = re.compile(
    r"[_\-\s]*(v\d+|signed|executed|final|definitive|closing|amended|current|"
    r"redline|markup|draft|wip|superseded|void|old|expired|deprecated|copy)[_\-\s]*",
    re.IGNORECASE,
)


def parse_version_indicator(filename: str) -> tuple[str, int]:
    """Parse version indicator and rank from a filename.

    Returns
    -------
    tuple[str, int]
        (indicator_name, rank).  Empty string and neutral rank if none found.
    """
    lower = filename.lower()

    # Check keywords (highest rank wins)
    best_keyword = ""
    best_rank = -1
    for keyword, rank in _KEYWORD_RANKS.items():
        if keyword in lower and rank > best_rank:
            best_keyword = keyword
            best_rank = rank

    if best_keyword:
        return best_keyword, best_rank

    # Check for explicit version number
    match = _VERSION_NUM_RE.search(lower)
    if match:
        version_num = int(match.group(1))
        return f"v{version_num}", version_num

    return "", _NEUTRAL_RANK


def _base_name(path: str) -> str:
    """Extract a normalized base name for grouping.

    Strips version indicators, extensions, and normalizes separators
    so that ``MSA_v1.pdf`` and ``MSA_v2_signed.pdf`` share the same base.
    """
    # Take filename only (strip directory)
    filename = path.rsplit("/", 1)[-1] if "/" in path else path

    # Strip extension
    dot_idx = filename.rfind(".")
    if dot_idx > 0:
        filename = filename[:dot_idx]

    # Strip version indicators
    cleaned = _STRIP_RE.sub("_", filename)

    # Normalize: lowercase, collapse underscores/spaces/hyphens
    cleaned = re.sub(r"[_\-\s]+", "_", cleaned.lower()).strip("_")

    return cleaned


def _customer_prefix(path: str) -> str:
    """Extract the customer directory prefix from a path.

    For ``GroupA/CustomerX/file.pdf`` returns ``GroupA/CustomerX``.
    For ``file.pdf`` returns ``""`` (root-level file).
    """
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 1:
        return ""
    return "/".join(parts[:-1])


@dataclass
class VersionGroup:
    """A group of related files ordered by precedence (most authoritative first)."""

    base_name: str
    customer_prefix: str
    files: list[FileEntry] = field(default_factory=list)


class VersionChainBuilder:
    """Detects version chains among files and marks superseded ones.

    Groups files by normalized base name within each customer directory,
    orders by version rank → folder tier → mtime, and marks all but the
    first (most authoritative) as superseded.
    """

    def __init__(self, similarity_threshold: int = 85) -> None:
        self._threshold = similarity_threshold

    def build_chains(self, entries: list[FileEntry]) -> list[VersionGroup]:
        """Build version chains from a list of FileEntry objects.

        Mutates the FileEntry objects in-place to set ``version_indicator``,
        ``version_rank``, ``is_latest_version``, and ``superseded_by``.

        Returns
        -------
        list[VersionGroup]
            Groups of related files, each ordered most-authoritative-first.
        """
        # Pre-populate version indicators from filenames
        for entry in entries:
            if not entry.version_indicator:
                indicator, rank = parse_version_indicator(entry.path)
                entry.version_indicator = indicator
                entry.version_rank = rank

        # Group by (customer_prefix, base_name)
        groups_map: dict[tuple[str, str], list[FileEntry]] = {}
        for entry in entries:
            prefix = _customer_prefix(entry.path)
            base = _base_name(entry.path)
            key = (prefix, base)
            groups_map.setdefault(key, []).append(entry)

        result: list[VersionGroup] = []
        for (prefix, base), files in groups_map.items():
            # Sort: highest version_rank first, then lowest folder_tier
            # (lower tier = more authoritative), then newest mtime
            sorted_files = sorted(
                files,
                key=lambda f: (
                    -f.version_rank,
                    f.folder_tier,
                    -f.mtime,
                ),
            )

            # Mark latest and superseded
            if sorted_files:
                latest = sorted_files[0]
                latest.is_latest_version = True
                latest.superseded_by = ""

                for older in sorted_files[1:]:
                    older.is_latest_version = False
                    older.superseded_by = latest.path

            result.append(VersionGroup(base_name=base, customer_prefix=prefix, files=sorted_files))

        return result
