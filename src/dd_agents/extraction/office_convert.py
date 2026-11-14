"""Document-to-markdown conversion with a built-in fallback.

``markitdown`` is preferred. It needs ``onnxruntime`` (through ``magika``),
which has no wheels on some Python versions, so the dependency is
conditional in ``pyproject.toml``. When ``markitdown`` cannot be imported,
common Office and HTML formats are converted with the libraries
``markitdown`` itself builds on.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def convert_to_markdown(path: str | Path) -> str:
    """Convert *path* to markdown text.

    Raises ``ImportError`` when ``markitdown`` is unavailable and the built-in
    fallback does not handle the file type. Conversion errors propagate.
    """
    filepath = Path(path)
    try:
        from markitdown import MarkItDown
    except ImportError:
        converter = _FALLBACKS.get(filepath.suffix.lower())
        if converter is None:
            raise ImportError(
                f"markitdown is not installed and no built-in converter handles {filepath.suffix!r}"
            ) from None
        logger.debug("markitdown unavailable, using built-in converter for %s", filepath.name)
        return converter(filepath)

    result = MarkItDown().convert(str(filepath))
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
