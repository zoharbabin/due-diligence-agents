"""Unit tests for search Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dd_agents.models.search import (
    SearchCitation,
    SearchColumn,
    SearchColumnResult,
    SearchPrompts,
    SearchSubjectResult,
)


class TestSearchColumn:
    """Tests for SearchColumn validation."""

    def test_valid_column(self) -> None:
        col = SearchColumn(name="Consent Required", prompt="Does this agreement require consent? Answer YES or NO.")
        assert col.name == "Consent Required"
        assert "consent" in col.prompt.lower()

    def test_name_too_long(self) -> None:
        with pytest.raises(ValidationError):
            SearchColumn(name="x" * 101, prompt="A valid prompt that is long enough.")

    def test_name_empty(self) -> None:
        with pytest.raises(ValidationError):
            SearchColumn(name="", prompt="A valid prompt that is long enough.")

    def test_prompt_too_short(self) -> None:
        with pytest.raises(ValidationError):
            SearchColumn(name="Valid", prompt="Short")

    def test_prompt_max_length(self) -> None:
        with pytest.raises(ValidationError):
            SearchColumn(name="Valid", prompt="x" * 2001)


class TestSearchPrompts:
    """Tests for SearchPrompts validation."""

    def test_valid_prompts(self) -> None:
        data = {
            "name": "Test Analysis",
            "description": "A test analysis",
            "columns": [
                {"name": "Q1", "prompt": "A valid prompt that is long enough to pass."},
            ],
        }
        prompts = SearchPrompts.model_validate(data)
        assert prompts.name == "Test Analysis"
        assert len(prompts.columns) == 1

    def test_empty_columns_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SearchPrompts(name="Test", columns=[])

    def test_extra_fields_rejected(self) -> None:
        """extra='forbid' should catch typos."""
        with pytest.raises(ValidationError):
            SearchPrompts.model_validate(
                {
                    "name": "Test",
                    "columns": [{"name": "Q1", "prompt": "A valid prompt that is long enough."}],
                    "colunms": [],  # typo
                }
            )

    def test_description_defaults_empty(self) -> None:
        prompts = SearchPrompts(
            name="Test",
            columns=[SearchColumn(name="Q1", prompt="A valid prompt that is long enough.")],
        )
        assert prompts.description == ""


class TestSearchResults:
    """Tests for result models."""

    def test_success_result(self) -> None:
        result = SearchSubjectResult(
            subject_name="Acme Corp",
            group="GroupA",
            files_analyzed=3,
            columns={
                "Q1": SearchColumnResult(
                    answer="YES",
                    confidence="high",
                    citations=[
                        SearchCitation(
                            file_path="msa.pdf",
                            page="5",
                            section_ref="Section 12.3",
                            exact_quote="Upon change of control...",
                        )
                    ],
                )
            },
        )
        assert result.error is None
        assert result.columns["Q1"].answer == "YES"
        assert len(result.columns["Q1"].citations) == 1

    def test_error_result(self) -> None:
        result = SearchSubjectResult(
            subject_name="Globex",
            group="GroupA",
            error="API error",
        )
        assert result.error == "API error"
        assert result.columns == {}

    def test_citation_defaults(self) -> None:
        cit = SearchCitation()
        assert cit.file_path == ""
        assert cit.page == ""
        assert cit.section_ref == ""
        assert cit.exact_quote == ""


class TestConfidenceValidator:
    """Tests for the Pydantic confidence normalization validator (Issue #4 Phase A).

    Confidence values are normalized to lowercase to match the Confidence enum
    in dd_agents.models.enums (high/medium/low).
    """

    def test_mixed_case_normalized(self) -> None:
        """Mixed-case confidence is normalized to lowercase on construction."""
        result = SearchColumnResult(answer="YES", confidence="High")
        assert result.confidence == "high"

    def test_lowercase_unchanged(self) -> None:
        result = SearchColumnResult(answer="NO", confidence="low")
        assert result.confidence == "low"

    def test_uppercase_normalized(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="HIGH")
        assert result.confidence == "high"

    def test_empty_string_preserved(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="")
        assert result.confidence == ""

    def test_whitespace_stripped(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="  Medium  ")
        assert result.confidence == "medium"

    def test_default_empty(self) -> None:
        result = SearchColumnResult(answer="YES")
        assert result.confidence == ""


class TestParseCitations:
    """Tests for the parse_citations helper (Issue #4 Phase B)."""

    def test_valid_citations(self) -> None:
        from dd_agents.models.search import parse_citations

        raw = [
            {"file_path": "msa.pdf", "page": "5", "section_ref": "Section 12", "exact_quote": "consent required"},
            {"file_path": "sow.pdf", "page": "1", "section_ref": "", "exact_quote": ""},
        ]
        result = parse_citations(raw)
        assert len(result) == 2
        assert result[0].file_path == "msa.pdf"
        assert result[0].page == "5"

    def test_int_page_coerced(self) -> None:
        from dd_agents.models.search import parse_citations

        raw = [{"file_path": "doc.pdf", "page": 7}]
        result = parse_citations(raw)
        assert result[0].page == "7"

    def test_none_page_coerced(self) -> None:
        from dd_agents.models.search import parse_citations

        raw = [{"file_path": "doc.pdf", "page": None}]
        result = parse_citations(raw)
        assert result[0].page == ""

    def test_non_dict_entries_skipped(self) -> None:
        from dd_agents.models.search import parse_citations

        raw = [{"file_path": "doc.pdf"}, "not a dict", 42, None]
        result = parse_citations(raw)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        from dd_agents.models.search import parse_citations

        assert parse_citations([]) == []


class TestParseColumnResult:
    """Tests for the parse_column_result helper (Issue #4 Phase B)."""

    def test_full_column(self) -> None:
        from dd_agents.models.search import parse_column_result

        data = {
            "answer": "YES",
            "confidence": "high",
            "citations": [
                {"file_path": "msa.pdf", "page": "3", "section_ref": "Section 5", "exact_quote": "consent text"}
            ],
        }
        result = parse_column_result(data)
        assert result.answer == "YES"
        assert result.confidence == "high"  # Normalized
        assert len(result.citations) == 1
        assert result.citations[0].file_path == "msa.pdf"

    def test_missing_fields_default(self) -> None:
        from dd_agents.models.search import parse_column_result

        data = {}
        result = parse_column_result(data)
        assert result.answer == ""
        assert result.confidence == ""
        assert result.citations == []

    def test_confidence_normalization(self) -> None:
        from dd_agents.models.search import parse_column_result

        data = {"answer": "NO", "confidence": "  Medium  "}
        result = parse_column_result(data)
        assert result.confidence == "medium"

    def test_none_confidence(self) -> None:
        from dd_agents.models.search import parse_column_result

        data = {"answer": "YES", "confidence": None}
        result = parse_column_result(data)
        assert result.confidence == ""


class TestCitationVerificationFields:
    """Tests for the new verification fields on SearchCitation (Issue #5)."""

    def test_defaults(self) -> None:
        cit = SearchCitation()
        assert cit.quote_verified is None
        assert cit.quote_match_score == 0.0
        assert cit.section_verified is None

    def test_verified_citation(self) -> None:
        cit = SearchCitation(
            file_path="msa.pdf",
            quote_verified=True,
            quote_match_score=95.5,
            section_verified=True,
        )
        assert cit.quote_verified is True
        assert cit.quote_match_score == 95.5
        assert cit.section_verified is True

    def test_failed_citation(self) -> None:
        cit = SearchCitation(
            file_path="msa.pdf",
            quote_verified=False,
            quote_match_score=30.0,
            section_verified=False,
        )
        assert cit.quote_verified is False
        assert cit.quote_match_score == 30.0
