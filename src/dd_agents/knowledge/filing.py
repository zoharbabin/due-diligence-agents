"""File search, query, and annotation results back into the knowledge base (Issue #182).

Persists search results, ad-hoc query answers, and user annotations as
:class:`KnowledgeArticle` entries so that knowledge compounds across runs.
Every filed article is deduplicated by deterministic ID and carries full
provenance via :class:`KnowledgeSource` citations.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle, KnowledgeSource
from dd_agents.utils.naming import subject_safe_name as _to_safe_name

if TYPE_CHECKING:
    from dd_agents.knowledge.base import DealKnowledgeBase


def _sha256_hex(text: str) -> str:
    """Return the first 16 hex chars of the SHA-256 digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _make_sources(
    raw_citations: list[dict[str, Any]],
    timestamp: str,
) -> list[KnowledgeSource]:
    """Convert raw citation dicts to KnowledgeSource, filtering unverified ones.

    A citation is included when ``quote_verified`` is ``True`` or ``None``
    (not explicitly failed). Citations where ``quote_verified is False`` are
    excluded.
    """
    sources: list[KnowledgeSource] = []
    for cit in raw_citations:
        if cit.get("quote_verified") is False:
            continue
        sources.append(
            KnowledgeSource(
                source_path=cit.get("file_path", ""),
                page=str(cit.get("page", "")),
                section_ref=cit.get("section_ref", ""),
                exact_quote=cit.get("exact_quote", ""),
                timestamp=timestamp,
            )
        )
    return sources


def file_search_results(
    knowledge_base: DealKnowledgeBase,
    results: list[dict[str, Any]],
    prompts_name: str,
    timestamp: str,
) -> int:
    """File search results as insight articles. Returns count of articles created.

    For each subject result, for each column with an answer != ``"NOT_ADDRESSED"``,
    creates or updates a :class:`KnowledgeArticle` of type
    :attr:`ArticleType.INSIGHT`.

    Parameters
    ----------
    knowledge_base:
        The deal knowledge base to write into.
    results:
        List of dicts matching :class:`SearchSubjectResult` schema.
    prompts_name:
        Name of the search prompts configuration that produced these results.
    timestamp:
        ISO-8601 timestamp for provenance.

    Returns
    -------
    int
        Number of articles created or updated.
    """
    count = 0
    for subject_result in results:
        subject_name: str = subject_result.get("subject_name", "")
        try:
            entity_safe = _to_safe_name(subject_name)
        except ValueError:
            entity_safe = subject_name.strip().lower().replace(" ", "_")
        columns: dict[str, Any] = subject_result.get("columns", {})

        for col_name, col_data in columns.items():
            if not isinstance(col_data, dict):
                continue
            answer: str = col_data.get("answer", "")
            if answer == "NOT_ADDRESSED":
                continue

            col_safe = col_name.strip().lower().replace(" ", "_")
            content_hash = _sha256_hex(f"{entity_safe}:{col_safe}")
            article_id = f"insight_search_{entity_safe}_{col_safe}_{content_hash}"

            raw_citations: list[dict[str, Any]] = col_data.get("citations", [])
            sources = _make_sources(raw_citations, timestamp)

            existing = knowledge_base.get_article(article_id)
            if existing is not None:
                knowledge_base.update_article(
                    article_id,
                    {
                        "content": {
                            "answer": answer,
                            "confidence": col_data.get("confidence", ""),
                            "prompts_name": prompts_name,
                            "column": col_name,
                            "entity": subject_name,
                        },
                        "sources": [s.model_dump(mode="json") for s in sources],
                        "updated_by": f"search:{timestamp}",
                    },
                )
            else:
                article = KnowledgeArticle(
                    id=article_id,
                    article_type=ArticleType.INSIGHT,
                    title=f"{subject_name} — {col_name}",
                    content={
                        "answer": answer,
                        "confidence": col_data.get("confidence", ""),
                        "prompts_name": prompts_name,
                        "column": col_name,
                        "entity": subject_name,
                    },
                    sources=sources,
                    tags=[entity_safe, col_safe, "search"],
                    created_by=f"search:{timestamp}",
                    updated_by=f"search:{timestamp}",
                )
                knowledge_base.write_article(article)

            count += 1

    return count


def file_query_result(
    knowledge_base: DealKnowledgeBase,
    question: str,
    answer: str,
    confidence: str,
    sources: list[dict[str, Any]],
    timestamp: str,
) -> str | None:
    """File a query answer as an insight article.

    Returns the article ID, or ``None`` if the result was skipped
    (low confidence answers are not worth persisting).

    Parameters
    ----------
    knowledge_base:
        The deal knowledge base to write into.
    question:
        The user's question.
    answer:
        The answer text.
    confidence:
        Confidence level (``"high"``, ``"medium"``, ``"low"``).
    sources:
        List of citation dicts with file_path, page, section_ref, exact_quote, etc.
    timestamp:
        ISO-8601 timestamp for provenance.
    """
    if confidence.strip().lower() == "low":
        return None

    q_hash = _sha256_hex(question.strip())
    article_id = f"insight_query_{q_hash}"

    knowledge_sources = _make_sources(sources, timestamp)

    existing = knowledge_base.get_article(article_id)
    if existing is not None:
        knowledge_base.update_article(
            article_id,
            {
                "content": {
                    "question": question,
                    "answer": answer,
                    "confidence": confidence,
                },
                "sources": [s.model_dump(mode="json") for s in knowledge_sources],
                "updated_by": f"query:{timestamp}",
            },
        )
        return article_id

    article = KnowledgeArticle(
        id=article_id,
        article_type=ArticleType.INSIGHT,
        title=f"Query: {question[:150]}",
        content={
            "question": question,
            "answer": answer,
            "confidence": confidence,
        },
        sources=knowledge_sources,
        tags=["query"],
        created_by=f"query:{timestamp}",
        updated_by=f"query:{timestamp}",
    )
    knowledge_base.write_article(article)
    return article_id


def file_annotation(
    knowledge_base: DealKnowledgeBase,
    note: str,
    entity_safe_name: str | None,
    timestamp: str,
) -> str:
    """File a user annotation. Returns the article ID.

    Annotations are always filed (no dedup) since each represents a unique
    user observation.

    Parameters
    ----------
    knowledge_base:
        The deal knowledge base to write into.
    note:
        Free-text annotation body.
    entity_safe_name:
        Optional entity to link this annotation to. If provided, the annotation
        is tagged with the entity name and linked to the entity profile article.
    timestamp:
        ISO-8601 timestamp for provenance.
    """
    uid = uuid.uuid4().hex[:12]
    article_id = f"annotation_{uid}"

    tags: list[str] = ["annotation"]
    links: list[str] = []
    if entity_safe_name:
        tags.append(entity_safe_name)
        # Attempt to link to the entity profile article
        entity_article = knowledge_base.get_article(f"entity_{entity_safe_name}")
        if entity_article is not None:
            links.append(entity_article.id)

    article = KnowledgeArticle(
        id=article_id,
        article_type=ArticleType.ANNOTATION,
        title=f"Annotation: {note[:100]}",
        content={"note": note},
        sources=[],
        tags=tags,
        links=links,
        created_by="user",
        updated_by="user",
    )
    knowledge_base.write_article(article)
    return article_id
