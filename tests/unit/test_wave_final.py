"""Tests for Wave Final: 5 issues (#124, #127, #130, #134, #151)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    title: str = "Test Finding",
    severity: str = "P2",
    category: str = "change_of_control",
    agent: str = "legal",
    subject: str = "test_subject",
    description: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "severity": severity,
        "category": category,
        "agent": agent,
        "_subject_safe_name": subject,
        "_subject": subject,
        "description": description,
    }


# ===========================================================================
# Issue #127: Vector Store Integration
# ===========================================================================


class TestSearchSimilarTool:
    """Tests for #127: search_similar tool."""

    def test_tool_schema(self) -> None:
        from dd_agents.tools.search_similar import search_similar_tool_schema

        schema = search_similar_tool_schema()
        assert schema["name"] == "search_similar"
        assert "input_schema" in schema
        assert "query" in schema["input_schema"]["properties"]
        assert schema["input_schema"]["required"] == ["query"]

    def test_unavailable_returns_empty(self) -> None:
        from dd_agents.tools.search_similar import search_similar

        # Default: no vector store set
        with patch("dd_agents.tools.search_similar._VECTOR_STORE", None):
            result = search_similar("change of control")
        assert result["available"] is False
        assert result["results"] == []

    def test_available_returns_results(self) -> None:
        from dd_agents.tools.search_similar import search_similar

        mock_store = MagicMock()
        mock_store.is_available = True
        mock_store.search.return_value = [
            {"text": "CoC clause text", "metadata": {"subject_safe_name": "acme"}, "distance": 0.2, "id": "1"},
        ]

        with patch("dd_agents.tools.search_similar._VECTOR_STORE", mock_store):
            result = search_similar("change of control")

        assert result["available"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == 0.8  # 1.0 - 0.2

    def test_subject_filter(self) -> None:
        from dd_agents.tools.search_similar import search_similar

        mock_store = MagicMock()
        mock_store.is_available = True
        mock_store.search.return_value = [
            {"text": "result A", "metadata": {"subject_safe_name": "acme"}, "distance": 0.1, "id": "1"},
            {"text": "result B", "metadata": {"subject_safe_name": "beta"}, "distance": 0.2, "id": "2"},
        ]

        with patch("dd_agents.tools.search_similar._VECTOR_STORE", mock_store):
            result = search_similar("test", subject="acme")

        assert len(result["results"]) == 1
        assert result["results"][0]["metadata"]["subject_safe_name"] == "acme"

    def test_top_k_capped_at_20(self) -> None:
        from dd_agents.tools.search_similar import search_similar

        mock_store = MagicMock()
        mock_store.is_available = True
        mock_store.search.return_value = []

        with patch("dd_agents.tools.search_similar._VECTOR_STORE", mock_store):
            search_similar("test", top_k=50)

        mock_store.search.assert_called_once_with(query="test", top_k=20)

    def test_set_vector_store(self) -> None:
        from dd_agents.tools.search_similar import set_vector_store

        mock = MagicMock()
        set_vector_store(mock)
        # Clean up
        set_vector_store(None)

    def test_search_similar_in_tool_registry(self) -> None:
        from dd_agents.tools.server import SPECIALIST_CUSTOM_TOOLS, create_tool_definitions

        assert "search_similar" in SPECIALIST_CUSTOM_TOOLS
        tools = create_tool_definitions()
        names = [t["name"] for t in tools]
        assert "search_similar" in names


# ===========================================================================
# Issue #151: PDF Export
# ===========================================================================


class TestPDFExport:
    """Tests for #151: PDF Export."""

    def test_engine_detection_flags(self) -> None:
        from dd_agents.reporting.pdf_export import PLAYWRIGHT_AVAILABLE, WEASYPRINT_AVAILABLE

        # These are booleans — just verify they exist and are bool
        assert isinstance(PLAYWRIGHT_AVAILABLE, bool)
        assert isinstance(WEASYPRINT_AVAILABLE, bool)

    def test_export_pdf_missing_file(self) -> None:
        from dd_agents.reporting.pdf_export import export_pdf

        with pytest.raises(FileNotFoundError):
            asyncio.run(export_pdf(Path("/nonexistent/report.html")))

    def test_export_pdf_no_engine(self, tmp_path: Path) -> None:
        from dd_agents.reporting.pdf_export import PDFExportError, export_pdf

        html = tmp_path / "report.html"
        html.write_text("<html><body>Test</body></html>")

        with (
            patch("dd_agents.reporting.pdf_export.PLAYWRIGHT_AVAILABLE", False),
            patch("dd_agents.reporting.pdf_export.WEASYPRINT_AVAILABLE", False),
            pytest.raises(PDFExportError, match="No PDF engine available"),
        ):
            asyncio.run(export_pdf(html, engine="auto"))

    def test_export_pdf_invalid_engine(self, tmp_path: Path) -> None:
        from dd_agents.reporting.pdf_export import PDFExportError, export_pdf

        html = tmp_path / "report.html"
        html.write_text("<html><body>Test</body></html>")

        with (
            patch("dd_agents.reporting.pdf_export.PLAYWRIGHT_AVAILABLE", False),
            patch("dd_agents.reporting.pdf_export.WEASYPRINT_AVAILABLE", False),
            pytest.raises(PDFExportError, match="not available"),
        ):
            asyncio.run(export_pdf(html, engine="playwright"))

    def test_export_pdf_auto_output_path(self, tmp_path: Path) -> None:
        from dd_agents.reporting.pdf_export import export_pdf

        html = tmp_path / "report.html"
        html.write_text("<html><body>Test</body></html>")

        mock_export = AsyncMock(return_value=tmp_path / "report.pdf")
        (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 test")

        with (
            patch("dd_agents.reporting.pdf_export.PLAYWRIGHT_AVAILABLE", True),
            patch("dd_agents.reporting.pdf_export._export_with_playwright", mock_export),
        ):
            result = asyncio.run(export_pdf(html))

        assert result.suffix == ".pdf"
        mock_export.assert_called_once()

    def test_export_pdf_error_class(self) -> None:
        from dd_agents.reporting.pdf_export import PDFExportError

        assert issubclass(PDFExportError, Exception)

    def test_cli_export_pdf_command_exists(self) -> None:
        from dd_agents.cli import main

        command_names = [cmd for cmd in main.commands]
        assert "export-pdf" in command_names


# ===========================================================================
# Issue #124: Natural Language Query Interface
# ===========================================================================


class TestFindingIndexer:
    """Tests for #124: Finding indexer."""

    def test_index_empty_list(self) -> None:
        from dd_agents.query.indexer import FindingIndexer

        indexer = FindingIndexer()
        index = indexer.index_findings([])
        assert index.total_findings == 0
        assert index.summary == "No findings indexed."

    def test_index_findings_by_severity(self) -> None:
        from dd_agents.query.indexer import FindingIndexer

        findings = [
            _make_finding(severity="P0", title="Critical risk"),
            _make_finding(severity="P0", title="Another critical"),
            _make_finding(severity="P2", title="Medium risk"),
        ]
        indexer = FindingIndexer()
        index = indexer.index_findings(findings)
        assert index.total_findings == 3
        assert len(index.by_severity["P0"]) == 2
        assert len(index.by_severity["P2"]) == 1

    def test_index_findings_by_subject(self) -> None:
        from dd_agents.query.indexer import FindingIndexer

        findings = [
            _make_finding(subject="acme"),
            _make_finding(subject="acme"),
            _make_finding(subject="beta"),
        ]
        indexer = FindingIndexer()
        index = indexer.index_findings(findings)
        assert len(index.by_subject["acme"]) == 2
        assert len(index.by_subject["beta"]) == 1

    def test_index_findings_by_category(self) -> None:
        from dd_agents.query.indexer import FindingIndexer

        findings = [
            _make_finding(category="change_of_control"),
            _make_finding(category="liability_cap"),
            _make_finding(category="change_of_control"),
        ]
        indexer = FindingIndexer()
        index = indexer.index_findings(findings)
        assert len(index.by_category["change_of_control"]) == 2

    def test_index_report_from_directory(self, tmp_path: Path) -> None:
        from dd_agents.query.indexer import FindingIndexer

        merged_dir = tmp_path / "findings" / "merged"
        merged_dir.mkdir(parents=True)
        (merged_dir / "acme.json").write_text(
            json.dumps(
                [
                    _make_finding(title="CoC clause", subject="acme"),
                    _make_finding(title="Liability cap", subject="acme"),
                ]
            )
        )
        (merged_dir / "beta.json").write_text(
            json.dumps(
                [
                    _make_finding(title="Auto-renewal", subject="beta"),
                ]
            )
        )

        indexer = FindingIndexer()
        index = indexer.index_report(tmp_path)
        assert index.total_findings == 3

    def test_index_report_empty_dir(self, tmp_path: Path) -> None:
        from dd_agents.query.indexer import FindingIndexer

        indexer = FindingIndexer()
        index = indexer.index_report(tmp_path)
        assert index.total_findings == 0

    def test_index_summary_format(self) -> None:
        from dd_agents.query.indexer import FindingIndexer

        findings = [
            _make_finding(severity="P0", agent="legal"),
            _make_finding(severity="P1", agent="finance"),
        ]
        indexer = FindingIndexer()
        index = indexer.index_findings(findings)
        assert "2 findings indexed" in index.summary
        assert "P0" in index.summary


class TestQueryEngine:
    """Tests for #124: Query engine."""

    def _make_engine(self, findings: list[dict[str, Any]] | None = None) -> Any:
        from dd_agents.query.engine import QueryEngine
        from dd_agents.query.indexer import FindingIndexer

        if findings is None:
            findings = [
                _make_finding(severity="P0", title="Critical CoC risk", subject="acme"),
                _make_finding(severity="P0", title="IP ownership gap", subject="beta"),
                _make_finding(severity="P1", title="Liability uncapped", subject="acme"),
                _make_finding(severity="P2", title="Auto-renewal notice", subject="gamma"),
                _make_finding(severity="P3", title="Standard warranty", subject="acme"),
            ]
        indexer = FindingIndexer()
        index = indexer.index_findings(findings)
        return QueryEngine(index)

    def test_count_p0_findings(self) -> None:
        engine = self._make_engine()
        result = asyncio.run(engine.query("How many P0 findings?"))
        assert result.query_type == "keyword"
        assert result.confidence == "high"
        assert "2" in result.answer

    def test_count_total_findings(self) -> None:
        engine = self._make_engine()
        result = asyncio.run(engine.query("How many total findings?"))
        assert "5" in result.answer
        assert result.query_type == "keyword"

    def test_count_subjects(self) -> None:
        engine = self._make_engine()
        result = asyncio.run(engine.query("How many subjects?"))
        assert "3" in result.answer

    def test_fallback_search(self) -> None:
        import builtins

        engine = self._make_engine()
        real_import = builtins.__import__

        def block_sdk(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=block_sdk):
            result = asyncio.run(engine.query("Tell me about CoC risks"))
        assert result.answer  # Non-empty answer
        assert result.query_type == "keyword"

    def test_empty_index_fallback(self) -> None:
        engine = self._make_engine(findings=[])
        result = asyncio.run(engine.query("What are the risks?"))
        assert result.confidence == "low"

    def test_query_result_model(self) -> None:
        from dd_agents.query.engine import QueryResult

        r = QueryResult(answer="test", sources=[], confidence="high", query_type="keyword")
        assert r.answer == "test"
        assert r.confidence == "high"

    def test_cli_query_command_exists(self) -> None:
        from dd_agents.cli import main

        command_names = [cmd for cmd in main.commands]
        assert "query" in command_names

    def test_finding_index_model(self) -> None:
        from dd_agents.query.indexer import FindingIndex

        idx = FindingIndex()
        assert idx.total_findings == 0
        assert idx.findings == []


# ===========================================================================
# Issue #130: E2E Test Infrastructure
# ===========================================================================


class TestDataGeneratorImport:
    """Tests for #130: Data generator importability."""

    def test_testing_package_imports(self) -> None:
        from dd_agents.testing import SyntheticDataRoomGenerator  # noqa: F401

    def test_generator_creates_data_room(self, tmp_path: Path) -> None:
        from dd_agents.testing.data_generator import SyntheticDataRoomGenerator

        gen = SyntheticDataRoomGenerator(seed=42)
        root = gen.generate(tmp_path / "data_room")
        assert root.is_dir()
        # Should have subject directories
        md_files = list(root.rglob("*.md"))
        assert len(md_files) >= 5

    def test_generator_deterministic(self, tmp_path: Path) -> None:
        from dd_agents.testing.data_generator import SyntheticDataRoomGenerator

        root1 = SyntheticDataRoomGenerator(seed=99).generate(tmp_path / "run1")
        root2 = SyntheticDataRoomGenerator(seed=99).generate(tmp_path / "run2")

        files1 = sorted(str(p.relative_to(root1)) for p in root1.rglob("*.md"))
        files2 = sorted(str(p.relative_to(root2)) for p in root2.rglob("*.md"))
        assert files1 == files2

    def test_generator_reference_folder(self, tmp_path: Path) -> None:
        from dd_agents.testing.data_generator import SyntheticDataRoomGenerator

        root = SyntheticDataRoomGenerator().generate(tmp_path / "dr")
        assert (root / "_reference").is_dir()

    def test_generator_planted_findings(self, tmp_path: Path) -> None:
        from dd_agents.testing.data_generator import SyntheticDataRoomGenerator

        root = SyntheticDataRoomGenerator().generate(tmp_path / "dr")
        all_text = ""
        for md_file in root.rglob("*.md"):
            all_text += md_file.read_text()
        # Check planted clauses exist
        text_lower = all_text.lower()
        assert "change of control" in text_lower
        assert "liability" in text_lower


# ===========================================================================
# Issue #134: Documentation
# ===========================================================================


class TestDocumentation:
    """Tests for #134: User guide documentation exists."""

    @pytest.mark.parametrize(
        "filename",
        [
            "getting-started.md",
            "deal-configuration.md",
            "running-pipeline.md",
            "reading-report.md",
            "cli-reference.md",
        ],
    )
    def test_user_guide_file_exists(self, filename: str) -> None:
        doc_path = Path(__file__).parent.parent.parent / "docs" / "user-guide" / filename
        assert doc_path.exists(), f"Missing user guide: {filename}"

    def test_getting_started_has_install_instructions(self) -> None:
        doc = (Path(__file__).parent.parent.parent / "docs" / "user-guide" / "getting-started.md").read_text()
        assert "pip install" in doc.lower() or "pip install" in doc

    def test_cli_reference_has_commands(self) -> None:
        doc = (Path(__file__).parent.parent.parent / "docs" / "user-guide" / "cli-reference.md").read_text()
        assert "dd-agents" in doc
        assert "run" in doc
        assert "search" in doc


# ===========================================================================
# Cross-cutting integration
# ===========================================================================


class TestCLICommandCount:
    """Verify all CLI commands are registered."""

    def test_all_commands_registered(self) -> None:
        from dd_agents.cli import main

        commands = set(main.commands.keys())
        expected = {"run", "validate", "version", "init", "auto-config", "search", "assess", "export-pdf", "query"}
        assert expected.issubset(commands), f"Missing commands: {expected - commands}"
