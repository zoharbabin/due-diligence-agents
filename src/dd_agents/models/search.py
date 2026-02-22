"""Pydantic models for the ``dd-agents search`` command.

Defines the prompts file schema, per-customer results, and citation records.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class SearchColumnResult(BaseModel):
    """Result for one column (question) for one customer."""

    answer: str = ""
    citations: list[SearchCitation] = Field(default_factory=list)
    confidence: str = ""


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
