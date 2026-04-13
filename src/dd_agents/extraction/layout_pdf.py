"""Layout-aware PDF extraction with table detection.

Optional backend using pymupdf's ``page.get_text("blocks")`` for
detecting tabular structures.  Falls back gracefully when tables
are not detected.

Algorithm:
    ``get_text("blocks")`` returns ``(x0, y0, x1, y1, text, block_no, type)``
    tuples.  Blocks are grouped by Y-coordinate (tolerance-based) to form
    rows, then sorted by X within each row.  Three or more rows with the
    same column count are rendered as a Markdown table.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.extraction._constants import CONFIDENCE_FAILURE
from dd_agents.extraction._constants import CONFIDENCE_LAYOUT_PDF as _CONFIDENCE_LAYOUT

logger = logging.getLogger(__name__)

# Y-coordinate tolerance for grouping blocks into the same row (points).
_Y_TOLERANCE = 5.0


class LayoutPDFBackend:
    """Optional backend using pymupdf block coordinates for table detection."""

    @property
    def name(self) -> str:
        return "layout_pdf"

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset({".pdf"})

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text with layout-aware table detection.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence)``.  Returns ``("", 0.0)`` on
            failure.
        """
        try:
            import fitz
        except ImportError:
            logger.debug("pymupdf (fitz) not available for layout extraction")
            return "", CONFIDENCE_FAILURE

        from dd_agents.extraction.pipeline import _FITZ_LOCK

        parts: list[str] = []
        with _FITZ_LOCK:
            try:
                doc = fitz.open(str(filepath))
            except Exception:
                logger.warning("pymupdf failed to open %s for layout extraction", filepath)
                return "", CONFIDENCE_FAILURE

            try:
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    blocks = page.get_text("blocks")
                    if not blocks:
                        continue

                    text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text

                    tables = self._detect_tables(text_blocks)
                    page_text = self._blocks_to_markdown(text_blocks, tables, page_num + 1)
                    if page_text.strip():
                        parts.append(page_text)
            finally:
                doc.close()

        if parts:
            return "\n\n".join(parts), _CONFIDENCE_LAYOUT
        return "", CONFIDENCE_FAILURE

    @staticmethod
    def _detect_tables(blocks: list[Any]) -> list[list[list[str]]]:
        """Group blocks by Y-coordinate to detect table rows.

        Returns a list of tables, where each table is a list of rows,
        and each row is a list of cell texts.
        """
        if not blocks:
            return []

        # Group blocks by Y-coordinate (top edge)
        rows: dict[float, list[Any]] = {}
        for block in blocks:
            y0 = block[1]
            # Find existing row within tolerance
            matched = False
            for key_y in rows:
                if abs(y0 - key_y) <= _Y_TOLERANCE:
                    rows[key_y].append(block)
                    matched = True
                    break
            if not matched:
                rows[y0] = [block]

        # Sort rows by Y, then sort blocks within each row by X
        sorted_rows: list[list[Any]] = []
        for y in sorted(rows.keys()):
            row_blocks = sorted(rows[y], key=lambda b: b[0])  # sort by x0
            sorted_rows.append(row_blocks)

        # Detect tables: 3+ consecutive rows with the same column count
        tables: list[list[list[str]]] = []
        current_table: list[list[str]] = []
        prev_col_count: int | None = None

        for row_blocks in sorted_rows:
            col_count = len(row_blocks)
            if col_count >= 2 and col_count == prev_col_count:
                current_table.append([b[4].strip() for b in row_blocks])
            else:
                if len(current_table) >= 3:
                    tables.append(current_table)
                current_table = [[b[4].strip() for b in row_blocks]] if col_count >= 2 else []
                prev_col_count = col_count

        if len(current_table) >= 3:
            tables.append(current_table)

        return tables

    @staticmethod
    def _blocks_to_markdown(
        blocks: list[Any],
        tables: list[list[list[str]]],
        page_num: int,
    ) -> str:
        """Render detected tables as Markdown, rest as paragraphs."""
        # Collect all text from table cells to identify which blocks are in tables
        table_texts: set[str] = set()
        for table in tables:
            for row in table:
                for cell in row:
                    table_texts.add(cell)

        parts: list[str] = [f"--- Page {page_num} ---"]

        # Output non-table blocks as paragraphs
        for block in blocks:
            text = block[4].strip()
            if text and text not in table_texts:
                parts.append(text)

        # Output tables as Markdown
        for table in tables:
            if not table:
                continue
            # Header row
            header = "| " + " | ".join(table[0]) + " |"
            separator = "| " + " | ".join("---" for _ in table[0]) + " |"
            rows_md = [header, separator]
            for row in table[1:]:
                rows_md.append("| " + " | ".join(row) + " |")
            parts.append("\n".join(rows_md))

        return "\n\n".join(parts)
