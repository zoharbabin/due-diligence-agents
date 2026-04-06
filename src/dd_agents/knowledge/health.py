"""Knowledge Health Checks — automated integrity validation (Issue #185).

Runs 7 categories of health checks against the Deal Knowledge Base,
optionally auto-fixing broken links and orphan articles. Produces a
structured :class:`HealthCheckResult` with issues, severity counts,
and suggested remediation actions.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from dd_agents.knowledge._utils import now_iso
from dd_agents.knowledge.articles import ArticleType, KnowledgeArticle

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.graph import DealKnowledgeGraph
    from dd_agents.knowledge.lineage import FindingLineageTracker

logger = logging.getLogger(__name__)


class HealthCheckCategory(StrEnum):
    """Categories of knowledge health checks."""

    STALENESS = "staleness"
    ORPHANS = "orphans"
    BROKEN_LINKS = "broken_links"
    MISSING_COVERAGE = "missing_coverage"
    CITATION_DRIFT = "citation_drift"
    GRAPH_INTEGRITY = "graph_integrity"
    LINEAGE_GAPS = "lineage_gaps"


class HealthIssue(BaseModel):
    """A single health issue detected during a knowledge base check."""

    category: HealthCheckCategory = Field(description="Which check category found this issue")
    severity: str = Field(description="Issue severity: 'warning' or 'error'")
    article_id: str | None = Field(default=None, description="Article ID involved, if applicable")
    entity_safe_name: str | None = Field(default=None, description="Entity safe name, if applicable")
    description: str = Field(description="Human-readable description of the issue")
    suggested_action: str = Field(description="Recommended remediation step")
    auto_fixable: bool = Field(default=False, description="Whether this issue can be auto-fixed")


class HealthCheckResult(BaseModel):
    """Aggregated result of all health checks."""

    timestamp: str = Field(description="ISO-8601 timestamp when the check ran")
    total_issues: int = Field(description="Total number of issues found")
    issues_by_category: dict[str, int] = Field(description="Issue counts keyed by category")
    issues_by_severity: dict[str, int] = Field(description="Issue counts keyed by severity")
    issues: list[HealthIssue] = Field(description="All detected issues")
    auto_fixed: int = Field(default=0, description="Number of issues that were auto-fixed")
    knowledge_base_stats: dict[str, int] = Field(description="Counts of articles by type and total")


class KnowledgeHealthChecker:
    """Automated integrity validation for the Deal Knowledge Base.

    Runs 7 categories of checks and optionally auto-fixes certain issues
    (broken links, orphan articles).

    Parameters
    ----------
    knowledge_base:
        The DealKnowledgeBase to check.
    knowledge_graph:
        Optional graph for cycle/contradiction detection.
    lineage_tracker:
        Optional lineage tracker for gap analysis.
    data_room_path:
        Optional path to the data room root for citation drift checks.
    """

    def __init__(
        self,
        knowledge_base: DealKnowledgeBase,
        knowledge_graph: DealKnowledgeGraph | None = None,
        lineage_tracker: FindingLineageTracker | None = None,
        data_room_path: Path | None = None,
    ) -> None:
        self._kb = knowledge_base
        self._graph = knowledge_graph
        self._lineage = lineage_tracker
        self._data_room_path = data_room_path

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def check_staleness(self, max_age_runs: int = 5) -> list[HealthIssue]:
        """Find articles that may be stale.

        Uses version==1 as a proxy for staleness when other articles have
        been updated (higher versions). Also flags articles with empty
        ``updated_at``.

        Parameters
        ----------
        max_age_runs:
            Unused placeholder for future run-based age tracking.
        """
        issues: list[HealthIssue] = []
        articles = self._kb.list_articles()
        if not articles:
            return issues

        max_version = max(a.version for a in articles)

        for article in articles:
            if article.superseded_by:
                continue
            if not article.updated_at:
                issues.append(
                    HealthIssue(
                        category=HealthCheckCategory.STALENESS,
                        severity="warning",
                        article_id=article.id,
                        description=f"Article '{article.title}' has no updated_at timestamp",
                        suggested_action="Re-process or manually update the article",
                    )
                )
            elif article.version == 1 and max_version > 1:
                issues.append(
                    HealthIssue(
                        category=HealthCheckCategory.STALENESS,
                        severity="warning",
                        article_id=article.id,
                        description=(
                            f"Article '{article.title}' is still at version 1 "
                            f"while other articles have been updated (max version {max_version})"
                        ),
                        suggested_action="Review whether this article needs updating",
                    )
                )
        return issues

    def check_orphans(self) -> list[HealthIssue]:
        """Find articles with no inbound links from other articles.

        Entity profiles are excluded since they are natural root nodes.
        """
        issues: list[HealthIssue] = []
        articles = self._kb.list_articles()
        if not articles:
            return issues

        # Collect all IDs referenced in any article's links
        referenced_ids: set[str] = set()
        for article in articles:
            for link_id in article.links:
                referenced_ids.add(link_id)

        for article in articles:
            if article.superseded_by:
                continue
            if article.article_type == ArticleType.ENTITY_PROFILE:
                continue
            if article.id not in referenced_ids:
                issues.append(
                    HealthIssue(
                        category=HealthCheckCategory.ORPHANS,
                        severity="warning",
                        article_id=article.id,
                        description=f"Article '{article.title}' has no inbound links from other articles",
                        suggested_action="Link this article to a related entity profile or parent article",
                        auto_fixable=True,
                    )
                )
        return issues

    def check_broken_links(self) -> list[HealthIssue]:
        """Find links pointing to non-existent article IDs."""
        issues: list[HealthIssue] = []
        articles = self._kb.list_articles()
        if not articles:
            return issues

        all_ids = {a.id for a in articles}

        for article in articles:
            for link_id in article.links:
                if link_id not in all_ids:
                    issues.append(
                        HealthIssue(
                            category=HealthCheckCategory.BROKEN_LINKS,
                            severity="error",
                            article_id=article.id,
                            description=f"Article '{article.title}' links to non-existent article '{link_id}'",
                            suggested_action=f"Remove broken link to '{link_id}'",
                            auto_fixable=True,
                        )
                    )
        return issues

    def check_missing_coverage(
        self,
        known_entities: list[str] | None = None,
    ) -> list[HealthIssue]:
        """Find entities that have no entity_profile article.

        If ``known_entities`` is provided, check those. Otherwise scan
        non-profile articles for entity mentions in tags.

        Parameters
        ----------
        known_entities:
            Optional list of entity safe names to check for profiles.
        """
        issues: list[HealthIssue] = []
        articles = self._kb.list_articles()

        # Collect existing entity profile names from tags
        profile_entities: set[str] = set()
        for article in articles:
            if article.article_type == ArticleType.ENTITY_PROFILE:
                for tag in article.tags:
                    tag_lower = tag.lower()
                    if tag_lower.startswith("entity:"):
                        profile_entities.add(tag_lower.removeprefix("entity:"))
                    else:
                        profile_entities.add(tag_lower)
                # Also add the article ID minus "entity_" prefix if present
                if article.id.startswith("entity_"):
                    profile_entities.add(article.id.removeprefix("entity_"))

        if known_entities is not None:
            entities_to_check = set(known_entities)
        else:
            # Scan non-profile article tags for entity mentions
            entities_to_check = set()
            for article in articles:
                if article.article_type == ArticleType.ENTITY_PROFILE:
                    continue
                for tag in article.tags:
                    tag_lower = tag.lower()
                    if tag_lower.startswith("entity:"):
                        entities_to_check.add(tag_lower.removeprefix("entity:"))

        for entity in sorted(entities_to_check):
            if entity not in profile_entities:
                issues.append(
                    HealthIssue(
                        category=HealthCheckCategory.MISSING_COVERAGE,
                        severity="warning",
                        entity_safe_name=entity,
                        description=f"Entity '{entity}' has no entity_profile article",
                        suggested_action=f"Create an entity_profile article for '{entity}'",
                    )
                )
        return issues

    def check_citation_drift(self) -> list[HealthIssue]:
        """Find sources referencing files not found in the data room.

        Skipped if no ``data_room_path`` was provided.
        """
        issues: list[HealthIssue] = []
        if self._data_room_path is None:
            return issues

        from pathlib import Path

        data_room = Path(self._data_room_path)

        for article in self._kb.list_articles():
            for source in article.sources:
                if not source.source_path:
                    continue
                full_path = data_room / source.source_path
                if not full_path.exists():
                    issues.append(
                        HealthIssue(
                            category=HealthCheckCategory.CITATION_DRIFT,
                            severity="error",
                            article_id=article.id,
                            description=(
                                f"Article '{article.title}' cites '{source.source_path}' "
                                "which does not exist in the data room"
                            ),
                            suggested_action="Verify the source path or update the citation",
                        )
                    )
        return issues

    def check_graph_integrity(self) -> list[HealthIssue]:
        """Check the knowledge graph for cycles and contradictions.

        Skipped if no graph was provided.
        """
        issues: list[HealthIssue] = []
        if self._graph is None:
            return issues

        cycles = self._graph.detect_cycles()
        for cycle in cycles:
            issues.append(
                HealthIssue(
                    category=HealthCheckCategory.GRAPH_INTEGRITY,
                    severity="error",
                    description=f"Cycle detected in knowledge graph: {' -> '.join(cycle)}",
                    suggested_action="Break the cycle by removing or reversing an edge",
                )
            )

        contradictions = self._graph.detect_contradictions()
        for node_a, node_b, reason in contradictions:
            issues.append(
                HealthIssue(
                    category=HealthCheckCategory.GRAPH_INTEGRITY,
                    severity="error",
                    description=f"Contradiction between '{node_a}' and '{node_b}': {reason}",
                    suggested_action="Resolve the conflict by updating or removing one of the nodes",
                )
            )
        return issues

    def check_lineage_gaps(
        self,
        current_findings: list[dict[str, Any]] | None = None,
    ) -> list[HealthIssue]:
        """Report lineage tracker statistics as informational issues.

        Skipped if no lineage tracker was provided.

        Parameters
        ----------
        current_findings:
            Unused placeholder for future cross-referencing.
        """
        issues: list[HealthIssue] = []
        if self._lineage is None:
            return issues

        active = self._lineage.get_active()
        if not active and self._lineage._findings:
            issues.append(
                HealthIssue(
                    category=HealthCheckCategory.LINEAGE_GAPS,
                    severity="warning",
                    description=(
                        f"All {len(self._lineage._findings)} tracked findings are resolved or recurred "
                        "— no active findings in lineage"
                    ),
                    suggested_action="Verify that all findings have been genuinely resolved",
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Auto-fix methods
    # ------------------------------------------------------------------

    def fix_broken_links(self) -> int:
        """Remove broken links from articles.

        Returns
        -------
        int
            Number of articles fixed.
        """
        articles = self._kb.list_articles()
        all_ids = {a.id for a in articles}
        fixed = 0

        for article in articles:
            broken = [lid for lid in article.links if lid not in all_ids]
            if broken:
                clean_links = [lid for lid in article.links if lid in all_ids]
                self._kb.update_article(article.id, {"links": clean_links})
                fixed += 1
                logger.info("Fixed broken links in article %s: removed %s", article.id, broken)
        return fixed

    def fix_orphan_articles(self) -> int:
        """Link orphan articles to entity profiles by matching entity tags.

        Returns
        -------
        int
            Number of orphan articles linked.
        """
        articles = self._kb.list_articles()

        # Build entity tag -> profile article mapping
        entity_profiles: dict[str, KnowledgeArticle] = {}
        for article in articles:
            if article.article_type == ArticleType.ENTITY_PROFILE:
                for tag in article.tags:
                    tag_lower = tag.lower()
                    if tag_lower.startswith("entity:"):
                        entity_profiles[tag_lower.removeprefix("entity:")] = article
                    else:
                        entity_profiles[tag_lower] = article

        # Find orphans
        referenced_ids: set[str] = set()
        for article in articles:
            for link_id in article.links:
                referenced_ids.add(link_id)

        fixed = 0
        for article in articles:
            if article.superseded_by:
                continue
            if article.article_type == ArticleType.ENTITY_PROFILE:
                continue
            if article.id in referenced_ids:
                continue

            # Try to match entity from tags
            for tag in article.tags:
                tag_lower = tag.lower()
                entity_key = tag_lower.removeprefix("entity:") if tag_lower.startswith("entity:") else tag_lower
                profile = entity_profiles.get(entity_key)
                if profile is not None:
                    # Add bidirectional links
                    new_profile_links = list(profile.links)
                    if article.id not in new_profile_links:
                        new_profile_links.append(article.id)
                        self._kb.update_article(profile.id, {"links": new_profile_links})

                    new_article_links = list(article.links)
                    if profile.id not in new_article_links:
                        new_article_links.append(profile.id)
                        self._kb.update_article(article.id, {"links": new_article_links})

                    fixed += 1
                    logger.info("Linked orphan %s to profile %s", article.id, profile.id)
                    break
        return fixed

    # ------------------------------------------------------------------
    # Aggregate check
    # ------------------------------------------------------------------

    def run_all_checks(self, *, auto_fix: bool = False) -> HealthCheckResult:
        """Run all health checks and aggregate results.

        Parameters
        ----------
        auto_fix:
            If True, run auto-fix methods after detection.

        Returns
        -------
        HealthCheckResult
            Aggregated result with all issues and statistics.
        """
        all_issues: list[HealthIssue] = []
        all_issues.extend(self.check_staleness())
        all_issues.extend(self.check_orphans())
        all_issues.extend(self.check_broken_links())
        all_issues.extend(self.check_missing_coverage())
        all_issues.extend(self.check_citation_drift())
        all_issues.extend(self.check_graph_integrity())
        all_issues.extend(self.check_lineage_gaps())

        auto_fixed = 0
        if auto_fix:
            auto_fixed += self.fix_broken_links()
            auto_fixed += self.fix_orphan_articles()

        # Compute stats
        articles = self._kb.list_articles()
        by_type: dict[str, int] = {}
        for article in articles:
            key = article.article_type.value
            by_type[key] = by_type.get(key, 0) + 1
        kb_stats: dict[str, int] = {"total": len(articles)}
        kb_stats.update(by_type)

        # Aggregate counts
        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for issue in all_issues:
            cat = issue.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1

        return HealthCheckResult(
            timestamp=now_iso(),
            total_issues=len(all_issues),
            issues_by_category=by_category,
            issues_by_severity=by_severity,
            issues=all_issues,
            auto_fixed=auto_fixed,
            knowledge_base_stats=kb_stats,
        )
