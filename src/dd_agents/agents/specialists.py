"""Specialist agent runners — 9 domain specialists for forensic M&A due diligence.

Core specialists: Legal, Finance, Commercial, ProductTech, Cybersecurity.
Extended specialists: HR, Tax, Regulatory, ESG.

Each specialist analyses ALL subjects through its domain-specific lens.
Specialists run in parallel during pipeline step 16.

Domain-specific LLM robustness mitigations (Issue #52, spec doc 22) are
appended to each specialist's system prompt via ``_domain_robustness()``
class methods.
"""

from __future__ import annotations

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.prompt_builder import (
    AgentType,
)
from dd_agents.agents.prompt_constants import (
    SEVERITY_PREAMBLE,
)
from dd_agents.agents.prompts.loader import load_builtin_specialist

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
    "regulatory_compliance",
    "legal_entity",
    "contract_timeline",
    "key_person_dependency",
    "employment_agreements",
    "retention_risk",
    "non_compete_enforcement",
    "ip_portfolio_strength",
    "freedom_to_operate",
]

FINANCE_FOCUS_AREAS: list[str] = [
    "payment_terms",
    "pricing",
    "revenue_recognition",
    "financial_commitments",
    "penalties",
    "insurance",
    "revenue_composition",
    "unit_economics",
    "financial_projections",
    "cost_structure",
    "insurance_program",
]

COMMERCIAL_FOCUS_AREAS: list[str] = [
    "sla_compliance",
    "renewal_terms",
    "volume_commitments",
    "exclusivity",
    "territory",
    "customer_satisfaction",
    "customer_segmentation",
    "pricing_model",
    "expansion_contraction",
    "competitive_positioning",
    "supply_chain_risk",
    "operational_capacity",
]

PRODUCTTECH_FOCUS_AREAS: list[str] = [
    "product_scope",
    "technology_stack",
    "integration_requirements",
    "support_obligations",
    "documentation",
    "training",
    # Issue #132: Technology Stack Assessment & Technical Debt
    "technical_debt",
    "security_posture",
    "scalability",
    "migration_complexity",
    "architecture_risk",
]

CYBERSECURITY_FOCUS_AREAS: list[str] = [
    "data_breach_history",
    "access_controls",
    "encryption_standards",
    "incident_response",
    "vulnerability_management",
    "network_security",
    "compliance_certifications",
    "third_party_risk",
]

HR_FOCUS_AREAS: list[str] = [
    "workforce_composition",
    "compensation_analysis",
    "benefits_liabilities",
    "key_talent_retention",
    "organizational_structure",
    "labor_compliance",
    "union_collective_bargaining",
    "culture_integration",
    "succession_planning",
    "workforce_classification",
]

TAX_FOCUS_AREAS: list[str] = [
    "income_tax_compliance",
    "transfer_pricing",
    "nol_tax_attributes",
    "sales_use_tax",
    "international_tax",
    "deal_structure_tax",
    "tax_provisions",
    "tax_controversy",
    "employee_tax",
    "indirect_tax",
]

REGULATORY_FOCUS_AREAS: list[str] = [
    "license_transferability",
    "antitrust_competition",
    "data_privacy_regulation",
    "financial_regulation",
    "healthcare_regulation",
    "aml_sanctions",
    "government_contracts",
    "environmental_regulation",
    "consumer_protection",
    "industry_specific",
]

ESG_FOCUS_AREAS: list[str] = [
    "environmental_contamination",
    "environmental_permits",
    "climate_carbon_risk",
    "hazardous_materials",
    "supply_chain_sustainability",
    "esg_governance",
    "social_impact",
    "esg_disclosure",
    "biodiversity_land_use",
    "circular_economy",
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
    "get_subject_files",
    "search_similar",
    "read_office",
    "report_progress",
    "search_in_file",
    "get_page_content",
    "batch_verify_citations",
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
        return load_builtin_specialist("legal").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("legal").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class FinanceAgent(BaseAgentRunner):
    """Finance specialist -- pricing, revenue, financial reconciliation."""

    focus_areas: list[str] = FINANCE_FOCUS_AREAS

    reference_categories: list[str] = ["financial", "pricing"]

    # Finance batches are smaller because financial documents are dense
    # and context exhaustion degrades citation quality (Issue #92).
    # Reduced from 10/25K to 7/20K after production runs showed finance
    # consistently exceeding soft limits (200→270 turns).
    max_subjects_per_batch: int = 7
    max_tokens_per_batch: int = 20_000

    def get_agent_name(self) -> str:
        return "finance"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("finance").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("finance").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class CommercialAgent(BaseAgentRunner):
    """Commercial specialist -- renewal terms, SLA, churn risk."""

    focus_areas: list[str] = COMMERCIAL_FOCUS_AREAS

    reference_categories: list[str] = ["pricing", "sales", "operational"]

    def get_agent_name(self) -> str:
        return "commercial"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("commercial").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("commercial").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class ProductTechAgent(BaseAgentRunner):
    """ProductTech specialist -- technical risk, DPA, security compliance."""

    # ProductTech documents (SOC 2 reports, DPAs, pen test reports,
    # architecture docs) are dense and citation-heavy.  Reduced from
    # default 20/40K to match Finance's proven configuration after
    # production runs showed context exhaustion degrading citation
    # quality when all subjects are packed in a single batch.
    max_subjects_per_batch: int = 7
    max_tokens_per_batch: int = 20_000

    focus_areas: list[str] = PRODUCTTECH_FOCUS_AREAS

    reference_categories: list[str] = ["operational", "compliance"]

    def get_agent_name(self) -> str:
        return "producttech"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("producttech").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("producttech").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class CybersecurityAgent(BaseAgentRunner):
    """Cybersecurity specialist -- security posture, breach history, compliance."""

    focus_areas: list[str] = CYBERSECURITY_FOCUS_AREAS

    reference_categories: list[str] = ["compliance", "operational"]

    # Cybersecurity documents (pentest reports, SOC 2, incident logs) are
    # dense and citation-heavy, similar to ProductTech.
    max_subjects_per_batch: int = 15
    max_tokens_per_batch: int = 30_000

    def get_agent_name(self) -> str:
        return "cybersecurity"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("cybersecurity").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("cybersecurity").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class HRAgent(BaseAgentRunner):
    """HR / People specialist — workforce composition, talent retention, labor compliance."""

    focus_areas: list[str] = HR_FOCUS_AREAS

    reference_categories: list[str] = ["hr", "compliance"]

    def get_agent_name(self) -> str:
        return "hr"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("hr").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("hr").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class TaxAgent(BaseAgentRunner):
    """Tax specialist — income tax, transfer pricing, NOLs, deal structure tax."""

    focus_areas: list[str] = TAX_FOCUS_AREAS

    reference_categories: list[str] = ["financial", "compliance"]

    max_subjects_per_batch: int = 7
    max_tokens_per_batch: int = 20_000

    def get_agent_name(self) -> str:
        return "tax"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("tax").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("tax").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class RegulatoryAgent(BaseAgentRunner):
    """Regulatory specialist — licenses, antitrust, sector-specific compliance."""

    focus_areas: list[str] = REGULATORY_FOCUS_AREAS

    reference_categories: list[str] = ["compliance", "corporate_legal"]

    def get_agent_name(self) -> str:
        return "regulatory"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("regulatory").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("regulatory").domain_guidance

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class ESGAgent(BaseAgentRunner):
    """ESG specialist — environmental contamination, climate risk, ESG governance."""

    focus_areas: list[str] = ESG_FOCUS_AREAS

    reference_categories: list[str] = ["compliance", "operational"]

    def get_agent_name(self) -> str:
        return "esg"

    def get_system_prompt(self) -> str:
        return load_builtin_specialist("esg").role + " " + SEVERITY_PREAMBLE

    @staticmethod
    def domain_robustness() -> str:
        return load_builtin_specialist("esg").domain_guidance

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
    AgentType.CYBERSECURITY,
    AgentType.HR,
    AgentType.TAX,
    AgentType.REGULATORY,
    AgentType.ESG,
]

SPECIALIST_CLASSES: dict[AgentType, type[BaseAgentRunner]] = {
    AgentType.LEGAL: LegalAgent,
    AgentType.FINANCE: FinanceAgent,
    AgentType.COMMERCIAL: CommercialAgent,
    AgentType.PRODUCTTECH: ProductTechAgent,
    AgentType.CYBERSECURITY: CybersecurityAgent,
    AgentType.HR: HRAgent,
    AgentType.TAX: TaxAgent,
    AgentType.REGULATORY: RegulatoryAgent,
    AgentType.ESG: ESGAgent,
}


# ---------------------------------------------------------------------------
# Self-register built-in agents with the AgentRegistry
# ---------------------------------------------------------------------------


def _register_builtins() -> None:
    """Register the 9 built-in specialist agents with the AgentRegistry."""
    from dd_agents.agents.descriptor import DEFAULT_AGENT_COLORS, AgentDescriptor
    from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS
    from dd_agents.agents.prompt_constants import build_citation_mandate
    from dd_agents.agents.registry import AgentRegistry

    agents_to_register: list[tuple[str, str, type[BaseAgentRunner], list[str], list[str], int, int]] = [
        ("legal", "Legal", LegalAgent, LEGAL_FOCUS_AREAS, ["corporate_legal", "compliance"], 20, 40_000),
        ("finance", "Finance", FinanceAgent, FINANCE_FOCUS_AREAS, ["financial", "pricing"], 7, 20_000),
        (
            "commercial",
            "Commercial",
            CommercialAgent,
            COMMERCIAL_FOCUS_AREAS,
            ["pricing", "sales", "operational"],
            20,
            40_000,
        ),
        (
            "producttech",
            "Product & Tech",
            ProductTechAgent,
            PRODUCTTECH_FOCUS_AREAS,
            ["operational", "compliance"],
            7,
            20_000,
        ),
        (
            "cybersecurity",
            "Cybersecurity",
            CybersecurityAgent,
            CYBERSECURITY_FOCUS_AREAS,
            ["compliance", "operational"],
            15,
            30_000,
        ),
        ("hr", "HR / People", HRAgent, HR_FOCUS_AREAS, ["hr", "compliance"], 20, 40_000),
        ("tax", "Tax", TaxAgent, TAX_FOCUS_AREAS, ["financial", "compliance"], 7, 20_000),
        (
            "regulatory",
            "Regulatory",
            RegulatoryAgent,
            REGULATORY_FOCUS_AREAS,
            ["compliance", "corporate_legal"],
            20,
            40_000,
        ),
        ("esg", "ESG", ESGAgent, ESG_FOCUS_AREAS, ["compliance", "operational"], 20, 40_000),
    ]

    for name, display, cls, areas, ref_cats, batch_size, batch_tokens in agents_to_register:
        agent_type = AgentType(name)
        AgentRegistry.register(
            AgentDescriptor(
                name=name,
                display_name=display,
                color=DEFAULT_AGENT_COLORS.get(name, "#666666"),
                focus_areas=tuple(areas),
                reference_categories=tuple(ref_cats),
                agent_class=cls,
                specialist_focus=SPECIALIST_FOCUS.get(agent_type, ""),
                citation_examples=build_citation_mandate(name),
                max_subjects_per_batch=batch_size,
                max_tokens_per_batch=batch_tokens,
                domain_robustness=cls.domain_robustness() if hasattr(cls, "domain_robustness") else "",
            )
        )
