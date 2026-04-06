"""Knowledge-enriched search context builder (Issue #181).

Assembles pre-computed knowledge from the Deal Knowledge Base, Knowledge Graph,
and Finding Lineage Tracker into a structured text block that enriches search
prompts. Budget: max 15K chars of knowledge context per customer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dd_agents.knowledge.articles import ArticleType

if TYPE_CHECKING:
    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.graph import DealKnowledgeGraph
    from dd_agents.knowledge.lineage import FindingLineageTracker

logger = logging.getLogger(__name__)

# Minimum assembled context length to justify returning (avoid noise).
_MIN_CONTEXT_CHARS = 100


class KnowledgeContextBuilder:
    """Assembles pre-computed knowledge context for search enrichment.

    Budget: max 15K chars of knowledge context per customer.

    Priority order (sub-budgets as fraction of ``max_chars``):
        1. Entity profile summary — 40%
        2. Relevant clause summaries matched to column names — 20%
        3. Known contradictions — 15%
        4. Document relationship context from graph — 15%
        5. Recent insights from prior searches — 10%

    Parameters
    ----------
    knowledge_base:
        The deal's persistent knowledge base (may be None).
    knowledge_graph:
        The deal's cross-document relationship graph (may be None).
    lineage_tracker:
        The deal's cross-run finding lineage tracker (may be None).
    """

    def __init__(
        self,
        knowledge_base: DealKnowledgeBase | None,
        knowledge_graph: DealKnowledgeGraph | None = None,
        lineage_tracker: FindingLineageTracker | None = None,
    ) -> None:
        self._kb = knowledge_base
        self._graph = knowledge_graph
        self._lineage = lineage_tracker

    def build_context(
        self,
        entity_safe_name: str,
        column_names: list[str],
        max_chars: int = 15_000,
    ) -> str | None:
        """Build knowledge context for a search.

        Returns ``None`` if no knowledge base is available or the assembled
        context is under 100 characters (not worth adding noise).

        Parameters
        ----------
        entity_safe_name:
            The entity's ``customer_safe_name`` (lowercase, normalized).
        column_names:
            List of analysis column names to match clause summaries against.
        max_chars:
            Maximum total character budget for the assembled context.

        Returns
        -------
        str | None
            Formatted knowledge context or None if insufficient data.
        """
        if self._kb is None:
            return None

        # Sub-budgets
        profile_budget = int(max_chars * 0.40)
        clause_budget = int(max_chars * 0.20)
        contradiction_budget = int(max_chars * 0.15)
        graph_budget = int(max_chars * 0.15)
        insight_budget = int(max_chars * 0.10)

        sections: list[str] = []

        # 1. Entity profile summary
        profile_text = self._build_entity_profile(entity_safe_name, profile_budget)
        if profile_text:
            sections.append(profile_text)

        # 2. Clause summaries matched to column names
        clause_text = self._build_clause_summaries(entity_safe_name, column_names, clause_budget)
        if clause_text:
            sections.append(clause_text)

        # 3. Known contradictions
        contradiction_text = self._build_contradictions(entity_safe_name, contradiction_budget)
        if contradiction_text:
            sections.append(contradiction_text)

        # 4. Document relationship context from graph
        graph_text = self._build_graph_context(entity_safe_name, graph_budget)
        if graph_text:
            sections.append(graph_text)

        # 5. Recent insights
        insight_text = self._build_insights(entity_safe_name, insight_budget)
        if insight_text:
            sections.append(insight_text)

        if not sections:
            return None

        assembled = "\n\n".join(sections)

        # Truncate to max_chars if needed
        if len(assembled) > max_chars:
            assembled = assembled[: max_chars - 3] + "..."

        if len(assembled) < _MIN_CONTEXT_CHARS:
            return None

        return assembled

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_entity_profile(self, entity_safe_name: str, budget: int) -> str | None:
        """Build entity profile section from knowledge base.

        Looks up an article with ID ``entity_{entity_safe_name}`` and
        formats its content (severity distribution, key clauses, etc.).

        Parameters
        ----------
        entity_safe_name:
            The entity's safe name.
        budget:
            Maximum character budget for this section.

        Returns
        -------
        str | None
            Formatted entity profile section or None.
        """
        if self._kb is None:
            return None

        article_id = f"entity_{entity_safe_name}"
        article = self._kb.get_article(article_id)
        if article is None:
            return None

        lines: list[str] = [f"## Entity Profile: {article.title}"]

        content = article.content
        if isinstance(content, dict):
            # Format severity distribution if present
            severity_dist = content.get("severity_distribution")
            if isinstance(severity_dist, dict):
                lines.append("Severity distribution:")
                for sev, count in severity_dist.items():
                    lines.append(f"  {sev}: {count}")

            # Format key clauses if present
            key_clauses = content.get("key_clauses")
            if isinstance(key_clauses, list):
                lines.append("Key clauses:")
                for clause in key_clauses:
                    if isinstance(clause, str):
                        lines.append(f"  - {clause}")
                    elif isinstance(clause, dict):
                        lines.append(f"  - {clause.get('title', clause.get('name', str(clause)))}")

            # Format summary if present
            summary = content.get("summary")
            if isinstance(summary, str):
                lines.append(f"Summary: {summary}")

        text = "\n".join(lines)
        if len(text) > budget:
            text = text[: budget - 3] + "..."
        return text

    def _build_clause_summaries(
        self,
        entity_safe_name: str,
        column_names: list[str],
        budget: int,
    ) -> str | None:
        """Build clause summaries matched to column names.

        For each column name, searches for matching clause articles where the
        column name appears as a substring in the article tags or title.

        Parameters
        ----------
        entity_safe_name:
            The entity's safe name.
        column_names:
            List of analysis column names to match against.
        budget:
            Maximum character budget for this section.

        Returns
        -------
        str | None
            Formatted clause summaries section or None.
        """
        if self._kb is None or not column_names:
            return None

        clause_articles = self._kb.list_articles(article_type=ArticleType.CLAUSE_SUMMARY)
        if not clause_articles:
            return None

        lines: list[str] = ["## Relevant Clause Summaries"]
        chars_used = len(lines[0])

        for col_name in column_names:
            col_lower = col_name.lower()
            for article in clause_articles:
                if article.superseded_by:
                    continue
                # Check entity match via tags
                entity_match = any(entity_safe_name.lower() in tag.lower() for tag in article.tags)
                if not entity_match:
                    continue
                # Check column name match in tags or title
                title_match = col_lower in article.title.lower()
                tag_match = any(col_lower in tag.lower() for tag in article.tags)
                if not title_match and not tag_match:
                    continue

                summary = article.content.get("summary", "") if isinstance(article.content, dict) else ""
                entry = f"- [{col_name}] {article.title}"
                if summary:
                    entry += f": {summary}"

                if chars_used + len(entry) + 1 > budget:
                    break
                lines.append(entry)
                chars_used += len(entry) + 1

        if len(lines) <= 1:
            return None

        text = "\n".join(lines)
        if len(text) > budget:
            text = text[: budget - 3] + "..."
        return text

    def _build_contradictions(self, entity_safe_name: str, budget: int) -> str | None:
        """Build contradictions section for the entity.

        Lists articles of type CONTRADICTION where the entity appears in tags.

        Parameters
        ----------
        entity_safe_name:
            The entity's safe name.
        budget:
            Maximum character budget for this section.

        Returns
        -------
        str | None
            Formatted contradictions section or None.
        """
        if self._kb is None:
            return None

        contradiction_articles = self._kb.list_articles(article_type=ArticleType.CONTRADICTION)
        if not contradiction_articles:
            return None

        lines: list[str] = ["## Known Contradictions"]
        chars_used = len(lines[0])

        for article in contradiction_articles:
            if article.superseded_by:
                continue
            entity_match = any(entity_safe_name.lower() in tag.lower() for tag in article.tags)
            if not entity_match:
                continue

            description = article.content.get("description", "") if isinstance(article.content, dict) else ""
            entry = f"- {article.title}"
            if description:
                entry += f": {description}"

            if chars_used + len(entry) + 1 > budget:
                break
            lines.append(entry)
            chars_used += len(entry) + 1

        if len(lines) <= 1:
            return None

        text = "\n".join(lines)
        if len(text) > budget:
            text = text[: budget - 3] + "..."
        return text

    def _build_graph_context(self, entity_safe_name: str, budget: int) -> str | None:
        """Build document relationship context from the knowledge graph.

        Delegates to ``DealKnowledgeGraph.get_entity_context()`` if available.

        Parameters
        ----------
        entity_safe_name:
            The entity's safe name.
        budget:
            Maximum character budget for this section.

        Returns
        -------
        str | None
            Formatted graph context section or None.
        """
        if self._graph is None:
            return None

        raw = self._graph.get_entity_context(entity_safe_name, max_chars=budget)
        if not raw or raw.startswith("No graph data"):
            return None

        text = f"## Document Relationships\n{raw}"
        if len(text) > budget:
            text = text[: budget - 3] + "..."
        return text

    def _build_insights(self, entity_safe_name: str, budget: int) -> str | None:
        """Build insights section from prior searches.

        Lists articles of type INSIGHT where the entity appears in tags.

        Parameters
        ----------
        entity_safe_name:
            The entity's safe name.
        budget:
            Maximum character budget for this section.

        Returns
        -------
        str | None
            Formatted insights section or None.
        """
        if self._kb is None:
            return None

        insight_articles = self._kb.list_articles(article_type=ArticleType.INSIGHT)
        if not insight_articles:
            return None

        lines: list[str] = ["## Prior Search Insights"]
        chars_used = len(lines[0])

        for article in insight_articles:
            if article.superseded_by:
                continue
            entity_match = any(entity_safe_name.lower() in tag.lower() for tag in article.tags)
            if not entity_match:
                continue

            summary = article.content.get("summary", "") if isinstance(article.content, dict) else ""
            entry = f"- {article.title}"
            if summary:
                entry += f": {summary}"

            if chars_used + len(entry) + 1 > budget:
                break
            lines.append(entry)
            chars_used += len(entry) + 1

        if len(lines) <= 1:
            return None

        text = "\n".join(lines)
        if len(text) > budget:
            text = text[: budget - 3] + "..."
        return text
