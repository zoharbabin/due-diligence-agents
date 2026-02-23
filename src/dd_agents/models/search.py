"""Pydantic models for the ``dd-agents search`` command.

Defines the prompts file schema, per-customer results, and citation records.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class SearchColumn(BaseModel):
    """A single question column in the search prompts file."""

    name: str = Field(..., min_length=1, max_length=100, description="Free-form display name for the column header")
    prompt: str = Field(..., min_length=10, max_length=2000, description="Natural-language prompt sent to Claude")


class SearchPrompts(BaseModel, extra="forbid"):
    """Top-level prompts file schema.

    ``extra="forbid"`` catches typos in the JSON keys.
    """

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    columns: list[SearchColumn] = Field(..., min_length=1, max_length=20)


class SearchCitation(BaseModel):
    """A single citation backing an answer."""

    file_path: str = ""
    page: str = ""
    section_ref: str = ""
    exact_quote: str = ""
    # Citation verification fields (Issue #5).
    quote_verified: bool | None = Field(default=None, description="Whether exact_quote was found in source text")
    quote_match_score: float = Field(default=0.0, description="Fuzzy match score 0-100 from rapidfuzz")
    section_verified: bool | None = Field(default=None, description="Whether section_ref was found in source text")

    @field_validator("page", mode="before")
    @classmethod
    def _coerce_page(cls, v: Any) -> str:
        """Coerce page to string — LLMs sometimes return int or None."""
        if v is None:
            return ""
        return str(v)


class SearchColumnResult(BaseModel):
    """Result for one column (question) for one customer."""

    answer: str = ""
    citations: list[SearchCitation] = Field(default_factory=list)
    confidence: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, v: Any) -> str:
        """Normalize confidence to uppercase (HIGH/MEDIUM/LOW).

        Centralizes the normalization that was previously scattered across
        4 locations in the analyzer (parse, merge, synthesis, validation).
        """
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
        return ""


class SearchCustomerResult(BaseModel):
    """Aggregated search results for one customer."""

    customer_name: str
    group: str = ""
    files_analyzed: int = 0
    total_files: int = 0
    skipped_files: list[str] = Field(default_factory=list)
    columns: dict[str, SearchColumnResult] = Field(default_factory=dict)
    incomplete_columns: list[str] = Field(default_factory=list)
    error: str | None = None
    chunks_analyzed: int = 0


# ---------------------------------------------------------------------------
# LLM response parsing helpers (Issue #4 Phase B)
# ---------------------------------------------------------------------------


def parse_citations(raw_list: list[Any]) -> list[SearchCitation]:
    """Parse citation dicts from an LLM JSON response into validated models.

    Malformed entries are silently skipped to avoid failing the entire
    response on a single bad citation.  Type coercion (e.g. ``page``
    as int → str) is handled by the Pydantic field validators on
    :class:`SearchCitation`.
    """
    citations: list[SearchCitation] = []
    for cit in raw_list:
        if isinstance(cit, dict):
            try:
                citations.append(SearchCitation.model_validate(cit))
            except Exception:
                logger.debug("Skipping malformed citation: %s", cit)
    return citations


def parse_column_result(col_data: dict[str, Any]) -> SearchColumnResult:
    """Parse a single column dict from an LLM JSON response.

    Handles type coercion for ``confidence`` (via Pydantic validator)
    and delegates citation parsing to :func:`parse_citations`.
    """
    return SearchColumnResult(
        answer=col_data.get("answer", ""),
        confidence=col_data.get("confidence") or "",
        citations=parse_citations(col_data.get("citations", [])),
    )
