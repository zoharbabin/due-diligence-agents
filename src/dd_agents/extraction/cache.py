"""Checksum-based extraction cache for skip-on-match re-runs.

Uses SHA-256 hashes to detect changed files and skip re-extraction of
unchanged documents.  The cache file lives in the PERMANENT tier at
``_dd/forensic-dd/index/checksums.sha256``.

File format (standard ``sha256sum`` compatible)::

    a1b2c3d4...  ./Above 200K USD/Acme Corp/MSA.pdf
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Default chunk size for reading files during hashing (8 KiB).
_HASH_CHUNK_SIZE = 8192


class ExtractionCache:
    """Manages the ``checksums.sha256`` file for extraction caching.

    Parameters
    ----------
    cache_path:
        Absolute path to the ``checksums.sha256`` file.  The parent
        directory is created automatically on :meth:`save`.
    """

    def __init__(self, cache_path: Path) -> None:
        self._path = cache_path
        # {filepath_str: sha256_hex}
        self._entries: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load existing checksum entries from disk.

        Silently starts with an empty cache if the file does not exist
        or cannot be parsed.
        """
        self._entries.clear()
        if not self._path.exists():
            return
        try:
            text = self._path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    hash_val, filepath = parts
                    self._entries[filepath] = hash_val
        except OSError:
            logger.warning("Could not read checksum cache at %s", self._path)

    def save(self) -> None:
        """Persist the current cache to disk.

        Creates parent directories as needed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for filepath in sorted(self._entries):
            lines.append(f"{self._entries[filepath]}  {filepath}")
        self._path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @staticmethod
    def compute_checksum(filepath: Path) -> str:
        """Compute the SHA-256 hex digest of *filepath*.

        Raises
        ------
        FileNotFoundError
            If *filepath* does not exist.
        """
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def is_cached(self, filepath: str, current_hash: str | None = None) -> bool:
        """Return ``True`` if *filepath* is in the cache **and** its hash matches.

        Parameters
        ----------
        filepath:
            The file path key (e.g. ``./Above 200K/Acme/MSA.pdf``).
        current_hash:
            Pre-computed SHA-256 hex.  If ``None`` the method only checks
            whether the path exists in the cache (useful for quick lookups).
        """
        cached_hash = self._entries.get(filepath)
        if cached_hash is None:
            return False
        if current_hash is None:
            return True
        return cached_hash == current_hash

    def update(self, filepath: str, hash_val: str) -> None:
        """Add or update a cache entry for *filepath*."""
        self._entries[filepath] = hash_val

    def remove_stale(self, current_files: set[str] | list[str]) -> int:
        """Remove entries whose paths are no longer in *current_files*.

        Returns the number of stale entries removed.
        """
        current = set(current_files)
        stale_keys = [k for k in self._entries if k not in current]
        for k in stale_keys:
            del self._entries[k]
        return len(stale_keys)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get(self, filepath: str) -> str | None:
        """Return the cached hash for *filepath*, or ``None``."""
        return self._entries.get(filepath)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, filepath: str) -> bool:
        return filepath in self._entries
