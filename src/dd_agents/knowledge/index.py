"""Auto-maintained index for LLM and human navigation of the knowledge base (Issue #178).

The index is rebuilt after every write to maintain consistency. LLMs read
the index first to find relevant articles, then drill into them — avoiding
the need for embedding-based RAG at moderate scale.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle

logger = logging.getLogger(__name__)


class IndexEntry(BaseModel):
    """A single entry in the knowledge index."""

    id: str = Field(description="Article ID")
    article_type: ArticleType = Field(description="Article type")
    title: str = Field(description="Article title")
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    updated_at: str = Field(default="", description="Last update timestamp")
    source_count: int = Field(default=0, description="Number of backing sources")
    link_count: int = Field(default=0, description="Number of linked articles")


class KnowledgeIndex(BaseModel):
    """Navigable catalog of all knowledge articles.

    Organized by article type for efficient LLM scanning. The index is
    compact — one line per article with title, tags, and counts.
    """

    total_articles: int = Field(default=0, description="Total articles in the knowledge base")
    by_type: dict[str, list[IndexEntry]] = Field(
        default_factory=dict,
        description="Articles grouped by type",
    )
    entity_count: int = Field(default=0, description="Number of entity profiles")
    last_updated: str = Field(default="", description="ISO-8601 when index was last rebuilt")
    stats: dict[str, Any] = Field(default_factory=dict, description="Aggregate statistics")

    @classmethod
    def build(cls, articles: list[KnowledgeArticle], timestamp: str) -> KnowledgeIndex:
        """Build an index from a list of articles.

        Parameters
        ----------
        articles:
            All articles currently in the knowledge base.
        timestamp:
            ISO-8601 timestamp for the index rebuild.
        """
        by_type: dict[str, list[IndexEntry]] = {}
        entity_count = 0

        for article in articles:
            entry = IndexEntry(
                id=article.id,
                article_type=article.article_type,
                title=article.title,
                tags=article.tags,
                updated_at=article.updated_at,
                source_count=len(article.sources),
                link_count=len(article.links),
            )
            type_key = article.article_type.value
            if type_key not in by_type:
                by_type[type_key] = []
            by_type[type_key].append(entry)

            if article.article_type == ArticleType.ENTITY_PROFILE:
                entity_count += 1

        return cls(
            total_articles=len(articles),
            by_type=by_type,
            entity_count=entity_count,
            last_updated=timestamp,
            stats={
                "by_type_counts": {k: len(v) for k, v in by_type.items()},
                "total_sources": sum(len(a.sources) for a in articles),
                "total_links": sum(len(a.links) for a in articles),
            },
        )

    def generate_summary(self, max_chars: int = 5000) -> str:
        """Generate an LLM-readable summary of the knowledge base.

        Parameters
        ----------
        max_chars:
            Maximum character budget for the summary.
        """
        lines: list[str] = [
            f"Knowledge Base: {self.total_articles} articles, {self.entity_count} entity profiles",
            "",
        ]

        for type_key, entries in self.by_type.items():
            lines.append(f"## {type_key} ({len(entries)} articles)")
            for entry in entries[:20]:  # Cap per section
                tag_str = f" [{', '.join(entry.tags[:3])}]" if entry.tags else ""
                lines.append(f"- {entry.title}{tag_str}")
            if len(entries) > 20:
                lines.append(f"  ... and {len(entries) - 20} more")
            lines.append("")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3] + "..."
        return text
