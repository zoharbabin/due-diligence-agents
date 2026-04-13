"""Specialist agent runners -- Legal, Finance, Commercial, ProductTech.

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
    GAP_NOT_FOUND,
    SEVERITY_PREAMBLE,
    TFC_SEVERITY_RULE,
    build_citation_mandate,
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
        return (
            "You are the Legal specialist agent for forensic M&A due diligence. "
            "Focus on governance graphs, change-of-control clauses, assignment "
            "restrictions, termination rights, IP ownership, data privacy, "
            "indemnification, liability caps, warranties, and dispute resolution. " + SEVERITY_PREAMBLE
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
            f"{GAP_NOT_FOUND}\n\n"
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
            f"{GAP_NOT_FOUND}\n\n"
            #
            "### Termination Clauses — Subtype Classification\n\n"
            "Classify each termination clause as one of:\n"
            "- **TfCause (Termination for Cause)**: Triggered by material breach, "
            "insolvency, or specific default events. Standard mutual TfCause with "
            "reasonable cure period = P3. Broad or subjective 'cause' definition = P1.\n"
            "- **TfC (Termination for Convenience)**: Either party may terminate "
            "without cause, typically with a notice period. " + TFC_SEVERITY_RULE + "\n"
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
            f"{GAP_NOT_FOUND} Do NOT fabricate "
            "a liability cap that does not exist.\n\n"
            #
            "### Exclusivity (AG F1: 0.86 -- HIGH difficulty)\n\n"
            "DEFINITION: A clause granting one party exclusive rights within a "
            "defined scope (territory, product line, customer segment).\n"
            "KEYWORDS: exclusive, exclusivity, sole provider, sole supplier, "
            "exclusive license, non-exclusive, exclusive distribution, exclusive right\n"
            f"{GAP_NOT_FOUND}\n\n" + build_citation_mandate("legal")
        )

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
        return (
            "You are the Finance specialist agent for forensic M&A due diligence. "
            "Focus on payment terms, pricing compliance, revenue recognition, "
            "financial commitments, penalties, and insurance requirements. " + SEVERITY_PREAMBLE
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
            f"{GAP_NOT_FOUND}\n\n"
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
            "comparison.\n\n" + build_citation_mandate("finance")
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
            "exclusivity, territory restrictions, and customer satisfaction. " + SEVERITY_PREAMBLE
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
            f"{GAP_NOT_FOUND}\n\n"
            #
            "### Exclusivity (AG F1: 0.86 -- HIGH difficulty)\n\n"
            "DEFINITION: A clause granting one party exclusive rights within a scope.\n"
            "KEYWORDS: exclusive, exclusivity, sole provider, sole supplier, "
            "exclusive license, non-exclusive, exclusive right\n"
            f"{GAP_NOT_FOUND}\n\n"
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
            f"{GAP_NOT_FOUND}\n\n"
            "CRITICAL TfC VALUATION GUIDANCE:\n" + TFC_SEVERITY_RULE + "\n\n"
            #
            "### Commercial Citation Enforcement\n\n"
            "For each contract clause finding, cite the specific contract file and "
            "section/clause number. For pricing findings, cite the rate card or "
            "contract schedule with the exact pricing language. For renewal or "
            "termination findings, cite the renewal clause with exact quoted language "
            "including notice periods and dates. For customer concentration findings, "
            "cite the revenue data source document (spreadsheet tab, row, cell value). "
            "If a finding cannot be backed by a citation from the data room files, "
            "do NOT produce it — write a gap instead.\n\n" + build_citation_mandate("commercial")
        )

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
        return (
            "You are the ProductTech specialist agent for forensic M&A due diligence. "
            "Focus on product scope, technology stack, integration requirements, "
            "support obligations, documentation, and training requirements. " + SEVERITY_PREAMBLE
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
            f"{GAP_NOT_FOUND} Missing DPAs "
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
            f"{GAP_NOT_FOUND} Do NOT assume security standards are met "
            "without documentary evidence.\n\n"
            #
            "### ProductTech Citation Enforcement\n\n"
            "Technical documents (SOC2 reports, pentest results, architecture diagrams, "
            "SLAs) ARE quotable — they contain specific text you can cite verbatim.\n\n"
            "**How to cite technical documents:**\n"
            "- SOC2/audit reports: quote the control ID, test description, or exception text\n"
            "- Pentest reports: quote the finding ID, severity rating, and remediation status\n"
            "- Architecture docs: quote the component description, technology name, or version\n"
            "- SLA documents: quote the uptime percentage, response time, or penalty clause\n"
            "- Product specs: quote the feature description, requirement, or acceptance criteria\n\n"
            "**STRICT RULE: Every ProductTech finding MUST have a citation.**\n"
            "If you cannot copy verbatim text from a specific document, you do NOT "
            "have evidence for the finding. In that case:\n"
            "1. Do NOT write the finding\n"
            "2. Write a GAP instead with gap_type 'Missing_Doc' or 'Missing_Data'\n"
            "3. Absence of a document (e.g., no SOC2 report) is a GAP, not a finding\n\n"
            "Findings without citations are AUTOMATICALLY DOWNGRADED to P3 during merge. "
            "A P1 finding downgraded to P3 is worthless — invest the extra turn to read "
            "the source document and copy the exact quote.\n\n" + build_citation_mandate("producttech")
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
