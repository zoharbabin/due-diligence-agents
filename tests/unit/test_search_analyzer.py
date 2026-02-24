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
from dd_agents.search.analyzer import SearchAnalyzer, _extract_yes_no, _max_confidence
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
# TestConfidenceNormalization
# ===================================================================


class TestConfidenceNormalization:
    """Tests for confidence casing normalization (Issue 1)."""

    @pytest.mark.asyncio
    async def test_confidence_normalized_to_uppercase(self, tmp_path: Path) -> None:
        """LLM returns mixed-case confidence — parser must normalize to uppercase."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Agreement with consent clause.")

        mock_response_data = {
            "Consent Required": {
                "answer": "YES",
                "confidence": "High",  # Mixed case
                "citations": [],
            },
            "Notice Required": {
                "answer": "NO",
                "confidence": "low",  # Lowercase
                "citations": [],
            },
        }

        mock_call = AsyncMock(return_value=json.dumps(mock_response_data))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert results[0].columns["Consent Required"].confidence == "HIGH"
        assert results[0].columns["Notice Required"].confidence == "LOW"

    def test_confidence_normalized_on_merge(self, tmp_path: Path) -> None:
        """Merge phase normalizes confidence to uppercase."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="High"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED", confidence="medium"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED", confidence="low"),
                "Notice Required": _make_column_result(answer="NO", confidence="Medium"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        assert merged.columns["Consent Required"].confidence == "HIGH"
        assert merged.columns["Notice Required"].confidence == "MEDIUM"

    @pytest.mark.asyncio
    async def test_confidence_normalized_in_synthesis(self, tmp_path: Path) -> None:
        """Synthesis pass (Phase 3) normalizes confidence to uppercase."""
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

        synthesis_response = json.dumps(
            {
                "Consent Required": {
                    "answer": "NO",
                    "confidence": "High",  # Mixed case from LLM
                    "citations": [],
                },
            }
        )

        mock_call = AsyncMock(return_value=synthesis_response)
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        assert result.columns["Consent Required"].confidence == "HIGH"

    @pytest.mark.asyncio
    async def test_confidence_normalized_in_validation(self, tmp_path: Path) -> None:
        """Validation pass (Phase 4) normalizes confidence to uppercase."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED", confidence="HIGH"),
            }
        )
        file_texts = [_make_file_text(text="Contract text with notice clauses.")]

        validation_response = json.dumps(
            {
                "Notice Required": {
                    "answer": "YES",
                    "confidence": "medium",  # Lowercase from LLM
                    "citations": [],
                },
            }
        )

        mock_call = AsyncMock(return_value=validation_response)
        with patch.object(analyzer, "_call_claude", mock_call):
            updated = await analyzer._validation_pass(result, file_texts, customer)

        assert updated.columns["Notice Required"].confidence == "MEDIUM"


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
# TestParallelChunkAnalysis
# ===================================================================


class TestParallelChunkAnalysis:
    """Tests for concurrent chunk processing in _analyze_customer (Issue #21)."""

    @pytest.mark.asyncio
    async def test_multi_chunk_runs_concurrently(self, tmp_path: Path) -> None:
        """Multiple chunks should be dispatched via asyncio.gather, not sequentially."""
        analyzer = _make_analyzer(tmp_path)

        # Write a large text file that will be split into multiple chunks.
        text_parts = []
        for i in range(1, 100):
            text_parts.append(f"\n--- Page {i} ---\n")
            text_parts.append(f"Page {i} legal content. " * 500)
        big_text = "".join(text_parts)
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", big_text)

        customer = CustomerEntry(
            group="GroupA",
            name="Acme Corp",
            safe_name="acme",
            path="GroupA/Acme Corp",
            file_count=1,
            files=["GroupA/Acme Corp/msa.pdf"],
        )

        call_count = 0

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps(
                {
                    "Consent Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                    "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                }
            )

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            result = await analyzer._analyze_customer(customer)

        # Should have called Claude for multiple chunks (Phase 1) + validation (Phase 4).
        assert call_count >= 2
        # All calls succeeded without error.
        assert result.error is None or result.error == ""
        # Chunks were analyzed.
        assert result.chunks_analyzed >= 2


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

    def test_verbose_not_addressed_treated_as_not_addressed(self, tmp_path: Path) -> None:
        """NOT_ADDRESSED with explanation text must NOT beat a real free-text summary.

        Regression test: the model sometimes returns
        'NOT_ADDRESSED. The portions of the agreement reviewed (Part 1 of 4)...'
        which must be treated as NOT_ADDRESSED (priority 1), not as
        substantive free-text (priority 2).
        """
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Chunk 1: verbose NOT_ADDRESSED explanation (the early partial review).
        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer=(
                        "NOT_ADDRESSED. The portions of the agreement "
                        "reviewed (Part 1 of 4) do not contain an explicit "
                        "obligation on the Supplier to obtain consent."
                    ),
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        # Chunk 2: actual substantive summary from the later chunk.
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="Section 12.1 requires prior written consent for any change of control.",
                    confidence="HIGH",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # The substantive summary (priority 2) must win over the verbose
        # NOT_ADDRESSED (priority 1), regardless of ordering.
        assert "Section 12.1" in merged.columns["Consent Required"].answer
        assert "NOT_ADDRESSED" not in merged.columns["Consent Required"].answer.upper()

    def test_longer_free_text_preferred(self, tmp_path: Path) -> None:
        """When two chunks provide free-text at the same priority, the longer one wins."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="Short answer."),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="A much longer and more detailed answer with specific section references."
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        assert "much longer" in merged.columns["Consent Required"].answer

    def test_citation_dedup_normalizes_whitespace(self, tmp_path: Path) -> None:
        """Citations with trailing whitespace in keys should be deduplicated."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        cit_clean = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf",
            page="5",
            section_ref="Section 12",
            exact_quote="consent required",
        )
        cit_whitespace = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf ",  # trailing space
            page="5 ",  # trailing space
            section_ref="Section 12",
            exact_quote="consent required ",  # same quote with trailing space
        )

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_clean]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_whitespace]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # Whitespace-only difference in keys should be deduplicated.
        assert len(merged.columns["Consent Required"].citations) == 1

    def test_citation_dedup_preserves_distinct_quotes(self, tmp_path: Path) -> None:
        """Different quotes from the same page/section must NOT be deduplicated.  Issue #17."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        cit_a = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf",
            page="5",
            section_ref="Section 12",
            exact_quote="consent of the other party is required",
        )
        cit_b = SearchCitation(
            file_path="GroupA/Acme Corp/msa.pdf",
            page="5",
            section_ref="Section 12",
            exact_quote="prior written notice shall be provided",
        )

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_a]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_b]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # Both citations must survive — they have different exact_quote values.
        citations = merged.columns["Consent Required"].citations
        assert len(citations) == 2
        quotes = {c.exact_quote for c in citations}
        assert "consent of the other party is required" in quotes
        assert "prior written notice shall be provided" in quotes

    def test_confidence_takes_max_when_answers_agree(self, tmp_path: Path) -> None:
        """When two chunks agree at the same priority, the higher confidence wins.  Issue #22."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Both chunks return literal YES (priority 3), but different confidences.
        # Chunk 1 is processed first, so its answer/confidence become the initial best.
        # Chunk 2 has the same priority and same answer length, so is_better is False.
        # The _max_confidence fix should still promote the confidence to HIGH.
        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        assert merged.columns["Consent Required"].answer == "YES"
        assert merged.columns["Consent Required"].confidence == "HIGH"

    def test_confidence_takes_max_for_free_text(self, tmp_path: Path) -> None:
        """When a longer free-text answer wins, a shorter answer's higher confidence is kept."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Chunk 1: longer free-text with MEDIUM confidence.
        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="Section 12.1 requires prior written consent for any change of control.",
                    confidence="MEDIUM",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        # Chunk 2: shorter free-text with HIGH confidence.
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="Consent is required.",
                    confidence="HIGH",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # Chunk 1's longer answer wins, but chunk 2's HIGH confidence should be kept.
        assert "Section 12.1" in merged.columns["Consent Required"].answer
        assert merged.columns["Consent Required"].confidence == "HIGH"

    def test_free_text_no_triggers_conflict_with_yes(self, tmp_path: Path) -> None:
        """Free-text starting with 'NO' should conflict with literal 'YES'.  Issue #18."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="NO - the amendment removed the consent requirement.",
                    confidence="MEDIUM",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # The free-text "NO - ..." should trigger a conflict with "YES".
        assert "Consent Required" in conflicted

    def test_free_text_yes_triggers_conflict_with_no(self, tmp_path: Path) -> None:
        """Free-text starting with 'YES' should conflict with literal 'NO'.  Issue #18."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NO", confidence="HIGH"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="YES, consent is required per Section 12.",
                    confidence="MEDIUM",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        assert "Consent Required" in conflicted

    def test_free_text_without_yes_no_no_conflict(self, tmp_path: Path) -> None:
        """Free-text that doesn't start with YES/NO should not trigger false conflicts."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="Section 12 requires consent from both parties.",
                    confidence="HIGH",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(
                    answer="The agreement stipulates mutual consent is needed.",
                    confidence="MEDIUM",
                ),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])

        # Neither answer starts with YES or NO, so no conflict should be detected.
        assert "Consent Required" not in conflicted


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

    @pytest.mark.asyncio
    async def test_synthesis_preserves_long_quotes(self, tmp_path: Path) -> None:
        """Synthesis prompt should include quotes longer than 200 chars.  Issue #20."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        long_quote = "A" * 500  # 500-char quote

        merged = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                "Notice Required": _make_column_result(answer="YES", confidence="HIGH"),
            }
        )

        chunk_results = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(
                        answer="YES",
                        citations=[
                            SearchCitation(
                                file_path="GroupA/Acme Corp/msa.pdf",
                                page="5",
                                section_ref="Section 12",
                                exact_quote=long_quote,
                            )
                        ],
                    ),
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
                    "answer": "YES",
                    "confidence": "HIGH",
                    "citations": [],
                },
            }
        )

        captured_prompt: list[str] = []

        async def mock_call(system: str, user: str) -> str:
            captured_prompt.append(user)
            return synthesis_response

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        # The 500-char quote should be included (budget allows up to 1000 for few citations).
        prompt = captured_prompt[0]
        assert long_quote in prompt


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

    @pytest.mark.asyncio
    async def test_validation_uses_document_order(self, tmp_path: Path) -> None:
        """Validation pass should include files in document order, not sorted by size.  Issue #19."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        # MSA is larger, SOW is smaller.  Both fit within TARGET_CHUNK_CHARS.
        msa_text = "MSA content " * 100  # ~1200 chars
        sow_text = "SOW content " * 10  # ~120 chars
        file_texts = [
            _make_file_text(file_path="GroupA/Acme Corp/msa.pdf", text=msa_text),
            _make_file_text(file_path="GroupA/Acme Corp/sow.docx", text=sow_text),
        ]

        validation_response = json.dumps(
            {
                "Consent Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
            }
        )

        captured_prompt: list[str] = []

        async def mock_call(system: str, user: str) -> str:
            captured_prompt.append(user)
            return validation_response

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            await analyzer._validation_pass(result, file_texts, customer)

        # The MSA (first in document order, despite being larger) should appear
        # before the SOW in the prompt sent to Claude.
        prompt = captured_prompt[0]
        msa_pos = prompt.find("msa.pdf")
        sow_pos = prompt.find("sow.docx")
        assert msa_pos < sow_pos, "MSA should appear before SOW (document order, not size order)"

    @pytest.mark.asyncio
    async def test_validation_splits_oversized_file(self, tmp_path: Path) -> None:
        """When a file exceeds budget, take the leading segment at natural boundaries.  Issue #19."""
        from dd_agents.search.chunker import TARGET_CHUNK_CHARS

        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        # Create a file that exceeds TARGET_CHUNK_CHARS with page markers.
        pages = []
        for i in range(1, 200):
            pages.append(f"\n--- Page {i} ---\n")
            pages.append(f"Page {i} content with legal clauses. " * 100)
        big_text = "".join(pages)
        assert len(big_text) > TARGET_CHUNK_CHARS

        file_texts = [_make_file_text(file_path="GroupA/Acme Corp/msa.pdf", text=big_text, has_page_markers=True)]

        validation_response = json.dumps(
            {
                "Consent Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
            }
        )

        captured_prompt: list[str] = []

        async def mock_call(system: str, user: str) -> str:
            captured_prompt.append(user)
            return validation_response

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            await analyzer._validation_pass(result, file_texts, customer)

        # The prompt should contain the file but NOT all of it (it was split).
        prompt = captured_prompt[0]
        assert "msa.pdf (partial)" in prompt
        # The prompt should be roughly within the target size (not the full file).
        assert len(prompt) < len(big_text)


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

    def test_fallback_validates_json(self) -> None:
        """rfind fallback must validate result with json.loads().  Issue #23.

        When raw_decode fails and rfind('}') produces invalid JSON, the method
        should return the original cleaned text rather than the malformed substring.
        """
        # Construct input where raw_decode fails (truncated JSON) and rfind('}')
        # would return an invalid substring: the brace is inside a string value.
        raw = '{"col": {"answer": "YES, see section 12.3} for details"'
        result = SearchAnalyzer._extract_json_text(raw)
        # The rfind fallback would return '{"col": {"answer": "YES, see section 12.3}'
        # which is invalid JSON.  With the fix, it falls through to return cleaned.
        # The result should NOT be the invalid substring.
        import contextlib

        with contextlib.suppress(json.JSONDecodeError):
            json.loads(result)
        # The key assertion: the result should NOT be the truncated rfind output.
        assert result != '{"col": {"answer": "YES, see section 12.3}'

    def test_fallback_returns_valid_json_when_possible(self) -> None:
        """rfind fallback returns result when it IS valid JSON.  Issue #23."""
        # Truncated JSON where rfind('}') happens to produce valid JSON.
        valid_obj = '{"col": {"answer": "YES"}}'
        raw = valid_obj + " some trailing garbage without braces"
        result = SearchAnalyzer._extract_json_text(raw)
        # raw_decode should handle this case (primary path), but if it were to
        # fall through, the rfind result is valid and should be returned.
        parsed = json.loads(result)
        assert parsed["col"]["answer"] == "YES"


# ===================================================================
# TestExtractYesNo
# ===================================================================


class TestExtractYesNo:
    """Tests for _extract_yes_no helper (Issue #18)."""

    def test_literal_yes(self) -> None:
        assert _extract_yes_no("YES") == "YES"

    def test_literal_no(self) -> None:
        assert _extract_yes_no("NO") == "NO"

    def test_yes_with_comma(self) -> None:
        assert _extract_yes_no("YES, CONSENT IS REQUIRED PER SECTION 12.") == "YES"

    def test_no_with_dash(self) -> None:
        assert _extract_yes_no("NO - THE AMENDMENT REMOVED THIS REQUIREMENT.") == "NO"

    def test_yes_with_period(self) -> None:
        assert _extract_yes_no("YES. THE AGREEMENT REQUIRES CONSENT.") == "YES"

    def test_no_with_space(self) -> None:
        assert _extract_yes_no("NO THE CONTRACT DOES NOT REQUIRE CONSENT") == "NO"

    def test_free_text_no_prefix(self) -> None:
        """Free-text that doesn't start with YES/NO should be returned as-is."""
        text = "THE AGREEMENT REQUIRES MUTUAL CONSENT"
        assert _extract_yes_no(text) == text

    def test_not_addressed(self) -> None:
        """NOT_ADDRESSED should be returned as-is (not confused with NO)."""
        assert _extract_yes_no("NOT_ADDRESSED") == "NOT_ADDRESSED"

    def test_notice_not_confused_with_no(self) -> None:
        """'NOTICE' starts with 'NO' but the next char is alphanumeric — should NOT match."""
        assert _extract_yes_no("NOTICE IS REQUIRED") == "NOTICE IS REQUIRED"

    def test_yesterday_not_confused_with_yes(self) -> None:
        """'YESTERDAY' starts with 'YES' but the next char is alphanumeric."""
        assert _extract_yes_no("YESTERDAY WAS THE DEADLINE") == "YESTERDAY WAS THE DEADLINE"


# ===================================================================
# TestMaxConfidence
# ===================================================================


class TestMaxConfidence:
    """Tests for _max_confidence helper (Issue #22)."""

    def test_high_beats_medium(self) -> None:
        assert _max_confidence("HIGH", "MEDIUM") == "HIGH"

    def test_medium_beats_low(self) -> None:
        assert _max_confidence("LOW", "MEDIUM") == "MEDIUM"

    def test_high_beats_low(self) -> None:
        assert _max_confidence("HIGH", "LOW") == "HIGH"

    def test_equal_returns_first(self) -> None:
        assert _max_confidence("HIGH", "HIGH") == "HIGH"

    def test_empty_loses(self) -> None:
        assert _max_confidence("", "LOW") == "LOW"
        assert _max_confidence("MEDIUM", "") == "MEDIUM"

    def test_both_empty(self) -> None:
        result = _max_confidence("", "")
        assert result == ""

    def test_mixed_case_returns_uppercase(self) -> None:
        """_max_confidence should always return normalized uppercase."""
        # "high" (rank 3) > "MEDIUM" (rank 2), result normalized to uppercase.
        assert _max_confidence("high", "MEDIUM") == "HIGH"
        assert _max_confidence("high", "low") == "HIGH"
        # "medium" (rank 2) > "low" (rank 1).
        assert _max_confidence("medium", "low") == "MEDIUM"

    def test_whitespace_stripped(self) -> None:
        assert _max_confidence(" HIGH ", " LOW ") == "HIGH"

    def test_unknown_value_ranks_below_low(self) -> None:
        assert _max_confidence("CRITICAL", "LOW") == "LOW"
        assert _max_confidence("LOW", "UNKNOWN") == "LOW"


# ===================================================================
# TestExtractYesNo — Additional Edge Cases
# ===================================================================


class TestExtractYesNoEdgeCases:
    """Additional edge cases for _extract_yes_no (Issue #18)."""

    def test_empty_string(self) -> None:
        assert _extract_yes_no("") == ""

    def test_none_word_not_confused_with_no(self) -> None:
        """'NONE' starts with 'NO' but next char 'N' is alphanumeric."""
        assert _extract_yes_no("NONE") == "NONE"
        assert _extract_yes_no("NONE REQUIRED") == "NONE REQUIRED"

    def test_north_not_confused_with_no(self) -> None:
        assert _extract_yes_no("NORTH AMERICA") == "NORTH AMERICA"

    def test_normal_not_confused_with_no(self) -> None:
        assert _extract_yes_no("NORMAL TERMS APPLY") == "NORMAL TERMS APPLY"

    def test_yester_not_confused_with_yes(self) -> None:
        assert _extract_yes_no("YESTER") == "YESTER"

    def test_no_parenthetical(self) -> None:
        """'NO (' — non-alnum char after NO should match."""
        assert _extract_yes_no("NO (SEE SECTION 3)") == "NO"

    def test_yes_colon(self) -> None:
        assert _extract_yes_no("YES: PER SECTION 12") == "YES"


# ===================================================================
# TestExtractLeadingSegment
# ===================================================================


class TestExtractLeadingSegment:
    """Tests for _extract_leading_segment helper (Issue #19)."""

    def test_text_shorter_than_max_returned_as_is(self) -> None:
        from dd_agents.search.analyzer import _extract_leading_segment

        ft = _make_file_text(text="Short text", has_page_markers=False)
        result = _extract_leading_segment(ft, 1000)
        assert result == "Short text"

    def test_page_markers_split_at_boundary(self) -> None:
        """Oversized file with page markers should split at page boundary."""
        from dd_agents.search.analyzer import _extract_leading_segment

        pages = []
        for i in range(1, 20):
            pages.append(f"\n--- Page {i} ---\n")
            pages.append(f"Page {i} content. " * 200)
        big_text = "".join(pages)

        ft = _make_file_text(text=big_text, has_page_markers=True)
        result = _extract_leading_segment(ft, 5000)

        # Should be a subset of the text, split at page boundary.
        assert len(result) <= len(big_text)
        assert len(result) > 0
        assert "Page 1 content" in result

    def test_no_page_markers_split_at_paragraph(self) -> None:
        """Oversized file without page markers should split at paragraph boundary."""
        from dd_agents.search.analyzer import _extract_leading_segment

        paragraphs = "\n\n".join(f"Paragraph {i}. " * 100 for i in range(50))

        ft = _make_file_text(text=paragraphs, has_page_markers=False)
        result = _extract_leading_segment(ft, 3000)

        assert len(result) <= len(paragraphs)
        assert len(result) > 0
        assert "Paragraph 0" in result

    def test_empty_text(self) -> None:
        from dd_agents.search.analyzer import _extract_leading_segment

        ft = _make_file_text(text="", has_page_markers=False)
        result = _extract_leading_segment(ft, 1000)
        assert result == ""


# ===================================================================
# TestMerge — Additional Edge Cases
# ===================================================================


class TestMergeEdgeCases:
    """Additional edge cases for _merge_chunk_results."""

    def test_three_chunks_escalating_confidence(self, tmp_path: Path) -> None:
        """LOW → MEDIUM → HIGH across 3 chunks. Final confidence should be HIGH."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunks = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES", confidence="LOW"),
                    "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES", confidence="MEDIUM"),
                    "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES", confidence="HIGH"),
                    "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
                }
            ),
        ]

        merged, _ = analyzer._merge_chunk_results(chunks, customer, 1, [])
        assert merged.columns["Consent Required"].confidence == "HIGH"

    def test_notice_answer_does_not_conflict_with_yes(self, tmp_path: Path) -> None:
        """'NOTICE IS REQUIRED' is free-text, not NO — should not conflict with YES."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOTICE IS REQUIRED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        _, conflicted = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])
        assert "Consent Required" not in conflicted

    def test_citation_dedup_handles_empty_quotes(self, tmp_path: Path) -> None:
        """Empty and whitespace-only quotes should be treated as duplicates."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        cit_empty = SearchCitation(file_path="a.pdf", page="1", section_ref="S1", exact_quote="")
        cit_space = SearchCitation(file_path="a.pdf", page="1", section_ref="S1", exact_quote="   ")

        chunk1 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_empty]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )
        chunk2 = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES", citations=[cit_space]),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        merged, _ = analyzer._merge_chunk_results([chunk1, chunk2], customer, 1, [])
        assert len(merged.columns["Consent Required"].citations) == 1


# ===================================================================
# TestSynthesis — Additional Edge Cases
# ===================================================================


class TestSynthesisEdgeCases:
    """Additional edge cases for _synthesis_pass."""

    @pytest.mark.asyncio
    async def test_zero_citations_no_division_error(self, tmp_path: Path) -> None:
        """When conflicting chunks have no citations, quote budget math should not crash."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        merged = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="YES"),
                "Notice Required": _make_column_result(answer="YES"),
            }
        )
        chunk_results = [
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="YES", citations=[]),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
            _make_customer_result(
                columns={
                    "Consent Required": _make_column_result(answer="NO", citations=[]),
                    "Notice Required": _make_column_result(answer="YES"),
                }
            ),
        ]

        synthesis_response = json.dumps({"Consent Required": {"answer": "YES", "confidence": "HIGH", "citations": []}})
        mock_call = AsyncMock(return_value=synthesis_response)

        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer._synthesis_pass(merged, chunk_results, ["Consent Required"], customer)

        assert result.columns["Consent Required"].answer == "YES"


# ===================================================================
# TestValidation — Additional Edge Cases
# ===================================================================


class TestValidationEdgeCases:
    """Additional edge cases for _validation_pass (Issue #19)."""

    @pytest.mark.asyncio
    async def test_all_files_exceed_budget(self, tmp_path: Path) -> None:
        """When all files exceed budget, take first file's leading segment."""
        from dd_agents.search.chunker import TARGET_CHUNK_CHARS

        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        # Both files exceed TARGET_CHUNK_CHARS.
        huge_text = "X " * (TARGET_CHUNK_CHARS + 500)
        file_texts = [
            _make_file_text(file_path="GroupA/Acme Corp/msa.pdf", text=huge_text),
            _make_file_text(file_path="GroupA/Acme Corp/sow.docx", text=huge_text),
        ]

        validation_response = json.dumps(
            {
                "Consent Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
            }
        )

        captured_prompt: list[str] = []

        async def mock_call(system: str, user: str) -> str:
            captured_prompt.append(user)
            return validation_response

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            await analyzer._validation_pass(result, file_texts, customer)

        prompt = captured_prompt[0]
        # First file should be included (partial), second should not.
        assert "msa.pdf (partial)" in prompt
        assert "sow.docx" not in prompt

    @pytest.mark.asyncio
    async def test_first_file_fits_second_partially(self, tmp_path: Path) -> None:
        """First file fits whole, second file is split at boundary."""
        from dd_agents.search.chunker import TARGET_CHUNK_CHARS

        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        result = _make_customer_result(
            columns={
                "Consent Required": _make_column_result(answer="NOT_ADDRESSED"),
                "Notice Required": _make_column_result(answer="NOT_ADDRESSED"),
            }
        )

        small_text = "Small file content. " * 100  # ~2000 chars
        large_text = "L " * TARGET_CHUNK_CHARS  # Exceeds remaining budget
        file_texts = [
            _make_file_text(file_path="GroupA/Acme Corp/msa.pdf", text=small_text),
            _make_file_text(file_path="GroupA/Acme Corp/sow.docx", text=large_text),
        ]

        validation_response = json.dumps(
            {
                "Consent Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
            }
        )

        captured_prompt: list[str] = []

        async def mock_call(system: str, user: str) -> str:
            captured_prompt.append(user)
            return validation_response

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            await analyzer._validation_pass(result, file_texts, customer)

        prompt = captured_prompt[0]
        # Both files should appear: first whole, second partial.
        assert "msa.pdf" in prompt
        assert "sow.docx (partial)" in prompt


# ===================================================================
# TestParallelChunkFailure
# ===================================================================


class TestParallelChunkFailure:
    """Tests for parallel chunk resilience (Issue #21)."""

    @pytest.mark.asyncio
    async def test_one_chunk_fails_others_succeed(self, tmp_path: Path) -> None:
        """If one chunk's analysis crashes, the others should still be merged."""
        analyzer = _make_analyzer(tmp_path)

        # Write a large file that will be split into multiple chunks.
        pages = []
        for i in range(1, 100):
            pages.append(f"\n--- Page {i} ---\n")
            pages.append(f"Page {i} content with legal clauses. " * 500)
        big_text = "".join(pages)
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", big_text)

        customer = CustomerEntry(
            group="GroupA",
            name="Acme Corp",
            safe_name="acme",
            path="GroupA/Acme Corp",
            file_count=1,
            files=["GroupA/Acme Corp/msa.pdf"],
        )

        call_number = 0

        async def mock_call(system: str, user: str) -> str:
            nonlocal call_number
            call_number += 1
            # Fail the first chunk, succeed on all others.
            if call_number == 1:
                raise RuntimeError("Simulated chunk failure")
            return json.dumps(
                {
                    "Consent Required": {"answer": "YES", "confidence": "HIGH", "citations": []},
                    "Notice Required": {"answer": "NOT_ADDRESSED", "confidence": "HIGH", "citations": []},
                }
            )

        with patch.object(analyzer, "_call_claude", side_effect=mock_call):
            result = await analyzer._analyze_customer(customer)

        # Despite one chunk failing, we should still have a result (not a crash).
        assert result.customer_name == "Acme Corp"
        # The successful chunks should provide an answer.
        assert result.columns.get("Consent Required") is not None
        # Chunks were analyzed (multiple).
        assert result.chunks_analyzed >= 2


# ===================================================================
# TestNonTransientErrors
# ===================================================================


class TestNonTransientErrors:
    """Tests for non-transient error handling (no retry on permanent errors)."""

    @pytest.mark.asyncio
    async def test_prompt_too_long_no_retry(self, tmp_path: Path) -> None:
        """'Prompt is too long' error should not be retried."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Content")

        mock_call = AsyncMock(side_effect=RuntimeError("Prompt is too long"))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        # Should only call once (no retries for non-transient).
        assert mock_call.call_count == 1
        assert results[0].error is not None
        assert "Prompt is too long" in results[0].error

    @pytest.mark.asyncio
    async def test_context_length_no_retry(self, tmp_path: Path) -> None:
        """'context length' error should not be retried."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Content")

        mock_call = AsyncMock(side_effect=RuntimeError("exceeds context length limit"))

        with patch.object(analyzer, "_call_claude", mock_call):
            results = await analyzer.analyze_all([customer])

        assert mock_call.call_count == 1
        assert "context length" in results[0].error


# ===================================================================
# External reference isolation — guardrail test
# ===================================================================


class TestExternalReferenceIsolation:
    """Verify external reference files never leak into customer analysis.

    External T&C downloads (``__external__*.md``) live in the same text
    directory as customer extractions.  The analyzer must only load files
    from ``customer.files`` — never by globbing the text directory.
    """

    @pytest.mark.asyncio
    async def test_external_files_not_included_in_analysis(self, tmp_path: Path) -> None:
        """__external__ files in text_dir are invisible to the analyzer."""
        analyzer = _make_analyzer(tmp_path)
        customer = _make_customer()

        # Write the customer's actual file.
        _write_text_file(tmp_path, "GroupA/Acme Corp/msa.pdf", "Customer contract text.")

        # Write an external reference to the same text directory.
        text_dir = tmp_path / "data_room" / "_dd" / "forensic-dd" / "index" / "text"
        (text_dir / "__external__aws_amazon_com_agreement.md").write_text(
            "# External Reference: https://aws.amazon.com/agreement\n\n"
            "AWS Customer Agreement with assignment restrictions."
        )

        file_texts, skipped = analyzer._gather_file_texts(customer)

        # Only the customer file should be loaded, not the external reference.
        assert len(file_texts) == 1
        assert file_texts[0].file_path == "GroupA/Acme Corp/msa.pdf"
        assert "aws" not in file_texts[0].text.lower()


# ---------------------------------------------------------------------------
# Test answer normalization (Issue #24)
# ---------------------------------------------------------------------------


class TestAnswerNormalization:
    """Tests for _normalize_answer in parse_column_result."""

    def test_unable_to_determine(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Unable to determine from the provided documents") == "NOT_ADDRESSED"

    def test_cannot_determine(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Cannot determine based on available information") == "NOT_ADDRESSED"

    def test_insufficient_information(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Insufficient information to answer this question") == "NOT_ADDRESSED"

    def test_cannot_be_determined(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Cannot be determined from the contract text") == "NOT_ADDRESSED"

    def test_could_not_determine(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Could not determine whether consent is required") == "NOT_ADDRESSED"

    def test_indeterminate(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Indeterminate") == "NOT_ADDRESSED"

    def test_yes_unchanged(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("YES") == "YES"

    def test_no_unchanged(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("NO") == "NO"

    def test_not_addressed_unchanged(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("NOT_ADDRESSED") == "NOT_ADDRESSED"

    def test_substantive_free_text_preserved(self) -> None:
        from dd_agents.models.search import _normalize_answer

        answer = "YES - Section 12.3 requires prior written consent"
        assert _normalize_answer(answer) == answer

    def test_empty_string_unchanged(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("") == ""

    def test_whitespace_stripped(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("  YES  ") == "YES"

    def test_case_insensitive_detection(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("unable to determine...") == "NOT_ADDRESSED"

    def test_normalization_in_parse_column_result(self) -> None:
        """parse_column_result applies answer normalization."""
        from dd_agents.models.search import parse_column_result

        result = parse_column_result(
            {
                "answer": "Unable to determine from the provided document whether consent is required",
                "confidence": "LOW",
                "citations": [],
            }
        )
        assert result.answer == "NOT_ADDRESSED"


# ---------------------------------------------------------------------------
# Test parse-time citation dedup (Issue #24)
# ---------------------------------------------------------------------------


class TestParseTimeCitationDedup:
    """Tests for citation deduplication at parse time."""

    def test_duplicate_citations_removed(self) -> None:
        from dd_agents.models.search import parse_column_result

        result = parse_column_result(
            {
                "answer": "YES",
                "confidence": "HIGH",
                "citations": [
                    {
                        "file_path": "GroupA/Customer/msa.pdf",
                        "page": "5",
                        "section_ref": "Section 12.3",
                        "exact_quote": "Consent is required.",
                    },
                    {
                        "file_path": "GroupA/Customer/msa.pdf",
                        "page": "5",
                        "section_ref": "Section 12.3",
                        "exact_quote": "Consent is required.",
                    },
                ],
            }
        )
        assert len(result.citations) == 1

    def test_different_quotes_preserved(self) -> None:
        from dd_agents.models.search import parse_column_result

        result = parse_column_result(
            {
                "answer": "YES",
                "confidence": "HIGH",
                "citations": [
                    {
                        "file_path": "GroupA/Customer/msa.pdf",
                        "page": "5",
                        "section_ref": "Section 12.3",
                        "exact_quote": "Consent is required.",
                    },
                    {
                        "file_path": "GroupA/Customer/msa.pdf",
                        "page": "5",
                        "section_ref": "Section 12.3",
                        "exact_quote": "Written notice must be provided 30 days prior.",
                    },
                ],
            }
        )
        assert len(result.citations) == 2

    def test_whitespace_differences_deduped(self) -> None:
        """Citations that differ only by leading/trailing whitespace are deduped."""
        from dd_agents.models.search import parse_column_result

        result = parse_column_result(
            {
                "answer": "YES",
                "confidence": "HIGH",
                "citations": [
                    {
                        "file_path": "GroupA/Customer/msa.pdf",
                        "page": "5",
                        "section_ref": "Section 12.3",
                        "exact_quote": "Consent is required.",
                    },
                    {
                        "file_path": " GroupA/Customer/msa.pdf ",
                        "page": " 5 ",
                        "section_ref": " Section 12.3 ",
                        "exact_quote": " Consent is required. ",
                    },
                ],
            }
        )
        assert len(result.citations) == 1

    def test_dedup_function_directly(self) -> None:
        from dd_agents.models.search import SearchCitation, dedup_citations

        citations = [
            SearchCitation(file_path="a.pdf", page="1", section_ref="S1", exact_quote="Quote A"),
            SearchCitation(file_path="a.pdf", page="1", section_ref="S1", exact_quote="Quote A"),
            SearchCitation(file_path="b.pdf", page="2", section_ref="S2", exact_quote="Quote B"),
        ]
        result = dedup_citations(citations)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Test answer normalization coverage (Issue #24 — additional patterns)
# ---------------------------------------------------------------------------


class TestAnswerNormalizationAdditional:
    """Additional normalization patterns discovered during E2E audit."""

    def test_not_determinable(self) -> None:
        from dd_agents.models.search import _normalize_answer

        assert _normalize_answer("Not determinable from the provided documents") == "NOT_ADDRESSED"

    def test_validation_phase_normalizes(self) -> None:
        """parse_column_result used in validation phase catches non-standard answers.

        Regression test for bug where validation phase bypassed
        parse_column_result, allowing 'Unable to determine...' to
        overwrite the normalized NOT_ADDRESSED from the map phase.
        """
        from dd_agents.models.search import parse_column_result

        # Simulate validation response with non-standard answer.
        result = parse_column_result(
            {
                "answer": "Unable to determine from the provided document."
                " The one-page PO does not contain relevant provisions.",
                "confidence": "LOW",
                "citations": [],
            }
        )
        # After normalization, this should be NOT_ADDRESSED.
        assert result.answer == "NOT_ADDRESSED"

    def test_validation_skip_check_works_after_normalization(self) -> None:
        """Validation skip check sees normalized answer, not raw."""
        from dd_agents.models.search import parse_column_result

        result = parse_column_result(
            {
                "answer": "Not determinable from these documents",
                "confidence": "LOW",
                "citations": [],
            }
        )
        # After normalization, this is NOT_ADDRESSED.
        # The validation phase's skip check (answer.upper() == "NOT_ADDRESSED")
        # should now correctly see this as NOT_ADDRESSED and skip it.
        assert result.answer == "NOT_ADDRESSED"
        assert result.answer.upper().strip() == "NOT_ADDRESSED"
