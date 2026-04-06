"""Tests for AgentKnowledgeEnricher — Issue #184.

Verifies domain-filtered knowledge context assembly for specialist agent
prompts. All tests use in-memory knowledge base fixtures with no external
API calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle
from dd_agents.knowledge.base import DealKnowledgeBase
from dd_agents.knowledge.graph import DealKnowledgeGraph
from dd_agents.knowledge.lineage import FindingLineage, FindingLineageTracker, FindingStatus, SeverityEvent
from dd_agents.knowledge.prompt_enrichment import (
    AgentKnowledgeEnricher,
    _agent_domain,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_kb(tmp_path: Path) -> DealKnowledgeBase:
    """Create a DealKnowledgeBase backed by a temp directory."""
    kb = DealKnowledgeBase(tmp_path)
    kb.ensure_dirs()
    return kb


@pytest.fixture()
def entity_article_legal() -> KnowledgeArticle:
    """Entity profile article with legal and finance clauses."""
    return KnowledgeArticle(
        id="entity_acme_corp",
        article_type=ArticleType.ENTITY_PROFILE,
        title="Entity Profile: acme_corp",
        content={
            "severity_counts": {"P0": 2, "P1": 3, "P2": 5},
            "key_clauses": [
                {"category": "change_of_control", "title": "CoC clause in MSA", "severity": "P0"},
                {"category": "termination", "title": "Termination for convenience", "severity": "P1"},
                {"category": "payment_terms", "title": "Net-60 payment terms", "severity": "P2"},
                {"category": "product_scope", "title": "Product scope definition", "severity": "P1"},
            ],
        },
        tags=["acme_corp"],
    )


@pytest.fixture()
def contradiction_article_legal() -> KnowledgeArticle:
    """Contradiction article with a legal category."""
    return KnowledgeArticle(
        id="contradiction_001",
        article_type=ArticleType.CONTRADICTION,
        title="Conflicting termination clauses",
        content={
            "category": "termination",
            "description": "MSA says 30-day notice but SOW says 60-day notice.",
        },
        tags=["acme_corp", "termination"],
    )


@pytest.fixture()
def contradiction_article_finance() -> KnowledgeArticle:
    """Contradiction article with a finance category."""
    return KnowledgeArticle(
        id="contradiction_002",
        article_type=ArticleType.CONTRADICTION,
        title="Conflicting payment terms",
        content={
            "category": "payment_terms",
            "description": "Invoice says Net-30 but contract says Net-60.",
        },
        tags=["acme_corp", "payment_terms"],
    )


@pytest.fixture()
def insight_article_legal() -> KnowledgeArticle:
    """Insight article tagged for legal domain."""
    return KnowledgeArticle(
        id="insight_001",
        article_type=ArticleType.INSIGHT,
        title="Unusual indemnification cap",
        content={
            "category": "indemnification",
            "description": "Cap set at 3x annual contract value, above market norms.",
        },
        tags=["acme_corp", "indemnification"],
    )


@pytest.fixture()
def insight_article_finance() -> KnowledgeArticle:
    """Insight article tagged for finance domain."""
    return KnowledgeArticle(
        id="insight_002",
        article_type=ArticleType.INSIGHT,
        title="Revenue recognition risk",
        content={
            "category": "revenue_recognition",
            "description": "Multi-element arrangement with uncertain allocation.",
        },
        tags=["acme_corp", "revenue_recognition"],
    )


# ---------------------------------------------------------------------------
# Tests: _agent_domain helper
# ---------------------------------------------------------------------------


class TestAgentDomain:
    """Tests for the _agent_domain helper function."""

    def test_legal_variations(self) -> None:
        assert _agent_domain("legal") == "legal"
        assert _agent_domain("LegalAgent") == "legal"
        assert _agent_domain("legal_agent") == "legal"

    def test_finance_variations(self) -> None:
        assert _agent_domain("finance") == "finance"
        assert _agent_domain("FinanceAgent") == "finance"

    def test_commercial_variations(self) -> None:
        assert _agent_domain("commercial") == "commercial"
        assert _agent_domain("CommercialAgent") == "commercial"

    def test_producttech_variations(self) -> None:
        assert _agent_domain("producttech") == "producttech"
        assert _agent_domain("ProductTechAgent") == "producttech"
        assert _agent_domain("ProductTech") == "producttech"

    def test_unknown_returns_none(self) -> None:
        assert _agent_domain("unknown_agent") is None
        assert _agent_domain("judge") is None
        assert _agent_domain("") is None


# ---------------------------------------------------------------------------
# Tests: AgentKnowledgeEnricher
# ---------------------------------------------------------------------------


class TestEnricherReturnsNone:
    """Tests for cases where build_agent_context should return None."""

    def test_returns_none_when_no_knowledge_base(self) -> None:
        """Returns None when no knowledge base is provided (first run)."""
        enricher = AgentKnowledgeEnricher(knowledge_base=None)
        result = enricher.build_agent_context("legal", ["acme_corp"])
        assert result is None

    def test_returns_none_when_kb_has_no_data(self, tmp_kb: DealKnowledgeBase) -> None:
        """Returns None when KB exists but has no articles for the entities."""
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["nonexistent_entity"])
        assert result is None

    def test_returns_none_for_empty_customer_list(self, tmp_kb: DealKnowledgeBase) -> None:
        """Returns None when customer list is empty."""
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", [])
        assert result is None

    def test_returns_none_for_unknown_agent(
        self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle
    ) -> None:
        """Returns None for unrecognised agent names."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("judge", ["acme_corp"])
        assert result is None

    def test_returns_none_when_total_under_100_chars(self, tmp_kb: DealKnowledgeBase) -> None:
        """Returns None when assembled context is under 100 chars."""
        # Write a minimal entity profile that would produce very short output
        tiny = KnowledgeArticle(
            id="entity_tiny",
            article_type=ArticleType.ENTITY_PROFILE,
            title="Tiny",
            content={"key_clauses": [{"category": "termination", "title": "T"}]},
            tags=["tiny"],
        )
        tmp_kb.write_article(tiny)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        # With a very small max_chars, output will be < 100
        result = enricher.build_agent_context("legal", ["tiny"], max_chars=50)
        assert result is None


class TestEntityProfiles:
    """Tests for entity profile domain filtering."""

    def test_legal_sees_legal_categories_only(
        self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle
    ) -> None:
        """Legal agent only sees legal-domain clauses in entity profiles."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "CoC clause in MSA" in result
        assert "Termination for convenience" in result
        # Finance clause should NOT appear
        assert "Net-60 payment terms" not in result
        # ProductTech clause should NOT appear
        assert "Product scope definition" not in result

    def test_finance_does_not_see_legal_findings(
        self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle
    ) -> None:
        """Finance agent does not see legal-domain clauses."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("finance", ["acme_corp"])

        assert result is not None
        # Finance sees payment_terms
        assert "Net-60 payment terms" in result
        # Legal clauses should NOT appear
        assert "CoC clause in MSA" not in result
        assert "Termination for convenience" not in result

    def test_severity_counts_included(self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle) -> None:
        """Severity counts are included in entity profiles."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "P0: 2" in result
        assert "P1: 3" in result


class TestLineageHighlights:
    """Tests for finding lineage integration."""

    def test_lineage_included_when_tracker_available(self, tmp_kb: DealKnowledgeBase, tmp_path: Path) -> None:
        """Lineage highlights appear when a tracker with data is provided."""
        tmp_kb.write_article(
            KnowledgeArticle(
                id="entity_acme_corp",
                article_type=ArticleType.ENTITY_PROFILE,
                title="Entity Profile: acme_corp",
                content={
                    "key_clauses": [
                        {"category": "termination", "title": "Term clause", "severity": "P0"},
                    ],
                },
                tags=["acme_corp"],
            )
        )

        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        # Manually inject a persistent finding in the legal domain
        tracker._findings["fp001"] = FindingLineage(
            fingerprint="fp001",
            first_seen_run_id="run_1",
            first_seen_timestamp="2026-01-01T00:00:00Z",
            last_seen_run_id="run_5",
            last_seen_timestamp="2026-01-05T00:00:00Z",
            run_count=5,
            current_severity="P0",
            severity_history=[
                SeverityEvent(
                    run_id="run_3",
                    timestamp="2026-01-03T00:00:00Z",
                    old_severity="P1",
                    new_severity="P0",
                )
            ],
            status=FindingStatus.ACTIVE,
            latest_title="Missing CoC consent",
            latest_description="Change of control consent missing in MSA",
            entity_safe_name="acme_corp",
            agent="legal",
            category="change_of_control",
        )

        enricher = AgentKnowledgeEnricher(
            knowledge_base=tmp_kb,
            lineage_tracker=tracker,
        )
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "Finding Lineage" in result
        assert "Missing CoC consent" in result
        assert "5 runs" in result
        assert "P1 -> P0" in result

    def test_lineage_filtered_by_domain(self, tmp_kb: DealKnowledgeBase, tmp_path: Path) -> None:
        """Lineage findings outside agent's domain are excluded."""
        tmp_kb.write_article(
            KnowledgeArticle(
                id="entity_acme_corp",
                article_type=ArticleType.ENTITY_PROFILE,
                title="Entity Profile: acme_corp",
                content={
                    "severity_counts": {"P0": 1, "P1": 2, "P2": 3},
                    "key_clauses": [
                        {
                            "category": "payment_terms",
                            "title": "Net-60 payment terms with auto-renewal",
                            "severity": "P2",
                        },
                        {
                            "category": "pricing",
                            "title": "Volume-based pricing tiers applicable to all orders",
                            "severity": "P1",
                        },
                        {
                            "category": "insurance",
                            "title": "Minimum insurance coverage requirements for vendor",
                            "severity": "P2",
                        },
                    ],
                },
                tags=["acme_corp"],
            )
        )

        tracker = FindingLineageTracker(tmp_path / "lineage.json")
        # Legal-domain finding
        tracker._findings["fp_legal"] = FindingLineage(
            fingerprint="fp_legal",
            first_seen_run_id="run_1",
            first_seen_timestamp="2026-01-01T00:00:00Z",
            last_seen_run_id="run_4",
            last_seen_timestamp="2026-01-04T00:00:00Z",
            run_count=4,
            current_severity="P1",
            status=FindingStatus.ACTIVE,
            latest_title="Legal finding",
            latest_description="A legal domain finding",
            entity_safe_name="acme_corp",
            agent="legal",
            category="termination",
        )

        enricher = AgentKnowledgeEnricher(
            knowledge_base=tmp_kb,
            lineage_tracker=tracker,
        )
        # Finance agent should NOT see the legal-domain finding
        result = enricher.build_agent_context("finance", ["acme_corp"])
        assert result is not None
        assert "Legal finding" not in result


class TestContradictions:
    """Tests for contradiction domain filtering."""

    def test_contradictions_filtered_by_domain(
        self,
        tmp_kb: DealKnowledgeBase,
        entity_article_legal: KnowledgeArticle,
        contradiction_article_legal: KnowledgeArticle,
        contradiction_article_finance: KnowledgeArticle,
    ) -> None:
        """Legal agent sees legal contradictions, not finance ones."""
        tmp_kb.write_article(entity_article_legal)
        tmp_kb.write_article(contradiction_article_legal)
        tmp_kb.write_article(contradiction_article_finance)

        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "Conflicting termination clauses" in result
        assert "Conflicting payment terms" not in result


class TestDocumentRelationships:
    """Tests for knowledge graph document relationships."""

    def test_doc_relationships_included_when_graph_available(self, tmp_kb: DealKnowledgeBase) -> None:
        """Document relationships appear when a graph with entity data is provided."""
        tmp_kb.write_article(
            KnowledgeArticle(
                id="entity_acme_corp",
                article_type=ArticleType.ENTITY_PROFILE,
                title="Entity Profile: acme_corp",
                content={
                    "key_clauses": [
                        {"category": "termination", "title": "Term clause", "severity": "P0"},
                    ],
                },
                tags=["acme_corp"],
            )
        )

        graph = DealKnowledgeGraph()
        graph.add_entity("acme_corp", "Acme Corp")
        doc_id = graph.add_document("contracts/msa.pdf", "contract")
        from dd_agents.knowledge.graph import EdgeType, GraphEdge

        graph.add_edge(
            GraphEdge(
                source_id="entity:acme_corp",
                target_id=doc_id,
                edge_type=EdgeType.PARTY_TO,
            )
        )

        enricher = AgentKnowledgeEnricher(
            knowledge_base=tmp_kb,
            knowledge_graph=graph,
        )
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "Document Relationships" in result
        assert "Acme Corp" in result

    def test_doc_relationships_excluded_when_no_graph(
        self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle
    ) -> None:
        """No doc relationships section when graph is None."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb, knowledge_graph=None)
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "Document Relationships" not in result


class TestPriorInsights:
    """Tests for prior insight domain filtering."""

    def test_insights_filtered_by_domain_tags(
        self,
        tmp_kb: DealKnowledgeBase,
        entity_article_legal: KnowledgeArticle,
        insight_article_legal: KnowledgeArticle,
        insight_article_finance: KnowledgeArticle,
    ) -> None:
        """Legal agent sees legal insights, not finance ones."""
        tmp_kb.write_article(entity_article_legal)
        tmp_kb.write_article(insight_article_legal)
        tmp_kb.write_article(insight_article_finance)

        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["acme_corp"])

        assert result is not None
        assert "Unusual indemnification cap" in result
        assert "Revenue recognition risk" not in result


class TestBudgetEnforcement:
    """Tests for character budget enforcement."""

    def test_total_within_max_chars(self, tmp_kb: DealKnowledgeBase, entity_article_legal: KnowledgeArticle) -> None:
        """Total assembled context stays within max_chars."""
        tmp_kb.write_article(entity_article_legal)
        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        max_chars = 500
        result = enricher.build_agent_context("legal", ["acme_corp"], max_chars=max_chars)

        assert result is not None
        assert len(result) <= max_chars


class TestMultipleCustomers:
    """Tests for multi-entity context assembly."""

    def test_multiple_customers_each_get_context(self, tmp_kb: DealKnowledgeBase) -> None:
        """Each customer gets its own profile section."""
        for name in ["alpha", "beta"]:
            tmp_kb.write_article(
                KnowledgeArticle(
                    id=f"entity_{name}",
                    article_type=ArticleType.ENTITY_PROFILE,
                    title=f"Entity Profile: {name}",
                    content={
                        "severity_counts": {"P0": 1},
                        "key_clauses": [
                            {"category": "termination", "title": f"{name} termination clause", "severity": "P1"},
                        ],
                    },
                    tags=[name],
                )
            )

        enricher = AgentKnowledgeEnricher(knowledge_base=tmp_kb)
        result = enricher.build_agent_context("legal", ["alpha", "beta"])

        assert result is not None
        assert "alpha termination clause" in result
        assert "beta termination clause" in result
        assert "--- alpha ---" in result
        assert "--- beta ---" in result
