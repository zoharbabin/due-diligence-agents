"""Unit tests for knowledge compounding — file-back functions (Issue #182)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle
from dd_agents.knowledge.base import DealKnowledgeBase

if TYPE_CHECKING:
    from pathlib import Path
from dd_agents.knowledge.filing import (
    file_annotation,
    file_query_result,
    file_search_results,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-04-05T12:00:00+00:00"


@pytest.fixture()
def kb(tmp_path: Path) -> DealKnowledgeBase:
    """Return an initialized DealKnowledgeBase."""
    dkb = DealKnowledgeBase(tmp_path)
    dkb.ensure_dirs()
    return dkb


def _make_search_results(
    customer_name: str = "Customer A",
    columns: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Build a minimal search results list matching SearchCustomerResult schema."""
    if columns is None:
        columns = {
            "Revenue Growth": {
                "answer": "YES",
                "confidence": "high",
                "citations": [
                    {
                        "file_path": "financials/q1.pdf",
                        "page": "3",
                        "section_ref": "Section 2",
                        "exact_quote": "Revenue grew 15%",
                        "quote_verified": True,
                    },
                ],
            },
        }
    return [{"customer_name": customer_name, "columns": columns}]


# ---------------------------------------------------------------------------
# file_search_results tests
# ---------------------------------------------------------------------------


class TestFileSearchResults:
    """Tests for file_search_results."""

    def test_creates_articles_from_results(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results()
        count = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count == 1
        articles = kb.list_articles(ArticleType.INSIGHT)
        assert len(articles) == 1
        assert articles[0].content["answer"] == "YES"
        assert articles[0].content["entity"] == "Customer A"

    def test_skips_not_addressed_answers(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results(
            columns={
                "Revenue Growth": {
                    "answer": "NOT_ADDRESSED",
                    "confidence": "low",
                    "citations": [],
                },
                "IP Risk": {
                    "answer": "YES",
                    "confidence": "high",
                    "citations": [],
                },
            },
        )
        count = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count == 1
        articles = kb.list_articles(ArticleType.INSIGHT)
        assert len(articles) == 1
        assert articles[0].content["column"] == "IP Risk"

    def test_excludes_unverified_citations(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results(
            columns={
                "Compliance": {
                    "answer": "YES",
                    "confidence": "high",
                    "citations": [
                        {
                            "file_path": "a.pdf",
                            "page": "1",
                            "exact_quote": "Good quote",
                            "quote_verified": True,
                        },
                        {
                            "file_path": "b.pdf",
                            "page": "2",
                            "exact_quote": "Bad quote",
                            "quote_verified": False,
                        },
                        {
                            "file_path": "c.pdf",
                            "page": "3",
                            "exact_quote": "Unknown quote",
                            "quote_verified": None,
                        },
                    ],
                },
            },
        )
        count = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count == 1
        article = kb.list_articles(ArticleType.INSIGHT)[0]
        # Only verified (True) and unknown (None) citations are kept
        assert len(article.sources) == 2
        paths = {s.source_path for s in article.sources}
        assert paths == {"a.pdf", "c.pdf"}

    def test_deduplicates_updates_existing(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results()
        count1 = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count1 == 1

        # File again — should update, not create new
        updated_results = _make_search_results(
            columns={
                "Revenue Growth": {
                    "answer": "NO",
                    "confidence": "medium",
                    "citations": [],
                },
            },
        )
        count2 = file_search_results(kb, updated_results, "test_prompts_v2", TIMESTAMP)
        assert count2 == 1

        articles = kb.list_articles(ArticleType.INSIGHT)
        assert len(articles) == 1
        assert articles[0].content["answer"] == "NO"
        assert articles[0].version == 2

    def test_returns_correct_count(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results(
            columns={
                "Revenue Growth": {"answer": "YES", "confidence": "high", "citations": []},
                "Employee Churn": {"answer": "NO", "confidence": "medium", "citations": []},
                "Skipped Col": {"answer": "NOT_ADDRESSED", "confidence": "low", "citations": []},
            },
        )
        count = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count == 2

    def test_empty_results_returns_zero(self, kb: DealKnowledgeBase) -> None:
        count = file_search_results(kb, [], "test_prompts", TIMESTAMP)
        assert count == 0

    def test_multiple_customers(self, kb: DealKnowledgeBase) -> None:
        results = [
            *_make_search_results(customer_name="Customer A"),
            *_make_search_results(customer_name="Customer B"),
        ]
        count = file_search_results(kb, results, "test_prompts", TIMESTAMP)
        assert count == 2
        articles = kb.list_articles(ArticleType.INSIGHT)
        assert len(articles) == 2

    def test_tags_include_entity_column_search(self, kb: DealKnowledgeBase) -> None:
        results = _make_search_results()
        file_search_results(kb, results, "test_prompts", TIMESTAMP)
        article = kb.list_articles(ArticleType.INSIGHT)[0]
        assert "customer_a" in article.tags
        assert "revenue_growth" in article.tags
        assert "search" in article.tags


# ---------------------------------------------------------------------------
# file_query_result tests
# ---------------------------------------------------------------------------


class TestFileQueryResult:
    """Tests for file_query_result."""

    def test_creates_insight_for_high_confidence(self, kb: DealKnowledgeBase) -> None:
        sources = [
            {
                "file_path": "contracts/msa.pdf",
                "page": "5",
                "section_ref": "Section 4",
                "exact_quote": "The agreement...",
                "quote_verified": True,
            },
        ]
        article_id = file_query_result(kb, "What is the term?", "3 years", "high", sources, TIMESTAMP)
        assert article_id is not None
        article = kb.get_article(article_id)
        assert article is not None
        assert article.article_type == ArticleType.INSIGHT
        assert article.content["answer"] == "3 years"
        assert article.content["question"] == "What is the term?"
        assert len(article.sources) == 1

    def test_skips_low_confidence(self, kb: DealKnowledgeBase) -> None:
        article_id = file_query_result(kb, "Uncertain question?", "Maybe", "low", [], TIMESTAMP)
        assert article_id is None
        assert len(kb.list_articles(ArticleType.INSIGHT)) == 0

    def test_deduplicates_same_question(self, kb: DealKnowledgeBase) -> None:
        q = "What is the revenue?"
        file_query_result(kb, q, "10M", "high", [], TIMESTAMP)
        article_id = file_query_result(kb, q, "12M", "high", [], TIMESTAMP)
        assert article_id is not None

        articles = kb.list_articles(ArticleType.INSIGHT)
        assert len(articles) == 1
        assert articles[0].content["answer"] == "12M"
        assert articles[0].version == 2

    def test_medium_confidence_is_filed(self, kb: DealKnowledgeBase) -> None:
        article_id = file_query_result(kb, "Some question?", "Answer", "medium", [], TIMESTAMP)
        assert article_id is not None

    def test_query_tags(self, kb: DealKnowledgeBase) -> None:
        article_id = file_query_result(kb, "Tagged question?", "Answer", "high", [], TIMESTAMP)
        assert article_id is not None
        article = kb.get_article(article_id)
        assert article is not None
        assert "query" in article.tags


# ---------------------------------------------------------------------------
# file_annotation tests
# ---------------------------------------------------------------------------


class TestFileAnnotation:
    """Tests for file_annotation."""

    def test_creates_annotation_article(self, kb: DealKnowledgeBase) -> None:
        article_id = file_annotation(kb, "Important observation about governance.", None, TIMESTAMP)
        assert article_id.startswith("annotation_")
        article = kb.get_article(article_id)
        assert article is not None
        assert article.article_type == ArticleType.ANNOTATION
        assert article.content["note"] == "Important observation about governance."
        assert article.created_by == "user"

    def test_with_entity_links_to_profile(self, kb: DealKnowledgeBase) -> None:
        # Create an entity profile article first

        entity_article = KnowledgeArticle(
            id="entity_acme_corp",
            article_type=ArticleType.ENTITY_PROFILE,
            title="Acme Corp",
            content={"name": "Acme Corp"},
        )
        kb.write_article(entity_article)

        article_id = file_annotation(kb, "Note about Acme Corp", "acme_corp", TIMESTAMP)
        article = kb.get_article(article_id)
        assert article is not None
        assert "acme_corp" in article.tags
        assert "entity_acme_corp" in article.links

    def test_without_entity_creates_standalone(self, kb: DealKnowledgeBase) -> None:
        article_id = file_annotation(kb, "General observation", None, TIMESTAMP)
        article = kb.get_article(article_id)
        assert article is not None
        assert article.links == []
        assert "annotation" in article.tags

    def test_no_dedup_multiple_annotations(self, kb: DealKnowledgeBase) -> None:
        id1 = file_annotation(kb, "First note", None, TIMESTAMP)
        id2 = file_annotation(kb, "First note", None, TIMESTAMP)
        assert id1 != id2
        assert len(kb.list_articles(ArticleType.ANNOTATION)) == 2
