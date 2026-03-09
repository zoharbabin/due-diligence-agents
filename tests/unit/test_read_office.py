"""Tests for the read_office MCP tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestReadExcel:
    """Tests for reading Excel files (.xlsx, .xls)."""

    def test_read_xlsx_single_sheet(self, tmp_path: Path) -> None:
        """Read a simple .xlsx with one sheet returns markdown table."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Data"
        ws.append(["Name", "Value"])
        ws.append(["Alice", 100])
        ws.append(["Bob", 200])
        wb.save(tmp_path / "test.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "test.xlsx"))
        assert result["status"] == "ok"
        content = result["content"]
        assert "Sheet: Data" in content
        assert "Alice" in content
        assert "Bob" in content
        assert "100" in content

    def test_read_xlsx_multiple_sheets(self, tmp_path: Path) -> None:
        """Read a multi-sheet .xlsx returns all sheets."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws1 = wb.active
        assert ws1 is not None
        ws1.title = "Revenue"
        ws1.append(["Q1", "Q2"])
        ws1.append([1000, 2000])

        ws2 = wb.create_sheet("Costs")
        ws2.append(["Item", "Amount"])
        ws2.append(["Rent", 500])
        wb.save(tmp_path / "multi.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "multi.xlsx"))
        assert result["status"] == "ok"
        assert "Sheet: Revenue" in result["content"]
        assert "Sheet: Costs" in result["content"]
        assert "1000" in result["content"]
        assert "Rent" in result["content"]

    def test_read_xlsx_specific_sheet(self, tmp_path: Path) -> None:
        """Reading with sheet_name filters to that sheet only."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws1 = wb.active
        assert ws1 is not None
        ws1.title = "Summary"
        ws1.append(["Total", 999])

        ws2 = wb.create_sheet("Detail")
        ws2.append(["Item", "Cost"])
        ws2.append(["Widget", 42])
        wb.save(tmp_path / "sheets.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "sheets.xlsx"), sheet_name="Detail")
        assert result["status"] == "ok"
        assert "Widget" in result["content"]
        assert "999" not in result["content"]

    def test_read_xlsx_empty_sheet(self, tmp_path: Path) -> None:
        """Empty Excel file returns informative message."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        wb.save(tmp_path / "empty.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "empty.xlsx"))
        assert result["status"] == "ok"
        assert "Sheet" in result["content"] or "empty" in result["content"].lower()

    def test_read_xlsx_preserves_dates(self, tmp_path: Path) -> None:
        """Dates are preserved as strings, not converted to timestamps."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["Date", "Event"])
        ws.append(["2024-01-15", "Launch"])
        wb.save(tmp_path / "dates.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "dates.xlsx"))
        assert result["status"] == "ok"
        assert "2024" in result["content"]


class TestReadDocx:
    """Tests for reading Word documents (.docx)."""

    def test_read_docx(self, tmp_path: Path) -> None:
        """Read a .docx file returns text content."""
        pytest.importorskip("markitdown")

        # Create a minimal .docx using python-docx if available, else skip
        try:
            from docx import Document

            doc = Document()
            doc.add_paragraph("This Agreement is between Party A and Party B.")
            doc.add_paragraph("Section 1. Definitions.")
            doc.save(tmp_path / "contract.docx")
        except ImportError:
            pytest.skip("python-docx not available for test fixture creation")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "contract.docx"))
        assert result["status"] == "ok"
        assert "Party A" in result["content"]
        assert "Definitions" in result["content"]


class TestReadErrors:
    """Tests for error handling."""

    def test_file_not_found(self) -> None:
        """Missing file returns error."""
        from dd_agents.tools.read_office import read_office

        result = read_office("/nonexistent/file.xlsx")
        assert result["status"] == "error"
        assert "not found" in result["reason"].lower() or "not exist" in result["reason"].lower()

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        """Non-Office extension returns error."""
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(txt))
        assert result["status"] == "error"
        assert "unsupported" in result["reason"].lower()

    def test_unsupported_pdf(self, tmp_path: Path) -> None:
        """PDF is not handled by read_office — use Read tool instead."""
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(pdf))
        assert result["status"] == "error"

    def test_corrupted_xlsx(self, tmp_path: Path) -> None:
        """Corrupted Excel file returns error, not crash."""
        bad = tmp_path / "corrupt.xlsx"
        bad.write_bytes(b"NOT_AN_EXCEL_FILE")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(bad))
        assert result["status"] == "error"
        assert "reason" in result


class TestOutputTruncation:
    """Tests for output size management."""

    def test_large_xlsx_truncated(self, tmp_path: Path) -> None:
        """Large Excel output is truncated at the limit."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["Col_A", "Col_B", "Col_C"])
        # Write 5000 rows to generate large output
        for i in range(5000):
            ws.append([f"value_{i}_aaaa", f"data_{i}_bbbb", f"text_{i}_cccc"])
        wb.save(tmp_path / "big.xlsx")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(tmp_path / "big.xlsx"))
        assert result["status"] == "ok"
        assert len(result["content"]) <= 160_000  # Allow small overhead
        assert "truncated" in result["content"].lower()


class TestFallbackToExtractedText:
    """Tests for fallback to pre-extracted markdown in index/text/."""

    def test_fallback_when_pandas_fails(self, tmp_path: Path) -> None:
        """When primary read fails, falls back to extracted text."""
        # Create an xlsx that will fail to read
        bad_xlsx = tmp_path / "broken.xlsx"
        bad_xlsx.write_bytes(b"PK\x03\x04broken zip content")

        # Create the extracted text fallback
        text_dir = tmp_path / "index" / "text"
        text_dir.mkdir(parents=True)
        (text_dir / "broken.xlsx.md").write_text("# Extracted Content\nRevenue: $1M")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(bad_xlsx), text_dir=str(text_dir))
        assert result["status"] == "ok"
        assert "Revenue" in result["content"]
        assert result.get("method") == "extracted_text_fallback"

    def test_no_fallback_when_text_dir_missing(self, tmp_path: Path) -> None:
        """Without text_dir, corrupted file returns error."""
        bad = tmp_path / "corrupt.xlsx"
        bad.write_bytes(b"NOT_EXCEL")

        from dd_agents.tools.read_office import read_office

        result = read_office(str(bad))
        assert result["status"] == "error"


class TestToolRegistration:
    """Tests for tool registration in server.py."""

    def test_read_office_in_tool_definitions(self) -> None:
        """read_office appears in the tool definition registry."""
        # Reset singleton to pick up any changes
        import dd_agents.tools.server as srv
        from dd_agents.tools.server import create_tool_definitions

        srv._ALL_TOOL_DEFINITIONS = None

        tools = create_tool_definitions()
        names = [t["name"] for t in tools]
        assert "read_office" in names

    def test_read_office_tool_schema(self) -> None:
        """read_office tool has correct input schema."""
        import dd_agents.tools.server as srv
        from dd_agents.tools.server import create_tool_definitions

        srv._ALL_TOOL_DEFINITIONS = None

        tools = create_tool_definitions()
        tool = next(t for t in tools if t["name"] == "read_office")
        assert "file_path" in tool["input_schema"]["properties"]
        assert "file_path" in tool["input_schema"]["required"]
        assert "sheet_name" in tool["input_schema"]["properties"]

    def test_read_office_in_specialist_custom_tools(self) -> None:
        """read_office in SPECIALIST_CUSTOM_TOOLS list."""
        from dd_agents.tools.server import SPECIALIST_CUSTOM_TOOLS

        assert "read_office" in SPECIALIST_CUSTOM_TOOLS

    def test_read_office_in_specialist_tools(self) -> None:
        """read_office in SPECIALIST_TOOLS list."""
        from dd_agents.agents.specialists import SPECIALIST_TOOLS

        assert "read_office" in SPECIALIST_TOOLS


class TestPromptIntegration:
    """Tests for prompt builder integration."""

    def test_file_access_mentions_read_office(self) -> None:
        """File access instructions mention the read_office tool."""
        from dd_agents.agents.prompt_builder import PromptBuilder

        result = PromptBuilder._build_file_access_instructions()
        assert "read_office" in result

    def test_file_access_mentions_office_extensions(self) -> None:
        """Instructions mention the specific Office extensions."""
        from dd_agents.agents.prompt_builder import PromptBuilder

        result = PromptBuilder._build_file_access_instructions()
        assert ".xlsx" in result
        assert ".docx" in result
