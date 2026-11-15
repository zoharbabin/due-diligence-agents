"""Optional fast Office-to-markdown backend (``extraction.office_backend: "anydoc"``).

Uses the ``anydoc`` module from the ``firecrawl-anydoc`` package
(``pip install "dd-agents[office-fast]"``). The import is lazy. When the
package is missing, :func:`extract` logs one warning and returns no text, so
the pipeline falls back to markitdown.

Only .docx, .pptx and .xlsx are routed here. ``anydoc`` has no HTML reader.
OCR is always ``"reject"``: ``anydoc``'s ``"hosted"`` mode uploads the file to
a third-party API and is never used.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from dd_agents.extraction._constants import CONFIDENCE_ANYDOC, CONFIDENCE_FAILURE

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

ANYDOC_EXTENSIONS: frozenset[str] = frozenset({".docx", ".pptx", ".xlsx"})

_warn_lock = threading.Lock()
_warned_missing = False


def _warn_missing_once() -> None:
    global _warned_missing
    with _warn_lock:
        if _warned_missing:
            return
        _warned_missing = True
    logger.warning(
        "extraction.office_backend is 'anydoc' but the package is not installed. "
        'Falling back to markitdown. Install with: pip install "dd-agents[office-fast]"'
    )


def _reset_warning_for_tests() -> None:
    global _warned_missing
    with _warn_lock:
        _warned_missing = False


def extract(filepath: Path) -> tuple[str, float]:
    """Convert *filepath* with ``anydoc``. Returns ``("", 0.0)`` on any failure."""
    try:
        import anydoc
    except ImportError:
        _warn_missing_once()
        return "", CONFIDENCE_FAILURE

    try:
        text = str(anydoc.to_markdown(str(filepath), ocr="reject"))
    except Exception as exc:
        logger.debug("anydoc failed for %s: %s: %s", filepath.name, type(exc).__name__, exc)
        return "", CONFIDENCE_FAILURE

    if text and text.strip():
        return text, CONFIDENCE_ANYDOC
    return "", CONFIDENCE_FAILURE
