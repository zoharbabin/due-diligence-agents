"""Tests for KnowledgeContextBuilder (Issue #181)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle
from dd_agents.knowledge.search_context import KnowledgeContextBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    article_id: str,
    article_type: ArticleType,
    title: str,
    content: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    superseded_by: str | None = None,
) -> KnowledgeArticle:
    """Factory for test articles."""
    return KnowledgeArticle(
        id=article_id,
        article_type=article_type,
        title=title,
        content=content or {},
        tags=tags or [],
        superseded_by=superseded_by,
    )


def _mock_kb(
    articles_by_id: dict[str, KnowledgeArticle] | None = None,
    articles_by_type: dict[ArticleType, list[KnowledgeArticle]] | None = None,
    search_results: list[KnowledgeArticle] | None = None,
) -> MagicMock:
    """Build a mock DealKnowledgeBase."""
    kb = MagicMock()
    articles_by_id = articles_by_id or {}
    articles_by_type = articles_by_type or {}

    def get_article(article_id: str) -> KnowledgeArticle | None:
        return articles_by_id.get(article_id)

    def list_articles(article_type: ArticleType | None = None) -> list[KnowledgeArticle]:
        if article_type is not None:
            return articles_by_type.get(article_type, [])
        result: list[KnowledgeArticle] = []
        for arts in articles_by_type.values():
            result.extend(arts)
        return result

    def search_articles(query: str, limit: int = 10, article_type: ArticleType | None = None) -> list[KnowledgeArticle]:
        return search_results or []

    kb.get_article = MagicMock(side_effect=get_article)
    kb.list_articles = MagicMock(side_effect=list_articles)
    kb.search_articles = MagicMock(side_effect=search_articles)
    return kb


# ---------------------------------------------------------------------------
# Tests: no knowledge base
# ---------------------------------------------------------------------------


class TestNoKnowledgeBase:
    """Tests when no knowledge base is provided."""

    def test_returns_none_when_no_kb(self) -> None:
        builder = KnowledgeContextBuilder(knowledge_base=None)
        result = builder.build_context("acme", ["revenue"])
        assert result is None

    def test_returns_none_with_graph_but_no_kb(self) -> None:
        graph = MagicMock()
        builder = KnowledgeContextBuilder(knowledge_base=None, knowledge_graph=graph)
        result = builder.build_context("acme", ["revenue"])
        assert result is None


# ---------------------------------------------------------------------------
# Tests: no data for entity
# ---------------------------------------------------------------------------


class TestNoDataForEntity:
    """Tests when KB exists but has no data for the requested entity."""

    def test_returns_none_when_no_articles_for_entity(self) -> None:
        kb = _mock_kb()
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["revenue"])
        assert result is None

    def test_returns_none_when_only_other_entity_data(self) -> None:
        profile = _make_article(
            "entity_other_co",
            ArticleType.ENTITY_PROFILE,
            "Other Co Profile",
            content={"summary": "Some data about other company"},
            tags=["other_co"],
        )
        kb = _mock_kb(articles_by_id={"entity_other_co": profile})
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["revenue"])
        assert result is None


# ---------------------------------------------------------------------------
# Tests: entity profile
# ---------------------------------------------------------------------------


class TestEntityProfile:
    """Tests for entity profile section."""

    def test_includes_entity_profile_when_exists(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme Corp Profile",
            content={
                "severity_distribution": {"P0": 2, "P1": 5, "P2": 10},
                "summary": "Acme is a mid-market SaaS company with significant contract risk.",
            },
            tags=["acme"],
        )
        kb = _mock_kb(articles_by_id={"entity_acme": profile})
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [])
        assert result is not None
        assert "Entity Profile" in result
        assert "Acme Corp Profile" in result
        assert "P0: 2" in result
        assert "mid-market SaaS" in result

    def test_profile_with_key_clauses(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme Corp Profile",
            content={
                "key_clauses": [
                    "Non-compete clause with two-year restriction",
                    "Change of control provision requiring board approval",
                ],
                "summary": "Entity has several restrictive covenants",
            },
            tags=["acme"],
        )
        kb = _mock_kb(articles_by_id={"entity_acme": profile})
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [])
        assert result is not None
        assert "Non-compete clause" in result
        assert "Change of control" in result


# ---------------------------------------------------------------------------
# Tests: clause summaries
# ---------------------------------------------------------------------------


class TestClauseSummaries:
    """Tests for clause summary section matched to column names."""

    def test_includes_clause_summaries_matched_to_columns(self) -> None:
        clause = _make_article(
            "clause_1",
            ArticleType.CLAUSE_SUMMARY,
            "Revenue Recognition Clause",
            content={
                "summary": "Revenue is recognized upon delivery of goods or services "
                "per ASC 606 standards with multi-element arrangements"
            },
            tags=["acme", "revenue"],
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.CLAUSE_SUMMARY: [clause]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["revenue"])
        assert result is not None
        assert "Relevant Clause Summaries" in result
        assert "Revenue Recognition Clause" in result

    def test_clause_matched_by_title(self) -> None:
        clause = _make_article(
            "clause_2",
            ArticleType.CLAUSE_SUMMARY,
            "Non-Compete Terms",
            content={
                "summary": "Two year non-compete restriction in effect covering "
                "all territories and product lines within the agreed scope"
            },
            tags=["acme"],
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.CLAUSE_SUMMARY: [clause]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["non-compete"])
        assert result is not None
        assert "Non-Compete Terms" in result

    def test_clause_skips_superseded(self) -> None:
        clause = _make_article(
            "clause_old",
            ArticleType.CLAUSE_SUMMARY,
            "Revenue Clause",
            content={"summary": "Old clause"},
            tags=["acme", "revenue"],
            superseded_by="clause_new",
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.CLAUSE_SUMMARY: [clause]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["revenue"])
        # Superseded articles should be skipped, so no clause section
        assert result is None

    def test_clause_no_match_different_entity(self) -> None:
        clause = _make_article(
            "clause_3",
            ArticleType.CLAUSE_SUMMARY,
            "Revenue Clause",
            content={"summary": "Revenue details"},
            tags=["other_co", "revenue"],
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.CLAUSE_SUMMARY: [clause]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", ["revenue"])
        assert result is None


# ---------------------------------------------------------------------------
# Tests: contradictions
# ---------------------------------------------------------------------------


class TestContradictions:
    """Tests for contradictions section."""

    def test_includes_contradictions_for_entity(self) -> None:
        contradiction = _make_article(
            "contra_1",
            ArticleType.CONTRADICTION,
            "Revenue vs Contract Conflict",
            content={
                "description": "Revenue figure in financials conflicts with contract terms. "
                "The annual report states total revenue of twelve million while the master services "
                "agreement caps total fees at eight million for the same period"
            },
            tags=["acme"],
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.CONTRADICTION: [contradiction]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [])
        assert result is not None
        assert "Known Contradictions" in result
        assert "Revenue vs Contract Conflict" in result


# ---------------------------------------------------------------------------
# Tests: graph context
# ---------------------------------------------------------------------------


class TestGraphContext:
    """Tests for graph context section."""

    def test_includes_graph_context_when_available(self) -> None:
        kb = _mock_kb()
        graph = MagicMock()
        graph.get_entity_context.return_value = (
            "Entity: Acme (acme)\n\nRelationships (outgoing):\n"
            "  -> party_to: master_services_agreement.pdf (confidence: 1.00)\n"
            "  -> party_to: amendment_001.pdf (confidence: 0.95)\n"
            "  -> party_to: nda_mutual.pdf (confidence: 1.00)"
        )

        builder = KnowledgeContextBuilder(knowledge_base=kb, knowledge_graph=graph)
        result = builder.build_context("acme", [])
        assert result is not None
        assert "Document Relationships" in result
        assert "party_to" in result

    def test_graph_skipped_when_no_data(self) -> None:
        kb = _mock_kb()
        graph = MagicMock()
        graph.get_entity_context.return_value = "No graph data for entity: acme"

        builder = KnowledgeContextBuilder(knowledge_base=kb, knowledge_graph=graph)
        result = builder.build_context("acme", [])
        assert result is None

    def test_graph_skipped_when_no_graph(self) -> None:
        kb = _mock_kb()
        builder = KnowledgeContextBuilder(knowledge_base=kb, knowledge_graph=None)
        result = builder.build_context("acme", [])
        assert result is None


# ---------------------------------------------------------------------------
# Tests: insights
# ---------------------------------------------------------------------------


class TestInsights:
    """Tests for insights section."""

    def test_includes_insights_for_entity(self) -> None:
        insight = _make_article(
            "insight_1",
            ArticleType.INSIGHT,
            "Revenue Concentration Risk",
            content={
                "summary": "Top 3 subjects represent 80% of revenue creating significant "
                "concentration risk that should be addressed in the purchase agreement warranties"
            },
            tags=["acme"],
        )
        kb = _mock_kb(
            articles_by_type={ArticleType.INSIGHT: [insight]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [])
        assert result is not None
        assert "Prior Search Insights" in result
        assert "Revenue Concentration Risk" in result


# ---------------------------------------------------------------------------
# Tests: budget and ordering
# ---------------------------------------------------------------------------


class TestBudgetAndOrdering:
    """Tests for max_chars budget enforcement and section ordering."""

    def test_respects_max_chars_budget(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme Corp Profile",
            content={"summary": "A" * 5000},
            tags=["acme"],
        )
        kb = _mock_kb(articles_by_id={"entity_acme": profile})
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [], max_chars=500)
        assert result is not None
        assert len(result) <= 500

    def test_returns_none_when_assembled_under_100_chars(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme",
            content={},
            tags=["acme"],
        )
        kb = _mock_kb(articles_by_id={"entity_acme": profile})
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        # Very small max_chars to force short text — but profile header is long enough
        # We need content that produces < 100 chars total
        result = builder.build_context("acme", [], max_chars=50)
        # Even truncated to 50 chars, it's under 100
        if result is not None:
            assert len(result) >= 100

    def test_entity_profile_appears_first(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme Corp Profile",
            content={"summary": "Entity summary text here"},
            tags=["acme"],
        )
        insight = _make_article(
            "insight_1",
            ArticleType.INSIGHT,
            "Some Insight",
            content={"summary": "Insight summary text here"},
            tags=["acme"],
        )
        kb = _mock_kb(
            articles_by_id={"entity_acme": profile},
            articles_by_type={ArticleType.INSIGHT: [insight]},
        )
        builder = KnowledgeContextBuilder(knowledge_base=kb)
        result = builder.build_context("acme", [])
        assert result is not None
        profile_pos = result.index("Entity Profile")
        insight_pos = result.index("Prior Search Insights")
        assert profile_pos < insight_pos

    def test_all_sections_present_when_data_available(self) -> None:
        profile = _make_article(
            "entity_acme",
            ArticleType.ENTITY_PROFILE,
            "Acme Corp Profile",
            content={"summary": "Entity summary for Acme Corp"},
            tags=["acme"],
        )
        clause = _make_article(
            "clause_1",
            ArticleType.CLAUSE_SUMMARY,
            "Revenue Clause",
            content={"summary": "Revenue clause details"},
            tags=["acme", "revenue"],
        )
        contradiction = _make_article(
            "contra_1",
            ArticleType.CONTRADICTION,
            "Contract Conflict",
            content={"description": "Conflict between two contracts"},
            tags=["acme"],
        )
        insight = _make_article(
            "insight_1",
            ArticleType.INSIGHT,
            "Market Insight",
            content={"summary": "Market insight details"},
            tags=["acme"],
        )

        graph = MagicMock()
        graph.get_entity_context.return_value = (
            "Entity: Acme (acme)\n\nRelationships (outgoing):\n  -> party_to: contract.pdf"
        )

        kb = _mock_kb(
            articles_by_id={"entity_acme": profile},
            articles_by_type={
                ArticleType.CLAUSE_SUMMARY: [clause],
                ArticleType.CONTRADICTION: [contradiction],
                ArticleType.INSIGHT: [insight],
            },
        )

        builder = KnowledgeContextBuilder(
            knowledge_base=kb,
            knowledge_graph=graph,
        )
        result = builder.build_context("acme", ["revenue"])
        assert result is not None
        assert "Entity Profile" in result
        assert "Relevant Clause Summaries" in result
        assert "Known Contradictions" in result
        assert "Document Relationships" in result
        assert "Prior Search Insights" in result

        # Verify ordering
        positions = [
            result.index("Entity Profile"),
            result.index("Relevant Clause Summaries"),
            result.index("Known Contradictions"),
            result.index("Document Relationships"),
            result.index("Prior Search Insights"),
        ]
        assert positions == sorted(positions)
