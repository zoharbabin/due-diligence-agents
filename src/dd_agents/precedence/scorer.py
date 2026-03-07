"""Composite precedence score computation for data room files.

Combines version rank, folder tier, and recency into a single 0-1 score
that flows through agent prompts and merge decisions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.precedence.folder_priority import FolderTier

if TYPE_CHECKING:
    from dd_agents.models.inventory import FileEntry

# Weight allocation for the three components
_W_VERSION: float = 0.4
_W_FOLDER: float = 0.3
_W_RECENCY: float = 0.3

# Maximum version rank (for normalization)
_MAX_VERSION_RANK: float = 10.0


class PrecedenceScorer:
    """Computes a composite precedence score for each file."""

    def compute_score(self, entry: FileEntry, max_mtime: float) -> float:
        """Compute a 0-1 precedence score for a single file.

        Parameters
        ----------
        entry:
            The file entry with version_rank, folder_tier, and mtime populated.
        max_mtime:
            The maximum mtime across all files in the dataset (for normalization).

        Returns
        -------
        float
            Score in [0, 1].  Higher = more authoritative.
        """
        # Version component: normalize rank to [0, 1]
        version_score = min(entry.version_rank / _MAX_VERSION_RANK, 1.0) if entry.version_rank > 0 else 0.5

        # Folder component: use the tier's score directly
        try:
            folder_score = FolderTier(entry.folder_tier).score
        except ValueError:
            folder_score = FolderTier.WORKING.score

        # Recency component: normalize mtime to [0, 1] relative to max
        if max_mtime > 0 and entry.mtime > 0:
            recency_score = entry.mtime / max_mtime
        elif entry.mtime > 0:
            recency_score = 0.5
        else:
            recency_score = 0.0

        return _W_VERSION * version_score + _W_FOLDER * folder_score + _W_RECENCY * recency_score

    def score_batch(self, entries: list[FileEntry]) -> list[FileEntry]:
        """Compute precedence scores for a batch of files in-place.

        Automatically determines ``max_mtime`` from the batch.

        Returns
        -------
        list[FileEntry]
            The same list with ``precedence_score`` populated on each entry.
        """
        max_mtime = max((e.mtime for e in entries), default=0.0)
        for entry in entries:
            entry.precedence_score = round(self.compute_score(entry, max_mtime), 4)
        return entries
