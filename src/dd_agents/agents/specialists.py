"""Specialist agent runners -- Legal, Finance, Commercial, ProductTech.

Each specialist analyses ALL customers through its domain-specific lens.
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
    # Issue #131: Key Employee & Organizational Risk
    "key_person_dependency",
    "employment_agreements",
    "retention_risk",
    "non_compete_enforcement",
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
    "read_office",
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
            "indemnification, liability caps, warranties, and dispute resolution. "
            "Calibrate severity carefully: P0 is reserved for genuine deal-stoppers. "
            "Most findings are P2 or P3. Accuracy over volume."
        )

    @staticmethod
    def domain_robustness() -> str:
        """Legal-specific robustness mitigations (AG-7: high-difficulty provisions)."""
        return (
            "## LEGAL-SPECIFIC EXTRACTION GUIDANCE\n\n"
            #
            "### Change of Control (AG F1: 0.82 -- HIGH difficulty)\n\n"
            "DEFINITION: A clause triggered when ownership or control of a party "
            "changes, typically through acquisition, merger, or transfer of voting power.\n"
            "KEYWORDS: change of control, acquisition, merger, transfer of ownership, "
            "voting control, controlling interest, beneficial ownership, successor\n"
            "COMMON FORMULATIONS:\n"
            "- 'In the event of a Change of Control of [Party]...'\n"
            "- Sometimes embedded in termination or assignment clauses\n"
            "- May use 'change in management' or 'change in beneficial ownership'\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            "COC SUBTYPE CLASSIFICATION — classify each CoC clause as one of:\n"
            "1. **notification-only**: Party must notify counterparty of CoC. "
            "Routine administrative step, no consent needed.\n"
            "2. **consent-required**: Assignment or continuation requires prior written "
            "consent from counterparty. Assess cure period and revenue at risk.\n"
            "3. **termination-right**: Counterparty gains a right (but not obligation) to "
            "terminate upon CoC. Assess notice period and cure window.\n"
            "4. **auto-termination**: Contract automatically terminates upon CoC with "
            "no cure. Most severe subtype.\n"
            "5. **competitor-only**: Termination or restriction triggered ONLY if the "
            "acquirer is a competitor of the counterparty. In most acquisitions, the buyer "
            "is NOT a competitor to the target's customers. Competitor-only CoC = P3 unless "
            "deal config shows the buyer operates in the same market as a significant "
            "customer.\n\n"
            "For each CoC finding, your description MUST include:\n"
            "- The CoC subtype (one of the 5 above)\n"
            "- Which party holds the right (counterparty or mutual)\n"
            "- Cure period / negotiation window (if any)\n"
            "- Revenue impact estimate (if determinable)\n\n"
            #
            "### Anti-Assignment (AG F1: 0.88 -- MEDIUM-HIGH difficulty)\n\n"
            "DEFINITION: A clause restricting either party from assigning or "
            "transferring rights or obligations under the agreement without consent.\n"
            "KEYWORDS: assignment, transfer, delegate, successor, assign rights, "
            "consent required, written consent, non-assignable\n"
            "COMMON FORMULATIONS:\n"
            "- 'Neither party may assign this Agreement without prior written consent'\n"
            "- 'This Agreement shall be binding upon successors and permitted assigns'\n"
            "- May have carve-outs for affiliates or corporate reorganizations\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            #
            "### Termination Clauses — Subtype Classification\n\n"
            "Classify each termination clause as one of:\n"
            "- **TfCause (Termination for Cause)**: Triggered by material breach, "
            "insolvency, or specific default events. Standard mutual TfCause with "
            "reasonable cure period = P3. Broad or subjective 'cause' definition = P1.\n"
            "- **TfC (Termination for Convenience)**: Either party may terminate "
            "without cause, typically with a notice period. TfC is NOT a deal-breaker — "
            "it is a valuation/revenue-quality concern. TfC alone = P2. Escalate to P1 "
            "ONLY if: TfC + >10% revenue + <90 day notice period. NEVER flag TfC as P0.\n"
            "- **Termination on CoC**: Termination right triggered by change of control. "
            "Classify under CoC subtypes above, not here.\n"
            "- **Termination on Insolvency**: Triggered by bankruptcy or insolvency. "
            "Standard protective clause = P3.\n"
            "- **Mutual vs Unilateral**: Note whether termination right is mutual or "
            "held by one party only. Unilateral TfC held by counterparty = higher risk.\n\n"
            "For each termination finding, extract:\n"
            "- Termination subtype\n"
            "- Notice period required\n"
            "- Early termination fees or refund provisions\n"
            "- Which party holds the right\n"
            "- Cure period (for TfCause)\n\n"
            #
            "### Cap on Liability (AG F1: 0.67 -- VERY HIGH difficulty)\n\n"
            "DEFINITION: A contractual clause limiting the maximum aggregate liability "
            "of one or both parties, typically expressed as a fixed dollar amount, "
            "a multiple of fees paid, or 'direct damages only'.\n"
            "WHAT TO EXTRACT:\n"
            "- The cap amount (absolute $ or formula)\n"
            "- Which parties are capped\n"
            "- What is excluded from the cap (IP indemnity, confidentiality breach, "
            "willful misconduct)\n"
            "- Whether the cap is mutual or asymmetric\n"
            "KEYWORDS: liability cap, limitation of liability, aggregate liability, "
            "maximum liability, direct damages, consequential damages, exclusion of "
            "liability, cap on damages, total liability shall not exceed\n"
            "COMMON FORMULATIONS:\n"
            "- 'In no event shall [Party]'s aggregate liability exceed [amount]'\n"
            "- 'The total liability of either party shall be limited to [formula]'\n"
            "- Sometimes embedded in indemnification clauses, not a standalone section\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'. Do NOT fabricate "
            "a liability cap that does not exist.\n\n"
            #
            "### Exclusivity (AG F1: 0.86 -- HIGH difficulty)\n\n"
            "DEFINITION: A clause granting one party exclusive rights within a "
            "defined scope (territory, product line, customer segment).\n"
            "KEYWORDS: exclusive, exclusivity, sole provider, sole supplier, "
            "exclusive license, non-exclusive, exclusive distribution, exclusive right\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'."
        )

    def get_tools(self) -> list[str]:
        return list(SPECIALIST_TOOLS)


class FinanceAgent(BaseAgentRunner):
    """Finance specialist -- pricing, revenue, financial reconciliation."""

    focus_areas: list[str] = FINANCE_FOCUS_AREAS

    reference_categories: list[str] = ["financial", "pricing"]

    # Finance batches are smaller because financial documents are dense
    # and context exhaustion degrades citation quality (Issue #92).
    max_customers_per_batch: int = 10
    max_tokens_per_batch: int = 25_000

    def get_agent_name(self) -> str:
        return "finance"

    def get_system_prompt(self) -> str:
        return (
            "You are the Finance specialist agent for forensic M&A due diligence. "
            "Focus on payment terms, pricing compliance, revenue recognition, "
            "financial commitments, penalties, and insurance requirements. "
            "Calibrate severity carefully: P0 is reserved for genuine deal-stoppers. "
            "Most findings are P2 or P3. Accuracy over volume."
        )

    @staticmethod
    def domain_robustness() -> str:
        """Finance-specific robustness mitigations (E-1 through E-4, AG-7)."""
        return (
            "## FINANCE-SPECIFIC EXTRACTION GUIDANCE\n\n"
            #
            "### Cap on Liability (AG F1: 0.67 -- VERY HIGH difficulty)\n\n"
            "DEFINITION: A contractual clause limiting the maximum aggregate liability.\n"
            "When found, extract: cap amount (absolute $ or formula), which parties "
            "are capped, exclusions from the cap, mutual vs asymmetric.\n"
            "KEYWORDS: liability cap, limitation of liability, aggregate liability, "
            "maximum liability, direct damages, total liability shall not exceed\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            #
            "### Insurance (AG F1: 0.98 -- LOW difficulty)\n\n"
            "KEYWORDS: insurance, indemnity insurance, professional liability, "
            "errors and omissions, cyber insurance, policy limits\n\n"
            #
            "### Financial Data Handling\n\n"
            "- Excel date serial numbers (e.g. 44621) should be treated as "
            "ISO-8601 dates. If you see a 5-digit integer in a date column, "
            "it is likely an Excel date serial.\n"
            "- ALWAYS verify currency units. '$120' could be $120 or $120,000 "
            "depending on column headers. Include the column header context "
            "in your citation.\n"
            "- For large spreadsheets (>100 rows), process in chunks of 50 rows. "
            "Read header + first 10 rows to understand structure first.\n"
            "- When cross-referencing contract values against reference data, "
            "cite BOTH the contract clause AND the spreadsheet cell/row.\n"
            "- Normalize all currency values to full units (not thousands) before "
            "comparison."
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
            "exclusivity, territory restrictions, and customer satisfaction. "
            "Calibrate severity carefully: P0 is reserved for genuine deal-stoppers. "
            "Most findings are P2 or P3. Accuracy over volume."
        )

    @staticmethod
    def domain_robustness() -> str:
        """Commercial-specific robustness mitigations (AG-7: medium-high provisions)."""
        return (
            "## COMMERCIAL-SPECIFIC EXTRACTION GUIDANCE\n\n"
            #
            "### Most Favored Nation (AG F1: 0.90 -- MEDIUM-HIGH difficulty)\n\n"
            "DEFINITION: A clause guaranteeing one party pricing or terms at least "
            "as favorable as those offered to any other customer.\n"
            "KEYWORDS: most favored nation, MFN, most favored customer, best price, "
            "price parity, most favorable terms, price protection\n"
            "COMMON FORMULATIONS:\n"
            "- 'Supplier shall ensure that pricing is no less favorable than...'\n"
            "- 'Customer shall receive the benefit of any more favorable terms...'\n"
            "- May appear in pricing schedules or appendices rather than main body\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            #
            "### Exclusivity (AG F1: 0.86 -- HIGH difficulty)\n\n"
            "DEFINITION: A clause granting one party exclusive rights within a scope.\n"
            "KEYWORDS: exclusive, exclusivity, sole provider, sole supplier, "
            "exclusive license, non-exclusive, exclusive right\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            #
            "### Termination for Convenience (AG F1: 0.93 -- MEDIUM difficulty)\n\n"
            "DEFINITION: A clause allowing either party to terminate the agreement "
            "without cause, typically with a notice period.\n"
            "KEYWORDS: termination for convenience, terminate without cause, "
            "terminate at will, right to terminate, notice period, termination notice\n"
            "WHAT TO EXTRACT:\n"
            "- Which parties can terminate for convenience\n"
            "- Notice period required\n"
            "- Financial consequences (early termination fees, refunds)\n"
            "- Whether TfC survives through a change of control\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'.\n\n"
            "CRITICAL TfC VALUATION GUIDANCE:\n"
            "TfC is NOT a deal-breaker — it is a valuation/revenue quality signal. "
            "Revenue from TfC contracts is non-committed ('at-risk ARR') with lower "
            "certainty than locked-in contracts. TfC affects RPO calculations and "
            "revenue recognition (ASC 606). Report TfC findings as P2 valuation "
            "concerns. Escalate to P1 ONLY if: TfC + >10% revenue + <90 day notice. "
            "NEVER flag TfC as P0."
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
            "support obligations, documentation, and training requirements. "
            "Calibrate severity carefully: P0 is reserved for genuine deal-stoppers. "
            "Most findings are P2 or P3. Accuracy over volume."
        )

    @staticmethod
    def domain_robustness() -> str:
        """ProductTech-specific robustness mitigations.

        Note: No provisions from the AG study fall under ProductTech.
        Guidance focuses on DPA/security-specific extraction.
        """
        return (
            "## PRODUCTTECH-SPECIFIC EXTRACTION GUIDANCE\n\n"
            #
            "### Data Processing Agreements (DPA)\n\n"
            "KEYWORDS: data processing agreement, DPA, data controller, data processor, "
            "subprocessor, personal data, GDPR, data protection, data subject rights, "
            "cross-border transfer, standard contractual clauses, SCCs\n"
            "WHAT TO EXTRACT:\n"
            "- Controller vs processor designation for each party\n"
            "- Subprocessor list and notification obligations\n"
            "- Data residency / cross-border transfer mechanisms\n"
            "- Data breach notification timeframes\n"
            "- Data retention and deletion obligations\n"
            "IF NOT FOUND: Write a gap with gap_type 'Not_Found'. Missing DPAs "
            "are a material compliance risk.\n\n"
            #
            "### Security and Compliance Evidence\n\n"
            "KEYWORDS: SOC 2, SOC2, ISO 27001, penetration test, vulnerability scan, "
            "security audit, compliance certification, encryption, access control\n"
            "WHAT TO EXTRACT:\n"
            "- Security certifications claimed and their validity dates\n"
            "- Audit report references and scope\n"
            "- Encryption standards (at rest, in transit)\n"
            "- Incident response SLAs\n"
            "IF NOT FOUND: Write a gap. Do NOT assume security standards are met "
            "without documentary evidence."
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
