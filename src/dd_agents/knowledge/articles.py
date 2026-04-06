"""Pydantic models for knowledge articles and provenance sources (Issue #178).

Every article in the Deal Knowledge Base traces back to source documents
via :class:`KnowledgeSource`. This is M&A due diligence — every claim
must be cited to a specific document, page, and section.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArticleType(StrEnum):
    """Type of knowledge article stored in the Deal Knowledge Base."""

    ENTITY_PROFILE = "entity_profile"
    CLAUSE_SUMMARY = "clause_summary"
    CONTRADICTION = "contradiction"
    INSIGHT = "insight"
    ANNOTATION = "annotation"


class KnowledgeSource(BaseModel):
    """Provenance link back to a raw source document.

    Every claim in a knowledge article must be sourced. In M&A diligence,
    unsourced knowledge is worthless — advisors need to verify claims
    against the original documents.
    """

    source_path: str = Field(description="Relative path to the document in the data room")
    page: str = Field(default="", description="Page number or range (e.g. '5' or '3-7')")
    section_ref: str = Field(default="", description="Section reference (e.g. 'Section 4.3')")
    exact_quote: str = Field(default="", description="Verbatim text from the source document")
    run_id: str = Field(default="", description="Pipeline run that produced this source")
    timestamp: str = Field(default="", description="ISO-8601 when the source was accessed")


class KnowledgeArticle(BaseModel):
    """A single article in the Deal Knowledge Base.

    Articles are typed by :attr:`article_type` and linked to other articles
    via :attr:`links` (bidirectional IDs). All content is backed by
    :attr:`sources` tracing to raw data room documents.
    """

    id: str = Field(description="Unique article ID (deterministic hash or UUID prefix)")
    article_type: ArticleType = Field(description="Article type for categorization")
    title: str = Field(max_length=200, description="Human-readable title (max 200 chars)")
    content: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured content (schema varies by article_type)",
    )
    sources: list[KnowledgeSource] = Field(
        default_factory=list,
        description="Provenance chain — every claim must be sourced",
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    links: list[str] = Field(
        default_factory=list,
        description="IDs of related articles (bidirectional backlinks)",
    )
    created_at: str = Field(default="", description="ISO-8601 creation timestamp")
    updated_at: str = Field(default="", description="ISO-8601 last update timestamp")
    created_by: str = Field(
        default="",
        description="Origin: 'pipeline:{run_id}', 'search:{ts}', 'query:{ts}', or 'user'",
    )
    updated_by: str = Field(default="", description="Who last updated this article")
    version: int = Field(default=1, ge=1, description="Monotonic version, incremented on update")
    superseded_by: str | None = Field(
        default=None,
        description="ID of the article that replaces this one (soft delete)",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extensible metadata")
