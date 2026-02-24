"""Shared helpers for the extraction package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.extraction._constants import CONFIDENCE_FAILURE, CONFIDENCE_FALLBACK_READ

if TYPE_CHECKING:
    from pathlib import Path


def read_text(filepath: Path) -> tuple[str, float]:
    """Read *filepath* as plain text (UTF-8, then latin-1).

    Returns ``(text, 0.5)`` on success, ``("", 0.0)`` on failure.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            text = filepath.read_text(encoding=encoding, errors="replace")
            if text.strip():
                return text, CONFIDENCE_FALLBACK_READ
        except (OSError, UnicodeDecodeError):
            continue
    return "", CONFIDENCE_FAILURE
