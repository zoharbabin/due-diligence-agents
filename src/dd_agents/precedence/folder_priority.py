"""Folder priority classification for data room directories.

Classifies folder names into trust tiers based on naming patterns.
Configurable via deal-config.json overrides.
"""

from __future__ import annotations

from enum import IntEnum


class FolderTier(IntEnum):
    """Trust tier for a data room folder. Lower number = more authoritative."""

    AUTHORITATIVE = 1
    WORKING = 2
    SUPPLEMENTARY = 3
    HISTORICAL = 4

    @property
    def score(self) -> float:
        """Numeric score for the tier (higher = more authoritative)."""
        return {1: 1.0, 2: 0.7, 3: 0.4, 4: 0.2}[int(self)]


# Default patterns per tier (lowercase substrings matched against folder names)
DEFAULT_FOLDER_TIERS: dict[int, list[str]] = {
    1: [
        "executed",
        "signed",
        "final",
        "closing binder",
        "closing set",
        "definitive",
        "closing",
    ],
    2: [
        "current",
        "active",
        "latest",
    ],
    3: [
        "draft",
        "working",
        "internal",
        "notes",
        "wip",
        "redline",
        "markup",
        "comments",
        "track changes",
    ],
    4: [
        "archive",
        "old",
        "prior",
        "legacy",
        "superseded",
        "historical",
        "backup",
        "deprecated",
    ],
}


class FolderPriorityClassifier:
    """Classifies folder names into trust tiers.

    Parameters
    ----------
    overrides:
        User-provided folder-name → tier mapping from deal-config.json.
        Keys are folder names (case-insensitive), values are tier integers (1-4).
    """

    def __init__(self, overrides: dict[str, int] | None = None) -> None:
        self._overrides: dict[str, int] = {k.lower(): v for k, v in (overrides or {}).items()}
        self._tier_patterns = DEFAULT_FOLDER_TIERS

    def classify(self, folder_name: str) -> FolderTier:
        """Classify a single folder name into a trust tier."""
        lower = folder_name.lower().strip()

        # Check user overrides first
        if lower in self._overrides:
            return FolderTier(self._overrides[lower])

        # Check default patterns
        for tier, patterns in self._tier_patterns.items():
            for pattern in patterns:
                if pattern in lower:
                    return FolderTier(tier)

        # Default: working tier
        return FolderTier.WORKING

    def classify_path(self, rel_path: str) -> FolderTier:
        """Classify a relative path by examining all directory components.

        If any component matches a non-default pattern (authoritative,
        supplementary, or historical), that tier is returned.  Among multiple
        non-default matches, the most authoritative (lowest-numbered) wins.
        If no component matches a special pattern, returns WORKING.
        """
        parts = rel_path.replace("\\", "/").split("/")
        non_default: list[FolderTier] = []
        for part in parts:
            tier = self.classify(part)
            if tier != FolderTier.WORKING:
                non_default.append(tier)
        if non_default:
            return min(non_default)
        return FolderTier.WORKING
