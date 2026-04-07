"""Shared helpers for the extraction package."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dd_agents.extraction._constants import CONFIDENCE_FAILURE, CONFIDENCE_FALLBACK_READ

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def read_text(filepath: Path) -> tuple[str, float]:
    """Read *filepath* as plain text (UTF-8, then latin-1).

    Returns ``(text, 0.5)`` on success, ``("", 0.0)`` on failure.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            text = filepath.read_text(encoding=encoding, errors="replace")
            if text.strip():
                if encoding != "utf-8":
                    logger.debug("Fell back to %s encoding for %s", encoding, filepath.name)
                return text, CONFIDENCE_FALLBACK_READ
        except (OSError, UnicodeDecodeError):
            continue
    return "", CONFIDENCE_FAILURE
