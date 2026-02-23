"""Unit tests for search Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dd_agents.models.search import (
    SearchCitation,
    SearchColumn,
    SearchColumnResult,
    SearchCustomerResult,
    SearchPrompts,
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
        result = SearchCustomerResult(
            customer_name="Acme Corp",
            group="GroupA",
            files_analyzed=3,
            columns={
                "Q1": SearchColumnResult(
                    answer="YES",
                    confidence="HIGH",
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
        result = SearchCustomerResult(
            customer_name="Globex",
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
    """Tests for the Pydantic confidence normalization validator (Issue #4 Phase A)."""

    def test_mixed_case_normalized(self) -> None:
        """Mixed-case confidence is normalized to uppercase on construction."""
        result = SearchColumnResult(answer="YES", confidence="High")
        assert result.confidence == "HIGH"

    def test_lowercase_normalized(self) -> None:
        result = SearchColumnResult(answer="NO", confidence="low")
        assert result.confidence == "LOW"

    def test_uppercase_unchanged(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="HIGH")
        assert result.confidence == "HIGH"

    def test_empty_string_preserved(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="")
        assert result.confidence == ""

    def test_whitespace_stripped(self) -> None:
        result = SearchColumnResult(answer="YES", confidence="  Medium  ")
        assert result.confidence == "MEDIUM"

    def test_default_empty(self) -> None:
        result = SearchColumnResult(answer="YES")
        assert result.confidence == ""
