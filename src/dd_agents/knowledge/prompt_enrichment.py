"""Agent Context Enrichment from Knowledge Base (Issue #184).

Assembles domain-filtered knowledge context for specialist agent prompts.
Each agent receives only the knowledge relevant to its domain — legal agents
see legal clause categories, finance agents see financial categories, etc.

The enricher draws from four knowledge sources:
1. Entity profiles (from the Deal Knowledge Base)
2. Finding lineage highlights (from the FindingLineageTracker)
3. Known contradictions (from the Deal Knowledge Base)
4. Document relationships (from the DealKnowledgeGraph)
5. Prior insights (from the Deal Knowledge Base)

Returns ``None`` when no knowledge base exists (first run) or when the
assembled text is too short to be useful (< 100 chars).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dd_agents.knowledge.base import DealKnowledgeBase
    from dd_agents.knowledge.graph import DealKnowledgeGraph
    from dd_agents.knowledge.lineage import FindingLineageTracker

logger = logging.getLogger(__name__)

# Domain-to-category mapping for filtering knowledge articles to agent domains.
AGENT_DOMAIN_CATEGORIES: dict[str, set[str]] = {
    "legal": {
        "change_of_control",
        "termination",
        "assignment_consent",
        "ip_ownership",
        "non_compete",
        "indemnification",
        "liability_caps",
        "governing_law",
        "dispute_resolution",
        "confidentiality",
    },
    "finance": {
        "payment_terms",
        "pricing",
        "revenue_recognition",
        "financial_commitments",
        "penalties",
        "insurance",
    },
    "commercial": {
        "sla_compliance",
        "renewal_terms",
        "volume_commitments",
        "exclusivity",
        "territory",
        "customer_satisfaction",
    },
    "producttech": {
        "product_scope",
        "technology_stack",
        "integration_requirements",
        "support_obligations",
        "security_posture",
        "migration_complexity",
    },
}

# Sub-budget proportions for max_chars allocation.
_BUDGET_ENTITY_PROFILES = 0.40
_BUDGET_LINEAGE = 0.20
_BUDGET_CONTRADICTIONS = 0.15
_BUDGET_DOC_RELATIONSHIPS = 0.15
_BUDGET_PRIOR_INSIGHTS = 0.10

# Minimum total chars to return (below this, return None).
_MIN_USEFUL_CHARS = 100


def _agent_domain(agent_name: str) -> str | None:
    """Extract domain key from agent name.

    Accepts names like ``"legal"``, ``"LegalAgent"``, ``"finance_agent"``,
    ``"ProductTech"``. Returns the lowercase domain key or ``None`` if
    unrecognised.
    """
    name_lower = agent_name.lower().replace("_agent", "").replace("agent", "").strip("_ ")
    for domain in AGENT_DOMAIN_CATEGORIES:
        if domain in name_lower:
            return domain
    return None


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if needed."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."


class AgentKnowledgeEnricher:
    """Assembles domain-filtered knowledge context for specialist agent prompts.

    Draws from the Deal Knowledge Base, Knowledge Graph, and Finding Lineage
    Tracker to build a context string that is injected into agent prompts.

    Parameters
    ----------
    knowledge_base:
        The deal's knowledge base (may be ``None`` on first run).
    knowledge_graph:
        Optional knowledge graph for document relationship context.
    lineage_tracker:
        Optional finding lineage tracker for cross-run evolution data.
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

    def build_agent_context(
        self,
        agent_name: str,
        customer_safe_names: list[str],
        max_chars: int = 8_000,
    ) -> str | None:
        """Build knowledge context for a specialist agent prompt.

        Returns ``None`` if no knowledge base exists (first run), the agent
        domain is unrecognised, the customer list is empty, or the assembled
        text is shorter than 100 characters.

        Sub-budgets (of *max_chars*):

        1. Entity profiles: 40%
        2. Finding lineage highlights: 20%
        3. Known contradictions: 15%
        4. Document relationships: 15%
        5. Prior insights: 10%

        Parameters
        ----------
        agent_name:
            Agent name (e.g. ``"legal"``, ``"FinanceAgent"``).
        customer_safe_names:
            List of entity safe names to build context for.
        max_chars:
            Maximum total characters for the assembled context.
        """
        if self._kb is None:
            return None

        domain = _agent_domain(agent_name)
        if domain is None:
            return None

        if not customer_safe_names:
            return None

        sections: list[str] = []

        profiles = self._build_entity_profiles(
            agent_name, customer_safe_names, int(max_chars * _BUDGET_ENTITY_PROFILES)
        )
        if profiles:
            sections.append(profiles)

        lineage = self._build_lineage_highlights(agent_name, customer_safe_names, int(max_chars * _BUDGET_LINEAGE))
        if lineage:
            sections.append(lineage)

        contradictions = self._build_contradictions(
            agent_name, customer_safe_names, int(max_chars * _BUDGET_CONTRADICTIONS)
        )
        if contradictions:
            sections.append(contradictions)

        doc_rels = self._build_document_relationships(customer_safe_names, int(max_chars * _BUDGET_DOC_RELATIONSHIPS))
        if doc_rels:
            sections.append(doc_rels)

        insights = self._build_prior_insights(agent_name, customer_safe_names, int(max_chars * _BUDGET_PRIOR_INSIGHTS))
        if insights:
            sections.append(insights)

        if not sections:
            return None

        assembled = "\n\n".join(sections)
        assembled = _truncate(assembled, max_chars)

        if len(assembled) < _MIN_USEFUL_CHARS:
            return None

        return assembled

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_entity_profiles(
        self,
        agent_name: str,
        customer_safe_names: list[str],
        max_chars: int,
    ) -> str:
        """Build entity profile section filtered to agent's domain categories.

        For each customer, looks up the ``entity_{safe_name}`` article and
        extracts severity counts and key clauses filtered to the agent's
        domain.

        Parameters
        ----------
        agent_name:
            Agent name for domain resolution.
        customer_safe_names:
            Entity safe names.
        max_chars:
            Character budget for this section.
        """
        if self._kb is None:
            return ""

        domain = _agent_domain(agent_name)
        if domain is None:
            return ""

        categories = AGENT_DOMAIN_CATEGORIES[domain]
        lines: list[str] = ["=== Entity Profiles ==="]

        for safe_name in customer_safe_names:
            article = self._kb.get_article(f"entity_{safe_name}")
            if article is None:
                continue

            content: dict[str, Any] = article.content
            lines.append(f"\n--- {safe_name} ---")

            # Severity counts
            severity_counts = content.get("severity_counts", {})
            if severity_counts and isinstance(severity_counts, dict):
                parts = [f"{k}: {v}" for k, v in severity_counts.items()]
                lines.append(f"Severity: {', '.join(parts)}")

            # Key clauses filtered to domain
            key_clauses = content.get("key_clauses", [])
            if isinstance(key_clauses, list):
                filtered = [
                    c for c in key_clauses if isinstance(c, dict) and str(c.get("category", "")).lower() in categories
                ]
                if filtered:
                    lines.append(f"Key clauses ({domain}):")
                    for clause in filtered:
                        title = clause.get("title", clause.get("category", ""))
                        severity = clause.get("severity", "")
                        sev_str = f" [{severity}]" if severity else ""
                        lines.append(f"  - {title}{sev_str}")

        text = "\n".join(lines)
        return _truncate(text, max_chars)

    def _build_lineage_highlights(
        self,
        agent_name: str,
        customer_safe_names: list[str],
        max_chars: int,
    ) -> str:
        """Build lineage highlights: persistent findings and severity changes.

        Filters findings to the agent's domain by matching finding categories
        against the domain's category set.

        Parameters
        ----------
        agent_name:
            Agent name for domain resolution.
        customer_safe_names:
            Entity safe names.
        max_chars:
            Character budget for this section.
        """
        if self._lineage is None:
            return ""

        domain = _agent_domain(agent_name)
        if domain is None:
            return ""

        categories = AGENT_DOMAIN_CATEGORIES[domain]
        lines: list[str] = ["=== Finding Lineage ==="]

        for safe_name in customer_safe_names:
            entity_lineage = self._lineage.get_entity_lineage(safe_name)
            if not entity_lineage:
                continue

            # Filter to domain
            domain_lineage = [e for e in entity_lineage if e.category.lower() in categories]
            if not domain_lineage:
                continue

            lines.append(f"\n--- {safe_name} ---")

            # Persistent findings (3+ runs)
            persistent = [e for e in domain_lineage if e.run_count >= 3]
            if persistent:
                lines.append("Persistent findings (3+ runs):")
                for entry in persistent[:5]:
                    lines.append(f"  - [{entry.current_severity}] {entry.latest_title} ({entry.run_count} runs)")

            # Severity changes
            sev_changed = [e for e in domain_lineage if e.severity_history]
            if sev_changed:
                lines.append("Severity changes:")
                for entry in sev_changed[:5]:
                    last_ev = entry.severity_history[-1]
                    lines.append(f"  - {entry.latest_title}: {last_ev.old_severity} -> {last_ev.new_severity}")

        text = "\n".join(lines)
        if text == "=== Finding Lineage ===":
            return ""
        return _truncate(text, max_chars)

    def _build_contradictions(
        self,
        agent_name: str,
        customer_safe_names: list[str],
        max_chars: int,
    ) -> str:
        """Build contradictions section filtered to agent domain and customers.

        Searches the knowledge base for contradiction articles where any
        customer is in tags AND the category matches the agent's domain.

        Parameters
        ----------
        agent_name:
            Agent name for domain resolution.
        customer_safe_names:
            Entity safe names.
        max_chars:
            Character budget for this section.
        """
        if self._kb is None:
            return ""

        domain = _agent_domain(agent_name)
        if domain is None:
            return ""

        from dd_agents.knowledge.articles import ArticleType

        categories = AGENT_DOMAIN_CATEGORIES[domain]
        lines: list[str] = ["=== Known Contradictions ==="]

        all_contradictions = self._kb.list_articles(ArticleType.CONTRADICTION)
        customer_set = set(customer_safe_names)

        for article in all_contradictions:
            if article.superseded_by:
                continue

            # Check customer tag match
            has_customer = any(tag in customer_set for tag in article.tags)
            if not has_customer:
                continue

            # Check domain category match
            article_category = article.content.get("category", "")
            article_categories = article.content.get("categories", [])
            all_cats: set[str] = set()
            if article_category:
                all_cats.add(str(article_category).lower())
            if isinstance(article_categories, list):
                all_cats.update(str(c).lower() for c in article_categories)
            # Also check tags for category matches
            all_cats.update(t.lower() for t in article.tags if t.lower() in categories)

            if not all_cats.intersection(categories):
                continue

            lines.append(f"- {article.title}")
            description = article.content.get("description", "")
            if description:
                lines.append(f"  {description}")

        text = "\n".join(lines)
        if text == "=== Known Contradictions ===":
            return ""
        return _truncate(text, max_chars)

    def _build_document_relationships(
        self,
        customer_safe_names: list[str],
        max_chars: int,
    ) -> str:
        """Build document relationship section from the knowledge graph.

        For each customer, calls ``get_entity_context()`` with a per-entity
        character budget of ``max_chars / len(customers)``.

        Parameters
        ----------
        customer_safe_names:
            Entity safe names.
        max_chars:
            Character budget for this section.
        """
        if self._graph is None:
            return ""

        if not customer_safe_names:
            return ""

        per_entity = max(100, max_chars // len(customer_safe_names))
        lines: list[str] = ["=== Document Relationships ==="]

        for safe_name in customer_safe_names:
            context = self._graph.get_entity_context(safe_name, max_chars=per_entity)
            if context and not context.startswith("No graph data"):
                lines.append(context)

        text = "\n".join(lines)
        if text == "=== Document Relationships ===":
            return ""
        return _truncate(text, max_chars)

    def _build_prior_insights(
        self,
        agent_name: str,
        customer_safe_names: list[str],
        max_chars: int,
    ) -> str:
        """Build prior insights section filtered by domain and customer tags.

        Searches the knowledge base for insight articles tagged with any
        customer AND the agent's domain categories.

        Parameters
        ----------
        agent_name:
            Agent name for domain resolution.
        customer_safe_names:
            Entity safe names.
        max_chars:
            Character budget for this section.
        """
        if self._kb is None:
            return ""

        domain = _agent_domain(agent_name)
        if domain is None:
            return ""

        from dd_agents.knowledge.articles import ArticleType

        categories = AGENT_DOMAIN_CATEGORIES[domain]
        customer_set = set(customer_safe_names)
        lines: list[str] = ["=== Prior Insights ==="]

        all_insights = self._kb.list_articles(ArticleType.INSIGHT)

        for article in all_insights:
            if article.superseded_by:
                continue

            # Must be tagged with at least one customer
            has_customer = any(tag in customer_set for tag in article.tags)
            if not has_customer:
                continue

            # Must match domain via tags or content category
            tag_set = {t.lower() for t in article.tags}
            content_category = str(article.content.get("category", "")).lower()

            domain_match = bool(tag_set.intersection(categories)) or content_category in categories
            # Also accept if the domain name itself is in tags
            if not domain_match and domain in tag_set:
                domain_match = True

            if not domain_match:
                continue

            lines.append(f"- {article.title}")
            description = article.content.get("description", "")
            if description:
                lines.append(f"  {description}")

        text = "\n".join(lines)
        if text == "=== Prior Insights ===":
            return ""
        return _truncate(text, max_chars)
