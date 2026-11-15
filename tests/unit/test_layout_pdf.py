"""Tests for the layout-aware PDF extraction backend.

Covers:
    - LayoutPDFBackend satisfies ExtractionBackend protocol
    - Table detection with aligned blocks (3+ rows, same column count)
    - No alignment case -- blocks that do not form tables
    - Markdown rendering of detected tables
    - Graceful degradation when the PDF engine fails
    - ``name`` and ``supported_extensions`` properties
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from dd_agents.extraction.backend import ExtractionBackend
from dd_agents.extraction.layout_pdf import LayoutPDFBackend
from dd_agents.extraction.pdf_engine import PdfBlock, PdfError

if TYPE_CHECKING:
    from pathlib import Path

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_block(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    text: str,
    block_no: int = 0,
    block_type: int = 0,
) -> tuple[float, float, float, float, str, int, int]:
    """Build a text block tuple: (x0, y0, x1, y1, text, block_no, type)."""
    return (x0, y0, x1, y1, text, block_no, block_type)


def _tabular_blocks() -> list[Any]:
    """Return blocks that form a 4-row, 3-column table.

    Four rows at y=10, 30, 50, 70 with three columns each.
    """
    rows: list[Any] = []
    texts = [
        ["Header A", "Header B", "Header C"],
        ["r1c1", "r1c2", "r1c3"],
        ["r2c1", "r2c2", "r2c3"],
        ["r3c1", "r3c2", "r3c3"],
    ]
    for row_idx, row_texts in enumerate(texts):
        y = 10.0 + row_idx * 20.0
        for col_idx, cell_text in enumerate(row_texts):
            x = 10.0 + col_idx * 100.0
            rows.append(_make_block(x, y, x + 80.0, y + 12.0, cell_text, block_no=len(rows)))
    return rows


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestLayoutPDFProtocol:
    """LayoutPDFBackend satisfies ExtractionBackend protocol."""

    def test_isinstance_check(self) -> None:
        backend = LayoutPDFBackend()
        assert isinstance(backend, ExtractionBackend)

    def test_name_property(self) -> None:
        backend = LayoutPDFBackend()
        assert backend.name == "layout_pdf"

    def test_supported_extensions_contains_pdf(self) -> None:
        backend = LayoutPDFBackend()
        assert ".pdf" in backend.supported_extensions


class TestDetectTables:
    """Table detection with aligned blocks."""

    def test_detects_table_with_three_plus_rows(self) -> None:
        """3+ rows with the same column count (>=2) are detected as a table."""
        blocks = _tabular_blocks()
        tables = LayoutPDFBackend._detect_tables(blocks)

        assert len(tables) == 1
        table = tables[0]
        # 4 rows total, all with 3 columns
        assert len(table) == 4
        assert all(len(row) == 3 for row in table)
        # Check header text
        assert table[0] == ["Header A", "Header B", "Header C"]

    def test_no_table_when_fewer_than_three_rows(self) -> None:
        """Only 2 rows with equal column count -- not enough for a table."""
        blocks = [
            _make_block(10, 10, 90, 22, "A1", 0),
            _make_block(110, 10, 190, 22, "A2", 1),
            _make_block(10, 30, 90, 42, "B1", 2),
            _make_block(110, 30, 190, 42, "B2", 3),
        ]
        tables = LayoutPDFBackend._detect_tables(blocks)
        assert tables == []

    def test_no_table_when_blocks_are_single_column(self) -> None:
        """Single-column blocks (col_count < 2) are never tables."""
        blocks = [
            _make_block(10, 10, 300, 22, "Paragraph line 1", 0),
            _make_block(10, 30, 300, 42, "Paragraph line 2", 1),
            _make_block(10, 50, 300, 62, "Paragraph line 3", 2),
            _make_block(10, 70, 300, 82, "Paragraph line 4", 3),
        ]
        tables = LayoutPDFBackend._detect_tables(blocks)
        assert tables == []

    def test_empty_blocks_returns_empty(self) -> None:
        tables = LayoutPDFBackend._detect_tables([])
        assert tables == []


class TestBlocksToMarkdown:
    """Markdown rendering of detected tables."""

    def test_table_rendered_as_markdown(self) -> None:
        """Detected tables produce Markdown pipe-delimited output."""
        blocks = _tabular_blocks()
        tables = LayoutPDFBackend._detect_tables(blocks)
        md = LayoutPDFBackend._blocks_to_markdown(blocks, tables, page_num=1)

        assert "--- Page 1 ---" in md

        # Validate Markdown table structure
        assert "| Header A | Header B | Header C |" in md
        assert "| --- | --- | --- |" in md
        assert "| r1c1 | r1c2 | r1c3 |" in md
        assert "| r3c1 | r3c2 | r3c3 |" in md

    def test_non_table_blocks_rendered_as_paragraphs(self) -> None:
        """Blocks that are not part of a table appear as plain paragraphs."""
        blocks = [
            _make_block(10, 10, 300, 22, "First paragraph", 0),
            _make_block(10, 40, 300, 52, "Second paragraph", 1),
        ]
        md = LayoutPDFBackend._blocks_to_markdown(blocks, tables=[], page_num=2)

        assert "--- Page 2 ---" in md
        assert "First paragraph" in md
        assert "Second paragraph" in md
        # No Markdown table markers
        assert "|" not in md
        assert "---" not in md.replace("--- Page 2 ---", "")


class TestGracefulDegradation:
    """extract() degrades to ('', 0.0) when the PDF engine fails."""

    def test_returns_failure_when_engine_raises(self, tmp_path: Path) -> None:
        """extract() returns ('', 0.0) when the PDF cannot be opened."""
        backend = LayoutPDFBackend()
        pdf_file = tmp_path / "corrupt.pdf"
        pdf_file.write_bytes(b"not a real pdf")

        with patch("dd_agents.extraction.pdf_engine.extract_blocks", side_effect=PdfError("corrupt file")):
            text, confidence = backend.extract(pdf_file)

        assert text == ""
        assert confidence == 0.0

    def test_returns_failure_for_real_corrupt_file(self, tmp_path: Path) -> None:
        """A real unreadable file takes the same path, with no mocks."""
        backend = LayoutPDFBackend()
        pdf_file = tmp_path / "corrupt.pdf"
        pdf_file.write_bytes(b"not a real pdf")

        text, confidence = backend.extract(pdf_file)

        assert text == ""
        assert confidence == 0.0

    def test_returns_failure_when_no_blocks(self, tmp_path: Path) -> None:
        """A PDF with no text blocks yields ('', 0.0)."""
        backend = LayoutPDFBackend()
        pdf_file = tmp_path / "blank.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        with patch("dd_agents.extraction.pdf_engine.extract_blocks", return_value=[]):
            text, confidence = backend.extract(pdf_file)

        assert text == ""
        assert confidence == 0.0

    def test_successful_extraction_with_engine_blocks(self, tmp_path: Path) -> None:
        """extract() returns text and confidence for single-column blocks."""
        backend = LayoutPDFBackend()
        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        blocks = [
            PdfBlock(1, 10, 10, 300, 22, "Document title"),
            PdfBlock(1, 10, 40, 300, 52, "Body text here"),
        ]

        with patch("dd_agents.extraction.pdf_engine.extract_blocks", return_value=blocks):
            text, confidence = backend.extract(pdf_file)

        assert "Document title" in text
        assert "Body text here" in text
        assert confidence == 0.85

    def test_pages_are_rendered_separately(self, tmp_path: Path) -> None:
        """Blocks are grouped per page with a page marker each."""
        backend = LayoutPDFBackend()
        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        blocks = [PdfBlock(1, 10, 10, 300, 22, "On page one"), PdfBlock(2, 10, 10, 300, 22, "On page two")]

        with patch("dd_agents.extraction.pdf_engine.extract_blocks", return_value=blocks):
            text, _ = backend.extract(pdf_file)

        assert "--- Page 1 ---" in text
        assert "--- Page 2 ---" in text
