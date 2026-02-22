"""Unit tests for the search analyzer engine (mocked API)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from dd_agents.models.inventory import CustomerEntry
from dd_agents.models.search import SearchColumn, SearchPrompts
from dd_agents.search.analyzer import SearchAnalyzer

if TYPE_CHECKING:
    from pathlib import Path


def _make_prompts() -> SearchPrompts:
    return SearchPrompts(
        name="Test",
        columns=[
            SearchColumn(name="Consent Required", prompt="Does this agreement require consent? Answer YES or NO."),
            SearchColumn(name="Notice Required", prompt="Does this agreement require notice? Answer YES or NO."),
        ],
    )


def _make_customer(name: str = "Acme Corp", group: str = "GroupA") -> CustomerEntry:
    return CustomerEntry(
        group=group,
        name=name,
        safe_name="acme",
        path=f"{group}/{name}",
        file_count=2,
        files=[f"{group}/{name}/msa.pdf", f"{group}/{name}/sow.docx"],
    )


def _make_analyzer(tmp_path: Path, prompts: SearchPrompts | None = None) -> SearchAnalyzer:
    data_room = tmp_path / "data_room"
    data_room.mkdir()
    text_dir = data_room / "_dd" / "forensic-dd" / "index" / "text"
    text_dir.mkdir(parents=True)
    return SearchAnalyzer(
        prompts=prompts or _make_prompts(),
        data_room_path=data_room,
        text_dir=text_dir,
    )


def _write_text_file(tmp_path: Path, rel_path: str, content: str) -> None:
    """Write a fake extracted text file using the same naming as the pipeline."""
    from dd_agents.extraction.pipeline import ExtractionPipeline

    text_dir = tmp_path / "data_room" / "_dd" / "forensic-dd" / "index" / "text"
    data_room = tmp_path / "data_room"
    # The analyzer resolves relative paths against data_room_path, so mirror that.
    absolute = str(data_room / rel_path)
    safe_name = ExtractionPipeline._safe_text_name(absolute)
    (text_dir / safe_name).write_text(content)


class TestCostEstimate:
    """Tests for cost estimation."""

    def test_returns_required_keys(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        estimate = analyzer.estimate_cost([customer])

        assert "total_customers" in estimate
        assert "total_files" in estimate
        assert "files_with_text" in estimate
        assert "files_missing_text" in estimate
        assert "estimated_input_tokens" in estimate
        assert "estimated_output_tokens" in estimate
        assert "estimated_cost_usd" in estimate
        assert estimate["total_customers"] == 1

    def test_zero_customers(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        estimate = analyzer.estimate_cost([])

        assert estimate["total_customers"] == 0
        assert estimate["total_files"] == 0
        assert estimate["estimated_cost_usd"] == 0.0

    def test_missing_files_counted(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        # Write only one of the two expected files.
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Some text.")

        estimate = analyzer.estimate_cost([customer])
        assert estimate["files_with_text"] == 1
        assert estimate["files_missing_text"] == 1
        assert estimate["total_files"] == 2


class TestPromptBuilding:
    """Tests for system and customer prompt building."""

    def test_system_prompt_contains_column_names(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        prompt = analyzer._build_system_prompt()

        assert "Consent Required" in prompt
        assert "Notice Required" in prompt

    def test_system_prompt_contains_hierarchy_instructions(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        prompt = analyzer._build_system_prompt()

        assert "hierarchy" in prompt.lower()
        assert "amendments" in prompt.lower()

    def test_system_prompt_requires_all_columns(self, tmp_path: Path) -> None:
        """AG RAG Report compliance: prompt must demand all questions are answered."""
        analyzer = _make_analyzer(tmp_path)
        prompt = analyzer._build_system_prompt()

        assert "MUST answer EVERY question" in prompt
        assert "MUST contain exactly these keys" in prompt
        assert "do NOT omit" in prompt

    def test_system_prompt_contains_follow_up_validation(self, tmp_path: Path) -> None:
        """AG RAG Report compliance: prompt should instruct double-checking."""
        analyzer = _make_analyzer(tmp_path)
        prompt = analyzer._build_system_prompt()

        assert "Double-check" in prompt
        assert "pay special attention" in prompt.lower()

    def test_customer_prompt_includes_document_text(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Write extracted text files.
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Master Service Agreement content here.")

        prompt, files_found, skipped = analyzer._build_customer_prompt(customer)

        assert "Acme Corp" in prompt
        assert "Master Service Agreement" in prompt
        assert "msa.pdf" in prompt
        assert files_found == 1
        assert len(skipped) == 1  # sow.docx was not extracted

    def test_customer_prompt_empty_when_no_text(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # No text files written.
        prompt, files_found, skipped = analyzer._build_customer_prompt(customer)
        assert prompt == ""
        assert files_found == 0
        assert len(skipped) == 2

    def test_skipped_files_tracked(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Content here.")

        _, _, skipped = analyzer._build_customer_prompt(customer)
        assert "GroupA/Acme Corp/sow.docx" in skipped
        assert len(skipped) == 1


class TestAnalysis:
    """Tests for the main analysis flow (mocked API)."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Agreement with consent clause.")

        mock_response_data = {
            "Consent Required": {
                "answer": "YES",
                "confidence": "HIGH",
                "citations": [
                    {
                        "file_path": "GroupA/Acme Corp/msa.pdf",
                        "page": "3",
                        "section_ref": "Section 12",
                        "exact_quote": "consent clause text",
                    }
                ],
            },
            "Notice Required": {
                "answer": "NOT_ADDRESSED",
                "confidence": "HIGH",
                "citations": [],
            },
        }

        mock_call = AsyncMock(return_value=json.dumps(mock_response_data))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert len(results) == 1
        result = results[0]
        assert result.customer_name == "Acme Corp"
        assert result.error is None
        assert result.columns["Consent Required"].answer == "YES"
        assert len(result.columns["Consent Required"].citations) == 1
        assert result.files_analyzed == 1
        assert result.total_files == 2
        assert len(result.skipped_files) == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        analyzer._max_retries = 2
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Some content.")

        mock_call = AsyncMock(side_effect=RuntimeError("API down"))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert len(results) == 1
        assert results[0].error is not None
        assert "API error" in results[0].error
        # Should have been called max_retries times.
        assert mock_call.call_count == 2

    @pytest.mark.asyncio
    async def test_customer_with_no_text(self, tmp_path: Path) -> None:
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # No text files → should return error without calling API.
        results = await analyzer.analyze_all([customer])

        assert len(results) == 1
        assert results[0].error is not None
        assert "No extracted text" in results[0].error
        assert results[0].total_files == 2
        assert len(results[0].skipped_files) == 2

    @pytest.mark.asyncio
    async def test_empty_json_rejected(self, tmp_path: Path) -> None:
        """Empty {} from Claude should be treated as an error, not silent success."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Some content.")

        mock_call = AsyncMock(return_value="{}")

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert len(results) == 1
        assert results[0].error is not None
        assert "empty JSON" in results[0].error

    @pytest.mark.asyncio
    async def test_incomplete_response_detected(self, tmp_path: Path) -> None:
        """Missing columns in Claude's response should be flagged."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Some content.")

        # Only return one of two expected columns.
        mock_response_data = {
            "Consent Required": {
                "answer": "YES",
                "confidence": "HIGH",
                "citations": [],
            },
            # "Notice Required" is deliberately missing.
        }

        mock_call = AsyncMock(return_value=json.dumps(mock_response_data))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert len(results) == 1
        result = results[0]
        assert "Notice Required" in result.incomplete_columns
        assert result.error is not None
        assert "Incomplete response" in result.error
        # The missing column should still have an entry.
        assert "Notice Required" in result.columns
        assert "INCOMPLETE" in result.columns["Notice Required"].answer

    @pytest.mark.asyncio
    async def test_all_customers_returned(self, tmp_path: Path) -> None:
        """Every input customer must appear in output, even on failure."""
        analyzer = _make_analyzer(tmp_path)
        customers = [
            _make_customer(name="Alpha"),
            _make_customer(name="Beta"),
            _make_customer(name="Gamma"),
        ]

        # No text for any → all should return errors.
        results = await analyzer.analyze_all(customers)

        assert len(results) == len(customers)
        names = {r.customer_name for r in results}
        assert names == {"Alpha", "Beta", "Gamma"}
