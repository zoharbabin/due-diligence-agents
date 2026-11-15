"""Which pages of a PDF have no usable text layer and need OCR.

A mixed PDF has text pages and scanned pages. Extracting text alone returns
the text pages and silently loses the rest. This module finds the gap pages
so the pipeline can OCR only those.

``pdf-inspector`` (optional extra ``pdf-fast``) classifies each page and is
used when installed. Without it, a page with almost no text counts as scanned.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger(__name__)

# A page with fewer non-space characters than this has no usable text layer.
MIN_PAGE_TEXT_CHARS = 20
# OCR is slow. Never route more pages than this per document.
MAX_OCR_PAGES = 50


# A small OCR model can get stuck and repeat the same lines until it hits its token cap.
# A page where one long line appears this many times is treated as looping.
LOOP_MIN_LINE_CHARS = 20
LOOP_MIN_REPEATS = 4


def collapse_repeats(text: str) -> tuple[str, bool]:
    """Drop repeated lines from OCR output that looped. Returns ``(text, looped)``.

    Only acts when a line of at least :data:`LOOP_MIN_LINE_CHARS` characters
    appears :data:`LOOP_MIN_REPEATS` times or more. Then every repeat of a long
    line is dropped. Text that does not loop is returned unchanged.
    """
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        key = line.strip()
        if len(key) >= LOOP_MIN_LINE_CHARS:
            counts[key] = counts.get(key, 0) + 1
    if not any(n >= LOOP_MIN_REPEATS for n in counts.values()):
        return text, False
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        key = line.strip()
        if len(key) >= LOOP_MIN_LINE_CHARS:
            if key in seen:
                continue
            seen.add(key)
        kept.append(line)
    return "\n".join(kept), True


def pages_from_text(page_texts: Sequence[str]) -> list[int]:
    """1-based pages whose text layer is empty or nearly empty."""
    return [n for n, text in enumerate(page_texts, start=1) if len("".join(text.split())) < MIN_PAGE_TEXT_CHARS]


def _inspector_pages(path: Path) -> list[int] | None:
    """1-based pages ``pdf-inspector`` says need OCR. ``None`` if it is missing or cannot read the file."""
    try:
        import pdf_inspector
    except ImportError:
        return None
    try:
        result = pdf_inspector.classify_pdf(str(path))
    except Exception as exc:  # the library raises ValueError on damaged files
        logger.debug("pdf-inspector could not classify %s: %s", path.name, exc)
        return None
    return sorted(n + 1 for n in result.pages_needing_ocr)  # it reports 0-based pages


def pages_needing_ocr(path: Path, page_texts: Sequence[str]) -> list[int]:
    """1-based pages to OCR, at most :data:`MAX_OCR_PAGES`."""
    pages = _inspector_pages(path)
    if pages is None:
        pages = pages_from_text(page_texts)
    return pages[:MAX_OCR_PAGES]
