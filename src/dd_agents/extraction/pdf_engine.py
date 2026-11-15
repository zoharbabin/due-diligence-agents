"""PDF engine: the only module that talks to PDFium (``pypdfium2``).

Three operations, all serialised through :data:`PDF_LOCK` because PDFium is
not thread-safe:

- :func:`probe` -- encryption flag, page count and first-page text, used to
  classify a PDF before extraction.
- :func:`extract_pages` -- text per page.
- :func:`extract_blocks` -- text blocks with page coordinates (top-left
  origin, points). Wrapped lines form one block,
  table cells separated by a wide gap form separate blocks.

Files PDFium cannot open (truncated downloads, broken cross-reference
tables) are repaired in memory with ``pikepdf`` (qpdf) and retried once.
"""

from __future__ import annotations

import io
import logging
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# PDFium is not thread-safe. Every call into it, in any module, takes this lock.
PDF_LOCK = threading.RLock()

# A horizontal gap wider than this many line-heights splits a line into cells.
_CELL_GAP_FACTOR = 1.5
# Max vertical gap (in line-heights) for a line to join the block above it.
_LINE_JOIN_FACTOR = 0.8
# Max left-edge drift (points) for a line to join the block above it.
_LEFT_EDGE_TOLERANCE = 3.0
# Only the most recent blocks are candidates for stacking a line onto.
_STACK_WINDOW = 60

_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_LINE_CONTENT = re.compile(r"[^\r\n]+")


class PdfError(Exception):
    """The PDF could not be opened or read."""


class PdfEncryptedError(PdfError):
    """The PDF needs a password."""


@dataclass(frozen=True)
class PdfProbe:
    """What the pipeline needs to classify a PDF."""

    encrypted: bool
    page_count: int
    first_page_text: str


@dataclass(frozen=True)
class PdfBlock:
    """A text block. Coordinates are points from the top-left of the page."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def _pdfium() -> Any:
    try:
        import pypdfium2
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise PdfError("pypdfium2 is not installed (pip install 'dd-agents[pdf]')") from exc
    return pypdfium2


def _repair(path: Path) -> bytes | None:
    """Rewrite a damaged PDF with qpdf (via ``pikepdf``). ``None`` if that fails too."""
    try:
        import pikepdf
    except ImportError:
        return None
    try:
        with pikepdf.open(path) as pdf:
            out = io.BytesIO()
            pdf.save(out)
        return out.getvalue()
    except Exception as exc:
        logger.debug("pikepdf could not repair %s: %s", path, exc)
        return None


def _open(path: Path) -> Any:
    """Open *path*; caller holds :data:`PDF_LOCK` and closes the document."""
    pdfium = _pdfium()
    try:
        return pdfium.PdfDocument(str(path))
    except Exception as exc:
        if getattr(exc, "err_code", None) == pdfium.raw.FPDF_ERR_PASSWORD:
            raise PdfEncryptedError(f"{path.name} is password protected") from exc
        first = exc
    repaired = _repair(path)
    if repaired is not None:
        try:
            return pdfium.PdfDocument(repaired)
        except Exception as exc:
            first = exc
    raise PdfError(f"cannot open {path.name}: {first}") from first


def probe(path: Path) -> PdfProbe:
    """Return encryption flag, page count and first-page text.

    A password-protected file yields ``encrypted=True`` (no exception).
    Raises :class:`PdfError` if the file cannot be read at all.
    """
    with PDF_LOCK:
        try:
            doc = _open(path)
        except PdfEncryptedError:
            return PdfProbe(encrypted=True, page_count=0, first_page_text="")
        try:
            count = len(doc)
            if count == 0:
                return PdfProbe(encrypted=False, page_count=0, first_page_text="")
            return PdfProbe(encrypted=False, page_count=count, first_page_text=_page_text(doc[0]))
        finally:
            doc.close()


def extract_pages(path: Path) -> list[str]:
    """Return the text of every page. Raises :class:`PdfError` on failure."""
    with PDF_LOCK:
        doc = _open(path)
        try:
            return [_page_text(page) for page in doc]
        finally:
            doc.close()


def extract_blocks(path: Path) -> list[PdfBlock]:
    """Return text blocks for every page. Raises :class:`PdfError` on failure."""
    blocks: list[PdfBlock] = []
    with PDF_LOCK:
        doc = _open(path)
        try:
            for number, page in enumerate(doc, start=1):
                blocks.extend(_page_blocks(page, number))
        finally:
            doc.close()
    return blocks


# ---------------------------------------------------------------------------
# Page-level helpers (caller holds PDF_LOCK)
# ---------------------------------------------------------------------------


def _page_text(page: Any) -> str:
    textpage = page.get_textpage()
    try:
        text: str = textpage.get_text_range()
    finally:
        textpage.close()
        page.close()
    return _LINE_BREAK.sub("\n", text)


def _page_blocks(page: Any, number: int) -> list[PdfBlock]:
    height = page.get_height()
    textpage = page.get_textpage()
    try:
        text: str = textpage.get_text_range()
        segments: list[list[Any]] = []
        for line in _LINE_CONTENT.finditer(text):
            if line.group().strip():
                segments.extend(_line_segments(textpage, text, line.start(), len(line.group()), height))
    finally:
        textpage.close()
        page.close()
    return [PdfBlock(number, b[0], b[1], b[2], b[3], b[4]) for b in _stack(segments)]


def _line_segments(textpage: Any, text: str, start: int, length: int, page_height: float) -> list[list[Any]]:
    """Split one text line into cell segments: ``[x0, y0, x1, y1, text]``."""
    boxes: list[tuple[str, tuple[float, float, float, float] | None]] = []
    for i in range(start, start + length):
        ch = text[i]
        boxes.append((ch, textpage.get_charbox(i, loose=False) if ch.strip() else None))
    heights = [b[3] - b[1] for _, b in boxes if b]
    if not heights:
        return []
    cell_gap = max(heights) * _CELL_GAP_FACTOR

    segments: list[list[Any]] = []
    current: list[tuple[str, tuple[float, float, float, float] | None]] = []
    last_right: float | None = None
    for ch, box in boxes:
        if box is None:
            current.append((ch, None))
            continue
        if last_right is not None and box[0] - last_right > cell_gap:
            _flush(segments, current, page_height)
            current = []
        current.append((ch, box))
        last_right = box[2]
    _flush(segments, current, page_height)
    return segments


def _flush(
    out: list[list[Any]],
    chars: list[tuple[str, tuple[float, float, float, float] | None]],
    page_height: float,
) -> None:
    boxes = [b for _, b in chars if b]
    text = "".join(c for c, _ in chars).strip()
    if not boxes or not text:
        return
    out.append(
        [
            min(b[0] for b in boxes),
            page_height - max(b[3] for b in boxes),
            max(b[2] for b in boxes),
            page_height - min(b[1] for b in boxes),
            text,
        ]
    )


def _stack(segments: list[list[Any]]) -> list[list[Any]]:
    """Join consecutive lines with the same left edge into paragraph blocks."""
    segments = sorted(segments, key=lambda s: (s[1], s[0]))
    blocks: list[list[Any]] = []  # [x0, y0, x1, y1, text, last_line_height]
    for seg in segments:
        height = seg[3] - seg[1]
        for block in reversed(blocks[-_STACK_WINDOW:]):
            gap = seg[1] - block[3]
            if abs(block[0] - seg[0]) < _LEFT_EDGE_TOLERANCE and -1 <= gap <= max(height, block[5]) * _LINE_JOIN_FACTOR:
                block[1] = min(block[1], seg[1])
                block[2] = max(block[2], seg[2])
                block[3] = seg[3]
                block[4] += "\n" + seg[4]
                block[5] = height
                break
        else:
            blocks.append([*seg, height])
    blocks.sort(key=lambda b: (round(b[1]), b[0]))
    return [b[:5] for b in blocks]
