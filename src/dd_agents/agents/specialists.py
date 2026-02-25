"""Specialist agent runners -- Legal, Finance, Commercial, ProductTech.

Each specialist analyses ALL customers through its domain-specific lens.
Specialists run in parallel during pipeline step 16.
"""

from __future__ import annotations

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import (
    AgentType,
)

# ---------------------------------------------------------------------------
# Focus area constants per specialist
# ---------------------------------------------------------------------------

LEGAL_FOCUS_AREAS: list[str] = [
    "change_of_control",
    "assignment_consent",
    "termination",
    "non_compete",
    "ip_ownership",
    "data_privacy",
    "indemnification",
    "liability_caps",
    "warranty",
    "dispute_resolution",
]

FINANCE_FOCUS_AREAS: list[str] = [
    "payment_terms",
    "pricing",
    "revenue_recognition",
    "financial_commitments",
    "penalties",
    "insurance",
]

COMMERCIAL_FOCUS_AREAS: list[str] = [
    "sla_compliance",
    "renewal_terms",
    "volume_commitments",
    "exclusivity",
    "territory",
    "customer_satisfaction",
]

PRODUCTTECH_FOCUS_AREAS: list[str] = [
    "product_scope",
    "technology_stack",
    "integration_requirements",
    "support_obligations",
    "documentation",
    "training",
]

# ---------------------------------------------------------------------------
# Shared tool list for all specialist agents
# ---------------------------------------------------------------------------

SPECIALIST_TOOLS: list[str] = [
    "Read",
    "Write",
    "Glob",
    "Grep",
    "validate_finding",
    "validate_gap",
    "verify_citation",
    "resolve_entity",
    "get_customer_files",
    "report_progress",
]


# ---------------------------------------------------------------------------
# Specialist agent classes
# ---------------------------------------------------------------------------


class LegalAgent(BaseAgentRunner):
    """Legal specialist -- governance, risk clauses, entity validation."""

    focus_areas: list[str] = LEGAL_FOCUS_AREAS

    # Preferred reference file categories
    reference_categories: list[str] = ["corporate_legal", "compliance"]

    def get_agent_name(self) -> str:
        return "legal"

    def get_system_prompt(self) -> str:
        return (
            "You are the Legal specialist agent for forensic M&A due diligence. "
            "Focus on governance graphs, change-of-control clauses, assignment "
            "restrictions, termination rights, IP ownership, data privacy, "
            "indemnification, liability caps, warranties, and dispute resolution."
        )

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class FinanceAgent(BaseAgentRunner):
    """Finance specialist -- pricing, revenue, financial reconciliation."""

    focus_areas: list[str] = FINANCE_FOCUS_AREAS

    reference_categories: list[str] = ["financial", "pricing"]

    def get_agent_name(self) -> str:
        return "finance"

    def get_system_prompt(self) -> str:
        return (
            "You are the Finance specialist agent for forensic M&A due diligence. "
            "Focus on payment terms, pricing compliance, revenue recognition, "
            "financial commitments, penalties, and insurance requirements."
        )

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class CommercialAgent(BaseAgentRunner):
    """Commercial specialist -- renewal terms, SLA, churn risk."""

    focus_areas: list[str] = COMMERCIAL_FOCUS_AREAS

    reference_categories: list[str] = ["pricing", "sales", "operational"]

    def get_agent_name(self) -> str:
        return "commercial"

    def get_system_prompt(self) -> str:
        return (
            "You are the Commercial specialist agent for forensic M&A due diligence. "
            "Focus on SLA compliance, renewal terms, volume commitments, "
            "exclusivity, territory restrictions, and customer satisfaction."
        )

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class ProductTechAgent(BaseAgentRunner):
    """ProductTech specialist -- technical risk, DPA, security compliance."""

    focus_areas: list[str] = PRODUCTTECH_FOCUS_AREAS

    reference_categories: list[str] = ["operational", "compliance"]

    def get_agent_name(self) -> str:
        return "producttech"

    def get_system_prompt(self) -> str:
        return (
            "You are the ProductTech specialist agent for forensic M&A due diligence. "
            "Focus on product scope, technology stack, integration requirements, "
            "support obligations, documentation, and training requirements."
        )

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


# ---------------------------------------------------------------------------
# Registry for convenient iteration
# ---------------------------------------------------------------------------

SPECIALIST_TYPES: list[AgentType] = [
    AgentType.LEGAL,
    AgentType.FINANCE,
    AgentType.COMMERCIAL,
    AgentType.PRODUCTTECH,
]

SPECIALIST_CLASSES: dict[AgentType, type[BaseAgentRunner]] = {
    AgentType.LEGAL: LegalAgent,
    AgentType.FINANCE: FinanceAgent,
    AgentType.COMMERCIAL: CommercialAgent,
    AgentType.PRODUCTTECH: ProductTechAgent,
}
