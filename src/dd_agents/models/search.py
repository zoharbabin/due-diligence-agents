"""Pydantic models for the ``dd-agents search`` command.

Defines the prompts file schema, per-subject results, and citation records.
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

    name: str = Field(..., min_length=1, max_length=200, description="Name of the search prompts configuration")
    description: str = Field(default="", description="Human-readable description of the search purpose")
    columns: list[SearchColumn] = Field(
        ..., min_length=1, max_length=20, description="Question columns (1-20) to evaluate per subject"
    )


class SearchCitation(BaseModel):
    """A single citation backing an answer."""

    file_path: str = Field(default="", description="Source file path for this citation")
    page: str = Field(default="", description="Page number or range where the citation appears")
    section_ref: str = Field(default="", description="Section reference within the document")
    exact_quote: str = Field(default="", description="Exact quoted text from the source")
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
    """Result for one column (question) for one subject."""

    answer: str = Field(default="", description="Answer text (YES/NO/NOT_ADDRESSED or free-form)")
    citations: list[SearchCitation] = Field(default_factory=list, description="Citations backing this answer")
    confidence: str = Field(default="", description="Confidence level: high, medium, or low")

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, v: Any) -> str:
        """Normalize confidence to lowercase (high/medium/low).

        Matches the Confidence enum in dd_agents.models.enums which uses
        lowercase values.  Centralizes the normalization that was previously
        scattered across 4 locations in the analyzer (parse, merge,
        synthesis, validation).
        """
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
        return ""


class SearchSubjectResult(BaseModel):
    """Aggregated search results for one subject."""

    subject_name: str = Field(description="Subject display name")
    group: str = Field(default="", description="Group folder this subject belongs to")
    files_analyzed: int = Field(default=0, description="Number of files analyzed for this subject")
    total_files: int = Field(default=0, description="Total files available for this subject")
    skipped_files: list[str] = Field(default_factory=list, description="File paths that were skipped")
    columns: dict[str, SearchColumnResult] = Field(default_factory=dict, description="Results keyed by column name")
    incomplete_columns: list[str] = Field(
        default_factory=list, description="Column names where analysis was incomplete"
    )
    error: str | None = Field(default=None, description="Error message if analysis failed for this subject")
    chunks_analyzed: int = Field(default=0, description="Number of text chunks processed")


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


# Prefixes that are semantically equivalent to NOT_ADDRESSED.  Issue #24.
_NOT_ADDRESSED_PREFIXES = (
    "UNABLE TO DETERMINE",
    "CANNOT DETERMINE",
    "CANNOT BE DETERMINED",
    "UNABLE TO ASSESS",
    "INSUFFICIENT INFORMATION",
    "NOT ENOUGH INFORMATION",
    "COULD NOT DETERMINE",
    "COULD NOT BE DETERMINED",
    "NOT DETERMINABLE",
    "INDETERMINATE",
)


def _normalize_answer(answer: str) -> str:
    """Normalize non-standard LLM answer values to YES/NO/NOT_ADDRESSED.

    LLMs sometimes return free-text like "Unable to determine..." or
    "Cannot determine..." instead of conforming to the requested format.
    These are semantically equivalent to NOT_ADDRESSED and should be
    normalized for consistent downstream filtering/coloring.  Issue #24.
    """
    if not answer:
        return answer
    upper = answer.strip().upper()
    # Already standard — return as-is (preserving original casing for
    # free-text answers that happen to start with YES/NO).
    if upper in ("YES", "NO", "NOT_ADDRESSED"):
        return answer.strip()
    for prefix in _NOT_ADDRESSED_PREFIXES:
        if upper.startswith(prefix):
            return "NOT_ADDRESSED"
    return answer.strip()


def dedup_citations(citations: list[SearchCitation]) -> list[SearchCitation]:
    """Deduplicate citations by (file_path, page, section_ref, exact_quote).

    Applied at parse time so both single-chunk and multi-chunk subjects
    get consistent dedup.  The same 4-tuple key is used in the merge phase
    for cross-chunk dedup.  Issue #24.
    """
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[SearchCitation] = []
    for cit in citations:
        key = (
            (cit.file_path or "").strip(),
            (cit.page or "").strip(),
            (cit.section_ref or "").strip(),
            (cit.exact_quote or "").strip(),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(cit)
    return deduped


def parse_column_result(col_data: dict[str, Any]) -> SearchColumnResult:
    """Parse a single column dict from an LLM JSON response.

    Handles type coercion for ``confidence`` (via Pydantic validator),
    answer normalization (Issue #24), parse-time citation dedup (Issue #24),
    and delegates citation parsing to :func:`parse_citations`.
    """
    return SearchColumnResult(
        answer=_normalize_answer(col_data.get("answer", "")),
        confidence=col_data.get("confidence") or "",
        citations=dedup_citations(parse_citations(col_data.get("citations", []))),
    )
