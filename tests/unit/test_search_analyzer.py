"""Unit tests for the search analyzer engine (mocked API).

Tests cover the 4-phase chunked analysis flow:
  Phase 1 — MAP:   per-chunk analysis via _analyze_single
  Phase 2 — MERGE: mechanical merge of chunk results
  Phase 3 — SYNTH: conflict resolution via lightweight LLM call
  Phase 4 — VALID: re-query for remaining NOT_ADDRESSED answers
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from dd_agents.models.inventory import CustomerEntry
from dd_agents.models.search import (
    SearchCitation,
    SearchColumn,
    SearchColumnResult,
    SearchCustomerResult,
    SearchPrompts,
)
from dd_agents.search.analyzer import SearchAnalyzer
from dd_agents.search.chunker import (
    AnalysisChunk,
    FileSegment,
    FileText,
    create_analysis_chunks,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers (preserved from original test file + new additions)
# ---------------------------------------------------------------------------


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


def _make_file_text(
    file_path: str = "GroupA/Acme Corp/msa.pdf",
    text: str = "Some text content.",
    has_page_markers: bool = False,
) -> FileText:
    """Create a FileText object for testing without disk I/O."""
    return FileText(file_path=file_path, text=text, has_page_markers=has_page_markers)


def _make_column_result(
    answer: str = "YES",
    confidence: str = "HIGH",
    citations: list[SearchCitation] | None = None,
) -> SearchColumnResult:
    """Create a SearchColumnResult for testing."""
    return SearchColumnResult(
        answer=answer,
        confidence=confidence,
        citations=citations or [],
    )


def _make_customer_result(
    customer_name: str = "Acme Corp",
    columns: dict[str, SearchColumnResult] | None = None,
    error: str | None = None,
) -> SearchCustomerResult:
    """Create a SearchCustomerResult for testing."""
    return SearchCustomerResult(
        customer_name=customer_name,
        group="GroupA",
        files_analyzed=1,
        total_files=2,
        skipped_files=["GroupA/Acme Corp/sow.docx"],
        columns=columns or {},
        error=error,
    )


# ===================================================================
# TestCostEstimate
# ===================================================================


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
        # New keys for 4-phase chunked analysis.
        assert "total_api_calls" in estimate
        assert "chunked_customers" in estimate
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


# ===================================================================
# TestPromptBuilding
# ===================================================================


class TestPromptBuilding:
    """Tests for system prompt and chunk prompt building."""

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
        """_gather_file_texts + _build_chunk_prompt preserves document content in prompt."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Write extracted text file.
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Master Service Agreement content here.")

        # Phase 1: gather file texts (replaces old _build_customer_prompt).
        file_texts, skipped = analyzer._gather_file_texts(customer)

        assert len(file_texts) == 1
        assert len(skipped) == 1  # sow.docx was not extracted

        # Phase 2: create chunks and build the chunk prompt.
        chunks = create_analysis_chunks(file_texts)
        assert len(chunks) >= 1

        prompt = analyzer._build_chunk_prompt(chunks[0], customer)

        assert "Acme Corp" in prompt
        assert "Master Service Agreement" in prompt
        assert "msa.pdf" in prompt

    def test_customer_prompt_empty_when_no_text(self, tmp_path: Path) -> None:
        """_gather_file_texts returns empty list when no text files exist."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # No text files written.
        file_texts, skipped = analyzer._gather_file_texts(customer)
        assert file_texts == []
        assert len(skipped) == 2

    def test_skipped_files_tracked(self, tmp_path: Path) -> None:
        """_gather_file_texts returns skipped files list correctly."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Content here.")

        file_texts, skipped = analyzer._gather_file_texts(customer)
        assert "GroupA/Acme Corp/sow.docx" in skipped
        assert len(skipped) == 1


# ===================================================================
# TestAnalysis
# ===================================================================


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
        # 4-phase: chunks_analyzed should be set.
        assert result.chunks_analyzed >= 1

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

        # No text files -> should return error without calling API.
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

        # No text for any -> all should return errors.
        results = await analyzer.analyze_all(customers)

        assert len(results) == len(customers)
        names = {r.customer_name for r in results}
        assert names == {"Alpha", "Beta", "Gamma"}


# ===================================================================
# TestGatherFileTexts
# ===================================================================


class TestGatherFileTexts:
    """Tests for _gather_file_texts (I/O boundary)."""

    def test_gathers_existing_files(self, tmp_path: Path) -> None:
        """Two existing text files produce two FileText objects."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Preamble text\n--- Page 1 ---\nMSA content here.")
        _write_text_file(tmp_path, "GroupA/Acme Corp/sow.docx", "SOW content with no page markers.")

        file_texts, skipped = analyzer._gather_file_texts(customer)

        assert len(file_texts) == 2
        assert len(skipped) == 0
        # Check that has_page_markers is set correctly.
        paths_to_texts = {ft.file_path: ft for ft in file_texts}
        msa_ft = paths_to_texts["GroupA/Acme Corp/msa.pdf"]
        sow_ft = paths_to_texts["GroupA/Acme Corp/sow.docx"]
        assert msa_ft.has_page_markers is True
        assert sow_ft.has_page_markers is False

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        """Only write 1 of 2 files -- missing one should appear in skipped list."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "MSA content.")

        file_texts, skipped = analyzer._gather_file_texts(customer)

        assert len(file_texts) == 1
        assert len(skipped) == 1
        assert "GroupA/Acme Corp/sow.docx" in skipped

    def test_skips_empty_files(self, tmp_path: Path) -> None:
        """Empty extracted text file should be skipped."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "")  # Empty file
        _write_text_file(tmp_path, "GroupA/Acme Corp/sow.docx", "   \n  ")  # Whitespace-only

        file_texts, skipped = analyzer._gather_file_texts(customer)

        assert len(file_texts) == 0
        assert len(skipped) == 2


# ===================================================================
# TestBuildChunkPrompt
# ===================================================================


class TestBuildChunkPrompt:
    """Tests for _build_chunk_prompt output format."""

    def test_single_chunk_format(self, tmp_path: Path) -> None:
        """Single chunk with 1 segment gets standard format (no Part X of Y)."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        segment = FileSegment(
            file_path="GroupA/Acme Corp/msa.pdf",
            text="Master Service Agreement full text.",
            start_page=1,
            end_page=10,
            total_pages=10,
            is_partial=False,
        )
        chunk = AnalysisChunk(chunk_index=0, total_chunks=1, file_segments=[segment])

        prompt = analyzer._build_chunk_prompt(chunk, customer)

        assert "Acme Corp" in prompt
        assert "msa.pdf" in prompt
        assert "Master Service Agreement full text." in prompt
        # Single chunk: should NOT contain "Part X of Y" language.
        assert "Part 1 of" not in prompt
        assert "Analysis Part" not in prompt

    def test_multi_chunk_format(self, tmp_path: Path) -> None:
        """Multi-chunk prompt includes 'Part X of Y' header."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        segment = FileSegment(
            file_path="GroupA/Acme Corp/msa.pdf",
            text="Chunk 1 content.",
            start_page=1,
            end_page=5,
            total_pages=10,
            is_partial=True,
            part_number=1,
            total_parts=2,
        )
        chunk = AnalysisChunk(chunk_index=0, total_chunks=3, file_segments=[segment])

        prompt = analyzer._build_chunk_prompt(chunk, customer)

        assert "Analysis Part 1 of 3" in prompt
        assert "SUBSET" in prompt
        assert "NOT_ADDRESSED" in prompt

    def test_page_info_in_prompt(self, tmp_path: Path) -> None:
        """Partial segment shows page range info in the document header."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        segment = FileSegment(
            file_path="GroupA/Acme Corp/msa.pdf",
            text="Partial content for pages 15-30.",
            start_page=15,
            end_page=30,
            total_pages=80,
            is_partial=True,
            part_number=2,
            total_parts=4,
        )
        chunk = AnalysisChunk(chunk_index=1, total_chunks=2, file_segments=[segment])

        prompt = analyzer._build_chunk_prompt(chunk, customer)

        assert "Pages 15-30 of 80" in prompt
        assert "Part 2 of 4" in prompt


# ===================================================================
# TestMergeChunkResults
# ===================================================================


class TestMergeChunkResults:
    """Tests for _merge_chunk_results (Phase 2)."""

    def test_yes_overrides_not_addressed(self, tmp_path: Path) -> None:
        """YES from chunk 1 + NOT_ADDRESSED from chunk 2 -> YES wins."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED", confidence="HIGH"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED", confidence="HIGH"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, ["GroupA/Acme Corp/sow.docx"])

        assert merged.columns["Consent Required"].answer == "YES"
        assert merged.columns["Notice Required"].answer == "NOT_ADDRESSED"
        assert conflicted == []

    def test_conflict_detection(self, tmp_path: Path) -> None:
        """YES from chunk 1 + NO from chunk 2 -> conflict detected."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="YES", confidence="HIGH"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NO", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="YES", confidence="HIGH"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # YES has higher priority than NO, so merged answer is YES.
        assert merged.columns["Consent Required"].answer == "YES"
        # But the conflict is detected.
        assert "Consent Required" in conflicted
        # No conflict on Notice Required (both YES).
        assert "Notice Required" not in conflicted

    def test_citation_deduplication(self, tmp_path: Path) -> None:
        """Same citation in two chunks -> deduplicated in merged result."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        shared_citation = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf",
            page="5",
            section_ref="Section 12",
            exact_quote="consent required",
        )
        unique_citation = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf",
            page="10",
            section_ref="Section 15",
            exact_quote="additional clause",
        )

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[shared_citation]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[shared_citation, unique_citation]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # shared_citation appears in both chunks but should be deduplicated.
        citations = merged.columns["Consent Required"].citations
        assert len(citations) == 2  # shared + unique, not 3

    def test_all_not_addressed(self, tmp_path: Path) -> None:
        """Both chunks NOT_ADDRESSED -> merged is NOT_ADDRESSED."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        assert merged.columns["Consent Required"].answer == "NOT_ADDRESSED"
        assert merged.columns["Notice Required"].answer == "NOT_ADDRESSED"
        assert conflicted == []


# ===================================================================
# TestSynthesisPass
# ===================================================================


class TestSynthesisPass:
    """Tests for _synthesis_pass (Phase 3 -- conflict resolution)."""

    @pytest.mark.asyncio
    async def test_synthesis_resolves_conflict(self, tmp_path: Path) -> None:
        """Mock _call_claude to return resolution, verify conflicted column updated."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Merged result has conflicted "Consent Required".
        merged = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="YES", confidence="HIGH"),
            }
        )

        chunk_results = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES"),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="NO"),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
        ]

        synthesis_response = json.dumps(
            {
                "Consent Required": {
                    "answer": "NO",
                    "confidence": "HIGH",
                    "citations": [
                        {
                            "file_path": "GroupA/Acme Corp/msa.pdf",
                            "page": "10",
                            "section_ref": "Section 15",
                            "exact_quote": "amendment overrides consent",
                        }
                    ],
                },
            }
        )

        mock_call = AsyncMock(return_value=synthesis_response)

        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        # Conflicted column should be updated to synthesis result.
        assert result.columns["Consent Required"].answer == "NO"
        assert result.columns["Consent Required"].confidence == "HIGH"
        assert len(result.columns["Consent Required"].citations) == 1
        # Non-conflicted column should be unchanged.
        assert result.columns["Notice Required"].answer == "YES"

    @pytest.mark.asyncio
    async def test_synthesis_failure_keeps_merged(self, tmp_path: Path) -> None:
        """Mock _call_claude to raise, verify original merged result returned."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        merged = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="YES", confidence="HIGH"),
            }
        )

        chunk_results = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES"),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="NO"),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
        ]

        mock_call = AsyncMock(side_effect=RuntimeError("Synthesis API down"))

        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        # On failure, original merged result is returned unchanged.
        assert result.columns["Consent Required"].answer == "YES"
        assert result.columns["Consent Required"].confidence == "MEDIUM"

    @pytest.mark.asyncio
    async def test_synthesis_preserves_non_conflicted(self, tmp_path: Path) -> None:
        """Non-conflicted columns are unchanged after synthesis."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        merged = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="NO", confidence="HIGH"),
            }
        )

        chunk_results = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES"),
                    "Notice Required": _make_column_result(answer="NO"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="NO"),
                    "Notice Required": _make_column_result(answer="NO"),
                }
            ),
        ]

        # Synthesis returns only the conflicted column.
        synthesis_response = json.dumps(
            {
                "Consent Required": {
                    "answer": "NO",
                    "confidence": "HIGH",
                    "citations": [],
                },
            }
        )

        mock_call = AsyncMock(return_value=synthesis_response)

        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        # Non-conflicted column must remain exactly as it was.
        assert result.columns["Notice Required"].answer == "NO"
        assert result.columns["Notice Required"].confidence == "HIGH"


# ===================================================================
# TestValidationPass
# ===================================================================


class TestValidationPass:
    """Tests for _validation_pass (Phase 4 -- NOT_ADDRESSED follow-up)."""

    @pytest.mark.asyncio
    async def test_validation_finds_answer(self, tmp_path: Path) -> None:
        """Mock _call_claude returns YES for NOT_ADDRESSED column, verify updated."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED", confidence="HIGH"),
            }
        )

        file_texts = [_make_file_text(text="Some contract text with notice clauses.")]

        validation_response = json.dumps(
            {
                "Notice Required": {
                    "answer": "YES",
                    "confidence": "MEDIUM",
                    "citations": [
                        {
                            "file_path": "GroupA/Acme Corp/msa.pdf",
                            "page": "7",
                            "section_ref": "Section 5",
                            "exact_quote": "notice shall be given",
                        }
                    ],
                },
            }
        )

        mock_call = AsyncMock(return_value=validation_response)

        with patch.object(analyzer, "_call_claude", mock_call):
            updated = await analyzer._validation_pass(result, file_texts, customer)

        assert updated.columns["Notice Required"].answer == "YES"
        assert len(updated.columns["Notice Required"].citations) == 1
        # Already-answered column should be unchanged.
        assert updated.columns["Consent Required"].answer == "YES"

    @pytest.mark.asyncio
    async def test_validation_failure_keeps_current(self, tmp_path: Path) -> None:
        """Mock _call_claude raises, verify original result returned."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        file_texts = [_make_file_text(text="Some text.")]

        mock_call = AsyncMock(side_effect=RuntimeError("Validation API down"))

        with patch.object(analyzer, "_call_claude", mock_call):
            updated = await analyzer._validation_pass(result, file_texts, customer)

        # On failure, original result is returned unchanged.
        assert updated.columns["Notice Required"].answer == "NOT_ADDRESSED"

    @pytest.mark.asyncio
    async def test_validation_skips_already_answered(self, tmp_path: Path) -> None:
        """No NOT_ADDRESSED columns -> validation not called."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES"),
                "Notice Required": _make_column_result(answer="NO"),
            }
        )

        file_texts = [_make_file_text(text="Some text.")]

        mock_call = AsyncMock()

        with patch.object(analyzer, "_call_claude", mock_call):
            updated = await analyzer._validation_pass(result, file_texts, customer)

        # _call_claude should never have been called.
        mock_call.assert_not_called()
        # Result should be identical.
        assert updated.columns["Consent Required"].answer == "YES"
        assert updated.columns["Notice Required"].answer == "NO"


# ===================================================================
# TestInferDocType
# ===================================================================


class TestInferDocType:
    """Tests for _infer_doc_type static method."""

    def test_infers_known_types(self) -> None:
        """Known filename keywords map to expected document types."""
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/msa.pdf") == "MSA"
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/amendment_v2.docx") == "Amendment"
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/sow_2024.pdf") == "SOW"
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/nda_signed.pdf") == "NDA"
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/order_form.pdf") == "Order Form"
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/exhibit_a.pdf") == "Exhibit"

    def test_defaults_to_contract(self) -> None:
        """Unknown filename defaults to 'Contract'."""
        assert SearchAnalyzer._infer_doc_type("GroupA/Acme Corp/random.pdf") == "Contract"


# ===================================================================
# TestExtractJsonText
# ===================================================================


class TestExtractJsonText:
    """Tests for _extract_json_text — JSON extraction from raw model output."""

    def test_plain_json(self) -> None:
        raw = '{"col": {"answer": "YES"}}'
        assert SearchAnalyzer._extract_json_text(raw) == raw

    def test_markdown_fenced(self) -> None:
        raw = '```json\n{"col": {"answer": "YES"}}\n```'
        result = SearchAnalyzer._extract_json_text(raw)
        assert json.loads(result) == {"col": {"answer": "YES"}}

    def test_preamble_text(self) -> None:
        raw = 'Here is the analysis:\n{"col": {"answer": "NO"}}'
        result = SearchAnalyzer._extract_json_text(raw)
        assert json.loads(result) == {"col": {"answer": "NO"}}

    def test_double_json_extracts_first(self) -> None:
        """When the model returns two JSON objects, extract only the first."""
        obj1 = '{"col": {"answer": "NOT_ADDRESSED", "confidence": "MEDIUM", "citations": []}}'
        obj2 = '{"col": {"answer": "YES", "confidence": "HIGH", "citations": []}}'
        raw = obj1 + "\n" + obj2
        result = SearchAnalyzer._extract_json_text(raw)
        parsed = json.loads(result)
        assert parsed["col"]["answer"] == "NOT_ADDRESSED"

    def test_no_braces(self) -> None:
        raw = "No JSON here at all"
        assert SearchAnalyzer._extract_json_text(raw) == raw
        assert SearchAnalyzer._infer_doc_type("something_else.docx") == "Contract"
        assert SearchAnalyzer._infer_doc_type("") == "Contract"
