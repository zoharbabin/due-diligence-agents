"""Document-to-markdown conversion.

``markitdown`` is preferred. It imports ``magika``, which needs
``onnxruntime``, and ``onnxruntime`` has no wheels on some Python versions.
There ``markitdown`` can be installed without its dependencies
(``pip install --no-deps markitdown``). This module then loads it with a
stand-in for ``magika`` that reports "no guess". ``markitdown`` handles that
by using the extension, which the caller can correct with the *extension*
argument (see ``extraction/file_type.py``).

When ``markitdown`` is not installed at all, common Office and HTML formats
are converted with the libraries ``markitdown`` itself builds on.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import types
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Modules whose absence is the known onnxruntime gap, not a broken install.
_MAGIC_DEPS = frozenset({"magika", "onnxruntime"})
_import_lock = threading.Lock()


class _NoGuess:
    """``magika`` result that ``markitdown`` treats as "could not identify"."""

    status = "error"


class _NoMagika:
    """Stand-in for ``magika.Magika`` when it cannot be imported."""

    def identify_stream(self, stream: Any) -> _NoGuess:
        return _NoGuess()


def _load_markitdown() -> Any:
    """Return the ``MarkItDown`` class. Raises ``ImportError`` if unavailable.

    If only ``magika``/``onnxruntime`` are missing, ``markitdown`` is imported
    with a temporary ``magika`` stand-in. The stand-in is removed from
    ``sys.modules`` afterwards, so no other code sees it.
    """
    try:
        from markitdown import MarkItDown

        return MarkItDown
    except ModuleNotFoundError as exc:
        if exc.name not in _MAGIC_DEPS:
            raise

    with _import_lock:
        stub = types.ModuleType("magika")
        stub.Magika = _NoMagika  # type: ignore[attr-defined]
        previous = sys.modules.get("magika")
        sys.modules["magika"] = stub
        try:
            from markitdown import MarkItDown
        finally:
            if previous is None:
                sys.modules.pop("magika", None)
            else:
                sys.modules["magika"] = previous
    logger.info("magika is unavailable: markitdown identifies files by extension only")
    return MarkItDown


def convert_to_markdown(path: str | Path, extension: str | None = None) -> str:
    """Convert *path* to markdown text.

    *extension* (for example ``".xlsx"``) overrides the file name's extension
    when the caller knows the real type.

    Raises ``ImportError`` when ``markitdown`` is unavailable and the built-in
    fallback does not handle the file type. Conversion errors propagate.
    """
    filepath = Path(path)
    suffix = (extension or filepath.suffix).lower()
    try:
        markitdown_cls = _load_markitdown()
    except ImportError:
        converter = _FALLBACKS.get(suffix)
        if converter is None:
            raise ImportError(f"markitdown is not installed and no built-in converter handles {suffix!r}") from None
        logger.debug("markitdown unavailable, using built-in converter for %s", filepath.name)
        return converter(filepath)

    kwargs: dict[str, Any] = {}
    if extension:
        from markitdown import StreamInfo

        kwargs["stream_info"] = StreamInfo(extension=extension)
    result = markitdown_cls().convert(str(filepath), **kwargs)
    text: str = result.text_content if hasattr(result, "text_content") else ""
    return text


def _table(rows: list[list[str]]) -> str:
    """Render rows as a markdown table. The first row is the header."""
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [[c.replace("|", "\\|").replace("\n", " ") for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in padded[1:]]
    return "\n".join(lines)


def _html_to_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text: str = markdownify(str(soup), heading_style="ATX")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _convert_html(path: Path) -> str:
    return _html_to_markdown(path.read_text(encoding="utf-8", errors="replace"))


def _convert_docx(path: Path) -> str:
    import mammoth

    with path.open("rb") as fh:
        html: str = mammoth.convert_to_html(fh).value
    return _html_to_markdown(html)


def _convert_pptx(path: Path) -> str:
    from pptx import Presentation

    parts: list[str] = []
    for number, slide in enumerate(Presentation(str(path)).slides, start=1):
        parts.append(f"<!-- Slide number: {number} -->")
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                paragraphs = [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
                if paragraphs:
                    parts.append("\n".join(paragraphs))
            if getattr(shape, "has_table", False) and shape.has_table:
                table: Any = shape.table
                parts.append(_table([[cell.text for cell in row.cells] for row in table.rows]))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                parts.append(f"### Notes:\n{notes.text.strip()}")
    return "\n\n".join(p for p in parts if p)


def _convert_xlsx(path: Path) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        parts: list[str] = []
        for sheet in workbook.worksheets:
            rows = [["" if v is None else str(v) for v in row] for row in sheet.iter_rows(values_only=True)]
            table = _table(rows)
            if table:
                parts.append(f"## {sheet.title}\n\n{table}")
        return "\n\n".join(parts)
    finally:
        workbook.close()


_FALLBACKS = {
    ".html": _convert_html,
    ".htm": _convert_html,
    ".docx": _convert_docx,
    ".pptx": _convert_pptx,
    ".xlsx": _convert_xlsx,
}
