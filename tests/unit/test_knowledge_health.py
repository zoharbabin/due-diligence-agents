"""Unit tests for Knowledge Health Checks (Issue #185)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle, KnowledgeSource
from dd_agents.knowledge.base import DealKnowledgeBase
from dd_agents.knowledge.graph import DealKnowledgeGraph, EdgeType, GraphEdge
from dd_agents.knowledge.health import (
    HealthCheckCategory,
    HealthCheckResult,
    HealthIssue,
    KnowledgeHealthChecker,
)
from dd_agents.knowledge.lineage import FindingLineageTracker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kb(tmp_path: Path) -> DealKnowledgeBase:
    """Return an initialized DealKnowledgeBase."""
    dkb = DealKnowledgeBase(tmp_path)
    dkb.ensure_dirs()
    return dkb


def _make_article(
    article_id: str = "art_001",
    article_type: ArticleType = ArticleType.ENTITY_PROFILE,
    title: str = "Test Article",
    tags: list[str] | None = None,
    links: list[str] | None = None,
    sources: list[KnowledgeSource] | None = None,
    version: int = 1,
    updated_at: str = "2026-03-07T14:30:00+00:00",
    superseded_by: str | None = None,
) -> KnowledgeArticle:
    """Helper to create a test article."""
    return KnowledgeArticle(
        id=article_id,
        article_type=article_type,
        title=title,
        content={"key": "value"},
        sources=sources
        if sources is not None
        else [
            KnowledgeSource(
                source_path="contracts/msa.pdf",
                page="5",
                run_id="run_001",
            )
        ],
        tags=tags if tags is not None else ["test"],
        links=links or [],
        created_at="2026-03-07T14:30:00+00:00",
        updated_at=updated_at,
        created_by="pipeline:run_001",
        version=version,
        superseded_by=superseded_by,
    )


# ---------------------------------------------------------------------------
# Test: healthy knowledge base has zero issues
# ---------------------------------------------------------------------------


class TestHealthyKB:
    """A well-linked KB with no problems should produce zero issues."""

    def test_healthy_kb_zero_issues(self, kb: DealKnowledgeBase) -> None:
        profile = _make_article(
            article_id="entity_acme",
            article_type=ArticleType.ENTITY_PROFILE,
            title="Entity Profile: Acme",
            tags=["entity:acme"],
            links=["clause_001"],
            version=2,
        )
        clause = _make_article(
            article_id="clause_001",
            article_type=ArticleType.CLAUSE_SUMMARY,
            title="Clause Summary",
            tags=["acme"],
            links=["entity_acme"],
            version=2,
        )
        kb.write_article(profile)
        kb.write_article(clause)

        checker = KnowledgeHealthChecker(kb)
        result = checker.run_all_checks()
        assert result.total_issues == 0
        assert result.issues == []


# ---------------------------------------------------------------------------
# Test: broken links
# ---------------------------------------------------------------------------


class TestBrokenLinks:
    def test_broken_links_detected(self, kb: DealKnowledgeBase) -> None:
        article = _make_article(
            article_id="art_a",
            links=["nonexistent_id"],
        )
        kb.write_article(article)

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_broken_links()
        assert len(issues) == 1
        assert issues[0].category == HealthCheckCategory.BROKEN_LINKS
        assert issues[0].severity == "error"
        assert issues[0].auto_fixable is True
        assert "nonexistent_id" in issues[0].description

    def test_broken_links_auto_fixed(self, kb: DealKnowledgeBase) -> None:
        article = _make_article(
            article_id="art_a",
            links=["nonexistent_id", "also_missing"],
        )
        kb.write_article(article)

        checker = KnowledgeHealthChecker(kb)
        fixed = checker.fix_broken_links()
        assert fixed == 1

        updated = kb.get_article("art_a")
        assert updated is not None
        assert updated.links == []


# ---------------------------------------------------------------------------
# Test: orphan articles
# ---------------------------------------------------------------------------


class TestOrphans:
    def test_orphan_detected(self, kb: DealKnowledgeBase) -> None:
        # Entity profile (not orphan by definition)
        profile = _make_article(
            article_id="entity_acme",
            article_type=ArticleType.ENTITY_PROFILE,
            tags=["entity:acme"],
        )
        # Clause with no inbound links = orphan
        clause = _make_article(
            article_id="clause_001",
            article_type=ArticleType.CLAUSE_SUMMARY,
            title="Orphan Clause",
            tags=["entity:acme"],
        )
        kb.write_article(profile)
        kb.write_article(clause)

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_orphans()
        assert len(issues) == 1
        assert issues[0].article_id == "clause_001"
        assert issues[0].category == HealthCheckCategory.ORPHANS
        assert issues[0].auto_fixable is True

    def test_orphan_auto_fixed(self, kb: DealKnowledgeBase) -> None:
        profile = _make_article(
            article_id="entity_acme",
            article_type=ArticleType.ENTITY_PROFILE,
            tags=["entity:acme"],
        )
        clause = _make_article(
            article_id="clause_001",
            article_type=ArticleType.CLAUSE_SUMMARY,
            title="Orphan Clause",
            tags=["entity:acme"],
        )
        kb.write_article(profile)
        kb.write_article(clause)

        checker = KnowledgeHealthChecker(kb)
        fixed = checker.fix_orphan_articles()
        assert fixed == 1

        updated_profile = kb.get_article("entity_acme")
        assert updated_profile is not None
        assert "clause_001" in updated_profile.links

        updated_clause = kb.get_article("clause_001")
        assert updated_clause is not None
        assert "entity_acme" in updated_clause.links


# ---------------------------------------------------------------------------
# Test: missing coverage
# ---------------------------------------------------------------------------


class TestMissingCoverage:
    def test_missing_coverage_detected(self, kb: DealKnowledgeBase) -> None:
        # Clause references entity "beta" but no beta profile exists
        clause = _make_article(
            article_id="clause_x",
            article_type=ArticleType.CLAUSE_SUMMARY,
            tags=["entity:beta"],
        )
        kb.write_article(clause)

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_missing_coverage()
        assert len(issues) == 1
        assert issues[0].entity_safe_name == "beta"
        assert issues[0].category == HealthCheckCategory.MISSING_COVERAGE

    def test_missing_coverage_with_known_entities(self, kb: DealKnowledgeBase) -> None:
        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_missing_coverage(known_entities=["alpha", "gamma"])
        assert len(issues) == 2


# ---------------------------------------------------------------------------
# Test: citation drift
# ---------------------------------------------------------------------------


class TestCitationDrift:
    def test_citation_drift_detected(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        data_room = tmp_path / "dataroom"
        data_room.mkdir()
        # Source references a file that does not exist
        article = _make_article(
            article_id="art_cite",
            sources=[KnowledgeSource(source_path="missing/file.pdf")],
        )
        kb.write_article(article)

        checker = KnowledgeHealthChecker(kb, data_room_path=data_room)
        issues = checker.check_citation_drift()
        assert len(issues) == 1
        assert issues[0].category == HealthCheckCategory.CITATION_DRIFT
        assert issues[0].severity == "error"

    def test_citation_drift_skipped_no_data_room(self, kb: DealKnowledgeBase) -> None:
        article = _make_article(
            article_id="art_cite",
            sources=[KnowledgeSource(source_path="missing/file.pdf")],
        )
        kb.write_article(article)

        checker = KnowledgeHealthChecker(kb)  # no data_room_path
        issues = checker.check_citation_drift()
        assert issues == []


# ---------------------------------------------------------------------------
# Test: graph integrity
# ---------------------------------------------------------------------------


class TestGraphIntegrity:
    def test_graph_cycles_detected(self, kb: DealKnowledgeBase) -> None:
        graph = DealKnowledgeGraph()
        graph.add_entity("a", "A")
        graph.add_entity("b", "B")
        graph.add_edge(GraphEdge(source_id="entity:a", target_id="entity:b", edge_type=EdgeType.REFERENCES))
        graph.add_edge(GraphEdge(source_id="entity:b", target_id="entity:a", edge_type=EdgeType.REFERENCES))

        checker = KnowledgeHealthChecker(kb, knowledge_graph=graph)
        issues = checker.check_graph_integrity()
        cycle_issues = [i for i in issues if "Cycle" in i.description]
        assert len(cycle_issues) >= 1
        assert cycle_issues[0].severity == "error"

    def test_graph_contradictions_detected(self, kb: DealKnowledgeBase) -> None:
        graph = DealKnowledgeGraph()
        graph.add_entity("x", "X")
        graph.add_entity("y", "Y")
        graph.add_edge(
            GraphEdge(
                source_id="entity:x",
                target_id="entity:y",
                edge_type=EdgeType.CONFLICTS_WITH,
                metadata={"reason": "conflicting terms"},
            )
        )

        checker = KnowledgeHealthChecker(kb, knowledge_graph=graph)
        issues = checker.check_graph_integrity()
        contradiction_issues = [i for i in issues if "Contradiction" in i.description]
        assert len(contradiction_issues) == 1
        assert "conflicting terms" in contradiction_issues[0].description

    def test_graph_check_skipped_no_graph(self, kb: DealKnowledgeBase) -> None:
        checker = KnowledgeHealthChecker(kb)  # no graph
        issues = checker.check_graph_integrity()
        assert issues == []


# ---------------------------------------------------------------------------
# Test: empty KB
# ---------------------------------------------------------------------------


class TestEmptyKB:
    def test_empty_kb_zero_issues(self, kb: DealKnowledgeBase) -> None:
        checker = KnowledgeHealthChecker(kb)
        result = checker.run_all_checks()
        assert result.total_issues == 0
        assert result.issues == []
        assert result.knowledge_base_stats["total"] == 0


# ---------------------------------------------------------------------------
# Test: run_all_checks aggregation
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    def test_aggregates_correctly(self, kb: DealKnowledgeBase) -> None:
        # Create a broken link and an orphan
        profile = _make_article(
            article_id="entity_acme",
            article_type=ArticleType.ENTITY_PROFILE,
            tags=["entity:acme"],
            links=["deleted_article"],
        )
        orphan = _make_article(
            article_id="insight_001",
            article_type=ArticleType.INSIGHT,
            title="Orphan Insight",
            tags=["misc"],
        )
        kb.write_article(profile)
        kb.write_article(orphan)

        checker = KnowledgeHealthChecker(kb)
        result = checker.run_all_checks()

        assert result.total_issues >= 2
        assert HealthCheckCategory.BROKEN_LINKS.value in result.issues_by_category
        assert HealthCheckCategory.ORPHANS.value in result.issues_by_category
        assert result.knowledge_base_stats["total"] == 2
        assert "error" in result.issues_by_severity


# ---------------------------------------------------------------------------
# Test: HealthCheckResult serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_health_check_result_serialization(self) -> None:
        result = HealthCheckResult(
            timestamp="2026-04-05T10:00:00+00:00",
            total_issues=1,
            issues_by_category={"broken_links": 1},
            issues_by_severity={"error": 1},
            issues=[
                HealthIssue(
                    category=HealthCheckCategory.BROKEN_LINKS,
                    severity="error",
                    article_id="art_001",
                    description="Broken link",
                    suggested_action="Remove it",
                    auto_fixable=True,
                ),
            ],
            auto_fixed=0,
            knowledge_base_stats={"total": 5},
        )
        data = result.model_dump(mode="json")
        roundtrip = HealthCheckResult.model_validate(data)
        assert roundtrip.total_issues == 1
        assert roundtrip.issues[0].category == HealthCheckCategory.BROKEN_LINKS
        assert roundtrip.issues[0].auto_fixable is True


# ---------------------------------------------------------------------------
# Test: lineage gaps
# ---------------------------------------------------------------------------


class TestLineageGaps:
    def test_lineage_check_skipped_no_tracker(self, kb: DealKnowledgeBase) -> None:
        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_lineage_gaps()
        assert issues == []

    def test_lineage_gap_all_resolved(self, kb: DealKnowledgeBase, tmp_path: Path) -> None:
        lineage_path = tmp_path / "lineage.json"
        tracker = FindingLineageTracker(lineage_path)
        # Process a run and then resolve everything
        tracker.update_from_run(
            "run_001",
            [
                {
                    "analysis_unit": "acme",
                    "agent": "legal",
                    "category": "risk",
                    "title": "Finding A",
                    "description": "Desc",
                    "severity": "high",
                }
            ],
        )
        # Second run with no findings resolves all
        tracker.update_from_run("run_002", [])

        checker = KnowledgeHealthChecker(kb, lineage_tracker=tracker)
        issues = checker.check_lineage_gaps()
        assert len(issues) == 1
        assert issues[0].category == HealthCheckCategory.LINEAGE_GAPS
        assert issues[0].severity == "warning"


# ---------------------------------------------------------------------------
# Test: staleness check (U2)
# ---------------------------------------------------------------------------


class TestStaleness:
    def test_staleness_flags_version_1_articles(self, kb: DealKnowledgeBase) -> None:
        """Articles at version 1 should be flagged stale when others have higher versions."""
        a1 = _make_article(article_id="a1", title="First")
        a2 = _make_article(article_id="a2", title="Second")
        kb.write_article(a1)
        kb.write_article(a2)
        # Update a2 so it's at version 2
        kb.update_article("a2", {"title": "Second Updated"})

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_staleness()
        stale_ids = [i.article_id for i in issues]
        assert "a1" in stale_ids
        assert "a2" not in stale_ids

    def test_staleness_no_issues_when_all_same_version(self, kb: DealKnowledgeBase) -> None:
        """No staleness when all articles are at the same version."""
        kb.write_article(_make_article(article_id="x1", title="X1"))
        kb.write_article(_make_article(article_id="x2", title="X2"))

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_staleness()
        assert len(issues) == 0

    def test_staleness_skips_superseded(self, kb: DealKnowledgeBase) -> None:
        """Superseded articles should not be flagged as stale."""
        a1 = _make_article(article_id="a1", title="Old", superseded_by="a2")
        a2 = _make_article(article_id="a2", title="New")
        kb.write_article(a1)
        kb.write_article(a2)
        kb.update_article("a2", {"title": "New Updated"})

        checker = KnowledgeHealthChecker(kb)
        issues = checker.check_staleness()
        stale_ids = [i.article_id for i in issues]
        assert "a1" not in stale_ids  # superseded, should be skipped
