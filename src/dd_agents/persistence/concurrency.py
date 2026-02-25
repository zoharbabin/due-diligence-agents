"""Optimistic concurrency control for PERMANENT-tier shared files.

PERMANENT-tier files (``entity_resolution_cache.json``, ``run_history.json``,
``checksums.sha256``) are accessed by multiple pipeline runs.  When concurrent
runs modify these files simultaneously, data can be lost or corrupted.

This module provides :func:`read_validate_write`, an optimistic-concurrency
utility that detects mid-flight changes and retries transparently.

Algorithm
---------
1. Read the file and compute a SHA-256 checksum.
2. Apply the caller-supplied *transform* function.
3. Re-read the file and verify the checksum has not changed.
4. If unchanged, write atomically (temp file + ``os.replace``).
5. If changed (another process wrote), retry from step 1.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


class ConcurrentModificationError(Exception):
    """Raised when all retries are exhausted due to concurrent modifications."""


def _file_checksum(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*, or empty string if missing."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_validate_write(
    file_path: Path,
    transform: Callable[[dict[str, object]], dict[str, object]],
    max_retries: int = 1,
) -> bool:
    """Safely update a shared JSON file with optimistic concurrency.

    Parameters
    ----------
    file_path:
        Path to the JSON file to update.  If the file does not exist, an
        empty dict ``{}`` is passed to *transform* and the file is created.
    transform:
        A function that receives the current file contents as a dict and
        returns the new dict to write.  Must be side-effect-free (it may
        be called multiple times on retry).
    max_retries:
        Maximum number of retries when a concurrent modification is
        detected.  ``0`` means try once with no retries; ``1`` (the
        default) means try once plus one retry.

    Returns
    -------
    bool
        ``True`` if the write succeeded, ``False`` is never returned --
        on exhausted retries :class:`ConcurrentModificationError` is raised.

    Raises
    ------
    ConcurrentModificationError
        If the file was modified by another process on every attempt.
    """
    attempts = max_retries + 1  # total attempts = retries + 1

    for attempt in range(attempts):
        # Step 1: Read file bytes ONCE and derive both checksum and
        # parsed JSON from the same snapshot, avoiding a TOCTOU race
        # between separate checksum and read_text calls.
        if file_path.exists():
            try:
                raw_bytes = file_path.read_bytes()
                checksum_before = hashlib.sha256(raw_bytes).hexdigest()
                data: dict[str, object] = json.loads(raw_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # JSON is corrupt but we already read the bytes — reuse them
                # for the checksum to avoid a second read (TOCTOU).
                checksum_before = hashlib.sha256(raw_bytes).hexdigest()
                data = {}
            except OSError:
                # File disappeared or became unreadable after exists() check.
                checksum_before = ""
                data = {}
        else:
            checksum_before = ""
            data = {}

        # Step 2: Apply transform
        new_data = transform(data)

        # Step 3: Re-read and verify checksum
        checksum_after = _file_checksum(file_path)

        if checksum_before != checksum_after:
            # Another process modified the file between our read and now.
            logger.warning(
                "Concurrent modification detected on %s (attempt %d/%d)",
                file_path.name,
                attempt + 1,
                attempts,
            )
            continue  # Retry from step 1

        # Step 4: Write atomically
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(new_data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(file_path))
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.debug("Successfully wrote %s (attempt %d)", file_path.name, attempt + 1)
        return True

    # All retries exhausted
    raise ConcurrentModificationError(
        f"Failed to write {file_path} after {attempts} attempt(s) due to concurrent modifications."
    )
