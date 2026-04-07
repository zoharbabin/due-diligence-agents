"""Prompt builder -- assembles self-contained agent prompts.

Constructs complete prompts from deal config, customer lists, reference files,
domain rules, and output format requirements.  Implements token estimation and
customer batching when prompts exceed the context budget.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.models.config import DealConfig
    from dd_agents.models.inventory import CustomerEntry, ReferenceFile

# ---------------------------------------------------------------------------
# Agent type enumeration
# ---------------------------------------------------------------------------


class AgentType(StrEnum):
    """All agent roles in the pipeline: 4 specialists + judge + optional agents."""

    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"
    JUDGE = "judge"
    ACQUIRER_INTELLIGENCE = "acquirer_intelligence"
    EXECUTIVE_SYNTHESIS = "executive_synthesis"
    RED_FLAG_SCANNER = "red_flag_scanner"


# ---------------------------------------------------------------------------
# Focus area instructions per specialist
# ---------------------------------------------------------------------------

SPECIALIST_FOCUS: dict[AgentType, str] = {
    AgentType.LEGAL: (
        "Build the governance graph for each customer. Resolve governed_by for every file. "
        "Flag entity mismatches against the corporate org chart. Flag change of control, "
        "assignment restrictions, and exclusivity clauses. Validate intercompany agreements "
        "cover all signing entities. Gap detection: For each customer, check for missing MSAs, "
        "missing DPAs, missing referenced amendments, missing signature pages. "
        "Write gap files for EVERY missing document detected.\n\n"
        "SEVERITY CALIBRATION (Legal):\n"
        "- CoC notification-only = P2 (routine administrative step)\n"
        "- CoC consent-required affecting >5% revenue = P1\n"
        "- CoC competitor-only restriction = P3 (buyer rarely competes with customers)\n"
        "- CoC auto-terminate, no cure, >20% revenue = P0\n"
        "- CoC termination-right with >=60d cure = P1 (not P0)\n"
        "- Termination for Convenience (TfC) = P2 (valuation concern, not deal-breaker)\n"
        "- TfC on >10% revenue, <90d notice = P1\n"
        "- Termination for Cause (standard, mutual) = P3\n"
        "- Standard non-compete with reasonable scope = P3\n"
        "- Missing NDA for active customer = P1; missing NDA for prospect = P3\n\n"
        "REGULATORY & COMPLIANCE:\n"
        "- Assess DPA coverage: identify customers with and without DPAs\n"
        "- Map governing law/jurisdiction for each contract\n"
        "- Identify industry-regulated customers (financial, healthcare, government)\n"
        "- Flag cross-border data transfer issues (Schrems II, data residency)\n"
        "- Note antitrust/competition filing requirements if applicable\n\n"
        "LEGAL ENTITY DISTRIBUTION:\n"
        "- Identify all legal entities referenced in contracts\n"
        "- Flag contracts on legacy/acquired entities needing re-execution\n"
        "- Note entity-specific assignment or consent restrictions\n\n"
        "KEY EMPLOYEE & ORGANIZATIONAL RISK:\n"
        "- Identify key person dependencies from employment and consulting agreements\n"
        "- Flag missing or weak non-compete/non-solicit clauses for key executives\n"
        "- Assess retention risk: vesting cliffs, change-of-control acceleration provisions\n"
        "- Identify single-point-of-failure roles (sole architect, key customer relationships)\n"
        "- Review employment terms for CoC-triggered provisions (acceleration, severance)\n"
        "- Map employment agreements against key_executives from deal config if available"
    ),
    AgentType.FINANCE: (
        "Cross-reference every customer's contract values against the Revenue Cube and any "
        "financial reference data. Flag ARR mismatches >5%. Check discount levels against "
        "Pricing Guidelines. Identify one-time fees incorrectly counted as recurring ARR. "
        "Flag minimum commitment shortfalls. IMPORTANT: You MUST analyze ALL customers, not "
        "just those with dedicated financial documents. For customers with only contract files, "
        "extract financial terms from their contracts and cross-reference against reference "
        "file data. "
        "VERIFICATION REQUIREMENT: For every financial value you cite (dollar amounts, "
        "percentages, ratios), you MUST verify it appears verbatim in the source document. "
        "Include the exact page number and section. If a value is derived (e.g., percentage "
        "change), show the calculation with exact source values. Do NOT round or approximate "
        "source values — cite the exact numbers from the document. "
        "Gap detection: Check for missing financial verification, missing pricing "
        "documentation, unexplained revenue variances. Write gap files.\n\n"
        "SEVERITY CALIBRATION (Finance):\n"
        "- Intercompany payable/receivable in full acquisitions = P3 (eliminated at closing)\n"
        "- ARR mismatch 2-5% = P2; ARR mismatch >5% = P1\n"
        "- One-time fee miscounted as recurring (>$100K) = P1\n"
        "- Standard discount within guidelines = P3\n"
        "- Missing financial audit for trailing twelve months = P1\n\n"
        "REVENUE DECOMPOSITION:\n"
        "- Break down revenue by product/SKU: subscription, professional services, "
        "one-time license, usage-based, support/maintenance\n"
        "- For each stream: recurring vs non-recurring, committed vs uncommitted, "
        "gross margin profile\n"
        "- Flag services-heavy streams >10% revenue (lower valuation multiple)\n"
        "- Identify percentage-of-completion or milestone-based recognition\n\n"
        "UNIT ECONOMICS:\n"
        "- Extract/estimate CAC, LTV, payback period where data allows\n"
        "- Calculate/verify NRR and GRR from cohort data if available\n"
        "- Flag NRR < 100% (contraction) or GRR < 85% (high churn)\n"
        "- Identify margin profile by product line from segmented P&L\n\n"
        "FINANCIAL PROJECTIONS VALIDATION:\n"
        "- Cross-reference projections vs historical growth rates\n"
        "- Flag unrealistic assumptions (growth acceleration, margin expansion "
        "without supporting initiatives)\n"
        "- Note committed vs pipeline revenue in forward projections"
    ),
    AgentType.COMMERCIAL: (
        "Evaluate renewal mechanics (auto vs manual, notice periods, penalties). Cross-reference "
        "contract terms against Customer Health Scores for churn risk. Compare pricing against "
        "rate cards. Flag SLA commitments and service credit exposure. "
        "IMPORTANT DOMAIN BOUNDARY: For detailed financial analysis (revenue recognition, "
        "deferred revenue ratios, cash burn calculations, financial statement reconciliation), "
        "defer to the Finance agent. Do NOT perform independent financial calculations — "
        "note the data point and flag it for cross-agent review instead. "
        "Gap detection: Check for "
        "missing SOWs, missing order forms, missing renewal evidence, unsigned documents. "
        "Write gap files for EVERY missing document detected.\n\n"
        "SEVERITY CALIBRATION (Commercial):\n"
        "- Standard renewal approaching (<90 days) = P2\n"
        "- Auto-renew with termination-for-convenience on >10% revenue customer = P1\n"
        "- Expired contract still in operation = P1\n"
        "- Standard volume discount = P3\n"
        "- Customer churn risk with active replacement options = P2\n"
        "- TfC clause = P2 valuation/revenue quality concern, not a deal-breaker\n"
        "- TfC on >10% revenue, <90d notice = P1\n\n"
        "CUSTOMER SEGMENTATION & COHORT:\n"
        "- Segment by size (enterprise/mid-market/SMB), geography, vertical, vintage\n"
        "- Identify concentration: top 10% of revenue, single-vertical dependency\n"
        "- Flag >30% revenue from one vertical or geography\n\n"
        "PRICING MODEL:\n"
        "- Identify type: per-user, per-unit/consumption, tiered, flat-rate, hybrid\n"
        "- Flag pricing risks: consumption = volatile, per-seat = downsizing risk\n"
        "- Compare effective pricing across cohorts\n\n"
        "EXPANSION & CONTRACTION:\n"
        "- Decompose NRR: upsell + cross-sell + price increases - downgrades - churn\n"
        "- Identify expansion levers: seat adds, module upsell, escalation clauses\n"
        "- Flag contraction signals: seat reduction, step-down pricing, shortfalls\n\n"
        "COMPETITIVE POSITIONING:\n"
        "- Note competitive displacement language in contracts\n"
        "- Identify exclusivity or preferred vendor status\n"
        "- Flag benchmarking or MFN clauses"
    ),
    AgentType.PRODUCTTECH: (
        "Validate DPA adequacy and subprocessor lists. Cross-reference security claims against "
        "SOC2/compliance evidence. Check technical SLA feasibility. Flag data residency "
        "restrictions and migration obligations. IMPORTANT: You MUST analyze ALL customers, "
        "not just those with dedicated tech/security documents. For every customer's contracts, "
        "extract technology-related clauses. Gap detection: Check for missing DPAs, missing "
        "security addenda, missing SLA documentation, missing architecture/integration specs. "
        "Write gap files.\n\n"
        "SEVERITY CALIBRATION (ProductTech):\n"
        "- Missing DPA for EU-resident data processing = P1\n"
        "- Missing SOC2 report = P2\n"
        "- Expired security certification (>12 months) = P1\n"
        "- Minor technical debt in non-critical systems = P3\n"
        "- Data residency violation for regulated data = P0\n\n"
        "TECHNOLOGY STACK & TECHNICAL DEBT ASSESSMENT:\n"
        "- Identify technology stack components from contracts, SOWs, and technical documents\n"
        "- Flag deprecated technologies, end-of-life platforms, or unsupported versions\n"
        "- Assess migration complexity: proprietary APIs, vendor lock-in, custom integrations\n"
        "- Evaluate security posture: SOC2 gaps, penetration test recency, encryption standards\n"
        "- Assess scalability constraints: architecture limitations, SLA vs capacity\n"
        "- Quantify technical debt remediation cost where evidence supports estimation\n"
        "- For each finding, classify sub-category: technical_debt, security_posture, "
        "scalability, migration_complexity, or architecture_risk"
    ),
}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Assembles self-contained agent prompts from templates and runtime data."""

    # Prompt version tracking (Issue #146) — bump on prompt changes
    PROMPT_VERSION: str = "2.0.0"

    def __init__(
        self,
        project_dir: Path,
        run_dir: Path,
        run_id: str,
    ) -> None:
        self.project_dir = project_dir
        self.run_dir = run_dir
        self.run_id = run_id
        self.prompt_version = self.PROMPT_VERSION

    # ------------------------------------------------------------------
    # Specialist prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_deal_config(deal_config: DealConfig | dict[str, Any] | None) -> DealConfig | None:
        """Convert a raw dict to :class:`DealConfig` if needed.

        The pipeline state stores ``deal_config`` as a plain dict for
        JSON-safe checkpoint serialisation.  This helper reconstructs
        the typed Pydantic model so callers can use attribute access.
        Returns *None* if conversion fails or *deal_config* is ``None``.
        """
        if deal_config is None:
            return None

        # Already a DealConfig (or similar Pydantic model with .buyer)
        if hasattr(deal_config, "buyer"):
            return deal_config  # type: ignore[return-value]

        # Raw dict → DealConfig via Pydantic validation
        if isinstance(deal_config, dict):
            from dd_agents.models.config import DealConfig as _DealConfig

            try:
                return _DealConfig.model_validate(deal_config)
            except Exception:
                return None

        return None

    @staticmethod
    def _coerce_customers(customers: list[CustomerEntry] | list[str] | list[Any]) -> list[CustomerEntry]:
        """Ensure *customers* is a list of :class:`CustomerEntry` objects.

        When ``_run_specialist`` falls back to ``build_prompt()``, customers
        may be plain safe-name strings from ``PipelineState.customer_safe_names``.
        This converts them to minimal :class:`CustomerEntry` instances so that
        ``_build_customer_list`` can access ``.name`` / ``.safe_name`` etc.
        """
        if not customers:
            return []

        first = customers[0]
        if hasattr(first, "safe_name"):
            return customers  # type: ignore[return-value]

        # Plain strings — convert to minimal CustomerEntry objects.
        from dd_agents.models.inventory import CustomerEntry as _CustomerEntry

        return [_CustomerEntry(group="", name=str(s), safe_name=str(s), path=str(s)) for s in customers]

    @staticmethod
    def _build_severity_rubric(deal_config: DealConfig | dict[str, Any] | None) -> str:
        """Build a severity calibration rubric section for specialist prompts.

        Provides concrete P0-P3 criteria with examples and anti-examples,
        deal-type-specific guidance, and common false positive warnings.
        """
        deal_type = ""
        if deal_config:
            if hasattr(deal_config, "deal") and hasattr(deal_config.deal, "type"):
                deal_type = str(deal_config.deal.type).lower()
            elif isinstance(deal_config, dict):
                deal_obj = deal_config.get("deal", {})
                if isinstance(deal_obj, dict):
                    deal_type = str(deal_obj.get("type", "")).lower()
                elif hasattr(deal_obj, "type"):
                    deal_type = str(deal_obj.type).lower()

        lines: list[str] = [
            "## SEVERITY CALIBRATION",
            "",
            "Calibrate severity carefully. Quality over quantity — fewer, well-calibrated "
            "findings are far more valuable than many poorly-calibrated ones.",
            "",
            "### P0 — Genuine Deal-Stoppers (max 2-3 per entity)",
            "Reserved for issues that would cause a reasonable acquirer to walk away or ",
            "fundamentally renegotiate the deal price.",
            "Examples: undisclosed fraud, regulatory prohibition, auto-termination of >20% "
            "revenue on CoC with no cure, material IP ownership dispute.",
            "Anti-examples: routine CoC notifications, standard consent requirements, approaching "
            "renewal deadlines, TfC clauses (valuation concern, not deal-stopper), "
            "competitor-only CoC restrictions (buyer rarely competes with customers).",
            "",
            "### P1 — Material Risk Requiring Pre-Close Negotiation",
            "Issues that require specific deal protection (indemnity, escrow, price adjustment) "
            "but do not fundamentally threaten the deal.",
            "Examples: consent-required assignment for >5% revenue customers, ARR mismatch >5%, "
            "missing DPA for EU data, expired security certifications.",
            "",
            "### P2 — Moderate Risk, Post-Close Remediation",
            "Issues addressable through standard integration workstreams.",
            "Examples: approaching renewals, minor pricing discrepancies, standard CoC "
            "notification requirements, missing non-critical documentation.",
            "",
            "### P3 — Informational / Low Risk",
            "Noted for completeness but requiring no specific action.",
            "Examples: standard contract terms, minor administrative items, routine "
            "compliance matters with no financial impact.",
            "",
        ]

        # Deal-type-specific guidance
        if deal_type in ("acquisition", "merger", "buyout"):
            lines.extend(
                [
                    "### Deal-Type Context: Full Acquisition",
                    f"This is a {deal_type}. Key calibration rules:",
                    "- Intercompany obligations (payables, receivables, guarantees) between "
                    "target subsidiaries are eliminated at closing — do NOT flag as P0.",
                    "- Standard change-of-control notification requirements are routine "
                    "administrative steps — P2 at most, not P0.",
                    "- Parent-subsidiary agreements are superseded by the acquisition — "
                    "flag only if they create third-party obligations.",
                    "",
                ]
            )
        elif deal_type in ("divestiture", "carve-out", "spin-off"):
            lines.extend(
                [
                    "### Deal-Type Context: Divestiture/Carve-Out",
                    f"This is a {deal_type}. Key calibration rules:",
                    "- Shared services agreements that need to be replicated are P1 if no transition plan exists.",
                    "- Intercompany agreements that must survive the separation need "
                    "careful analysis — flag missing standalone terms as P1.",
                    "- IP licensing back to parent requires clear scope — ambiguity is P1.",
                    "",
                ]
            )
        elif deal_type:
            lines.extend(
                [
                    f"### Deal-Type Context: {deal_type.title()}",
                    "Apply standard severity criteria. Intercompany obligations should "
                    "be evaluated in context of the specific transaction structure.",
                    "",
                ]
            )

        lines.extend(
            [
                "### Common False Positives (do NOT flag as P0)",
                "- Intercompany payables/receivables in full acquisitions",
                "- Standard change-of-control notification requirements",
                "- Approaching renewal deadlines (>30 days out)",
                "- Routine consent requirements for assignment",
                "- Standard limitation of liability clauses",
                "- Missing documents that are not contractually required",
                "- TfC clauses — flag as P2 valuation concern, never P0",
                "- Competitor-only CoC restrictions — P3 unless buyer competes with customer",
            ]
        )

        return "\n".join(lines)

    def build_specialist_prompt(
        self,
        agent_name: str,
        customers: list[CustomerEntry] | list[str],
        reference_files: list[ReferenceFile] | None = None,
        deal_config: DealConfig | dict[str, Any] | None = None,
        file_precedence: dict[str, Any] | None = None,
    ) -> str:
        """Build a complete, self-contained specialist prompt.

        Parameters
        ----------
        agent_name:
            One of ``legal``, ``finance``, ``commercial``, ``producttech``.
        customers:
            List of :class:`CustomerEntry` objects -- every customer the agent
            must analyse.  Plain strings (safe_names) are also accepted and
            automatically coerced to minimal :class:`CustomerEntry` objects.
        reference_files:
            Reference files routed to this agent.  May be ``None``.
        deal_config:
            The loaded :class:`DealConfig`, or a raw dict from pipeline
            state.  Automatically coerced to :class:`DealConfig` if a
            dict is passed.  May be ``None`` for tests.
        file_precedence:
            Optional mapping of file path → FileEntry with precedence metadata.
            When provided, file lists are annotated with precedence status.
        """
        raw_deal_config = deal_config
        deal_config = self._coerce_deal_config(deal_config)
        customers = self._coerce_customers(customers)
        sections: list[str] = []

        # 1. Role & deal context
        sections.append(self._build_role_section(agent_name, deal_config))

        # 2. Customer list (with optional precedence annotations)
        sections.append(self._build_customer_list(agent_name, customers, file_precedence))

        # 2b. Document precedence rules (Issue #163)
        if file_precedence:
            sections.append(self._build_precedence_rules())

        # 3. File access instructions (Issue #87)
        sections.append(self._build_file_access_instructions())

        # 4. Reference files
        sections.append(self._build_reference_section(reference_files or []))

        # 5. Specialist focus
        try:
            agent_type = AgentType(agent_name)
        except ValueError:
            agent_type = None
        if agent_type and agent_type in SPECIALIST_FOCUS:
            sections.append(f"## YOUR SPECIALIST FOCUS\n\n{SPECIALIST_FOCUS[agent_type]}")

        # 5b. Severity calibration rubric (accepts both DealConfig and raw dict)
        sections.append(self._build_severity_rubric(deal_config or raw_deal_config))

        # 6. Output format requirements
        sections.append(self._build_output_format(agent_name))

        # 7. Manifest requirement
        sections.append(self._build_manifest_requirement(agent_name, customers))

        # 8. Robustness instructions (Issue #52 -- spec doc 22)
        sections.append(self.robustness_instructions())

        prompt = "\n\n---\n\n".join(sections)

        # Safety guard: if the assembled prompt exceeds the model context
        # (200K tokens ≈ 800K chars), truncate the customer file listing.
        # This protects against very large single-target data rooms with
        # long cloud-storage paths (e.g. OneDrive).
        max_prompt_chars = 600_000  # ~150K tokens, leaving room for agent turns
        if len(prompt) > max_prompt_chars:
            logger.warning(
                "Prompt for %s is %d chars (~%dK tokens) — exceeds safety limit. "
                "Truncating file listing from %d to %d files.",
                agent_name,
                len(prompt),
                len(prompt) // 4000,
                self.MAX_LISTED_FILES,
                self.MAX_LISTED_FILES // 2,
            )
            self.MAX_LISTED_FILES = max(50, self.MAX_LISTED_FILES // 2)
            sections[1] = self._build_customer_list(agent_name, customers, file_precedence)
            prompt = "\n\n---\n\n".join(sections)

        return prompt

    # ------------------------------------------------------------------
    # Judge prompt
    # ------------------------------------------------------------------

    def build_judge_prompt(
        self,
        findings_dir: str | Path | None = None,
        quality_targets: dict[str, Any] | None = None,
        sampling_rates: dict[str, float] | None = None,
    ) -> str:
        """Build the Judge agent prompt.

        Parameters
        ----------
        findings_dir:
            Path to the ``findings/`` directory tree.
        quality_targets:
            Score threshold and other QA targets.
        sampling_rates:
            Per-severity sampling rates (e.g. ``{"p0": 1.0, "p1": 0.2, ...}``).
        """
        rates = sampling_rates or {"p0": 1.0, "p1": 0.20, "p2": 0.10, "p3": 0.0}
        targets = quality_targets or {"score_threshold": 70}

        sections: list[str] = []

        sections.append(
            "# JUDGE AGENT\n\n"
            "You are the Judge for forensic M&A due diligence.\n"
            "Your role is to verify the quality of specialist agent outputs.\n"
            f"Run ID: {self.run_id}"
        )

        sections.append(
            "## SAMPLING RATES\n\n"
            f"- P0 (deal-stoppers): {rates['p0'] * 100:.0f}%\n"
            f"- P1 (material risk): {rates['p1'] * 100:.0f}%\n"
            f"- P2 (moderate risk): {rates['p2'] * 100:.0f}%\n"
            f"- P3 (informational): {rates['p3'] * 100:.0f}%"
        )

        sections.append(
            "## QUALITY TARGETS\n\n"
            f"Score threshold: {targets.get('score_threshold', 70)}\n\n"
            "Score weights:\n"
            "- citation_verification: 30%\n"
            "- contextual_validation: 25%\n"
            "- financial_accuracy: 20%\n"
            "- cross_agent_consistency: 15%\n"
            "- completeness: 10%"
        )

        sections.append(
            "## SPOT-CHECK PROTOCOL\n\n"
            "For each sampled finding:\n"
            "1. Citation verification -- does the quoted text exist in the source?\n"
            "2. Contextual validation -- is the finding correctly interpreted?\n"
            "3. Financial accuracy -- are numbers, dates, calculations correct?\n"
            "4. Cross-agent consistency -- do agents agree on facts?\n"
            "5. Completeness -- did the agent process all files and focus areas?"
        )

        if findings_dir:
            sections.append(f"## FINDINGS DIRECTORY\n\nRead specialist outputs from: {findings_dir}")

        sections.append(f"## OUTPUT\n\nWrite quality_scores.json to: {self.run_dir}/judge/quality_scores.json\n")

        return "\n\n---\n\n".join(sections)

    # ------------------------------------------------------------------
    # Acquirer Intelligence prompt (Issue #110)
    # ------------------------------------------------------------------

    def build_acquirer_intelligence_prompt(
        self,
        buyer_strategy: dict[str, Any],
        findings_summary: dict[str, Any],
        merged_findings_dir: str | None = None,
    ) -> str:
        """Build the Acquirer Intelligence agent prompt.

        Parameters
        ----------
        buyer_strategy:
            Buyer strategy dict from deal config.
        findings_summary:
            Summary statistics of merged findings (total, by severity, by domain).
        merged_findings_dir:
            Path to merged findings directory for the agent to read.
        """
        sections: list[str] = []

        sections.append(
            "# ACQUIRER INTELLIGENCE ANALYSIS\n\n"
            "You are the Acquirer Intelligence analyst for forensic M&A due diligence.\n"
            f"Run ID: {self.run_id}\n\n"
            "Analyse the merged due diligence findings through the buyer's strategic "
            "lens. Produce a structured assessment of how findings impact the "
            "acquisition thesis."
        )

        # Buyer strategy context
        strategy_lines = ["## BUYER STRATEGY"]
        if buyer_strategy.get("thesis"):
            strategy_lines.append(f"Acquisition Thesis: {buyer_strategy['thesis']}")
        if buyer_strategy.get("key_synergies"):
            strategy_lines.append(f"Expected Synergies: {', '.join(buyer_strategy['key_synergies'])}")
        if buyer_strategy.get("integration_priorities"):
            strategy_lines.append(f"Integration Priorities: {', '.join(buyer_strategy['integration_priorities'])}")
        if buyer_strategy.get("risk_tolerance"):
            strategy_lines.append(f"Risk Tolerance: {buyer_strategy['risk_tolerance']}")
        if buyer_strategy.get("focus_areas"):
            strategy_lines.append(f"Focus Areas: {', '.join(buyer_strategy['focus_areas'])}")
        sections.append("\n".join(strategy_lines))

        # Findings summary
        summary_lines = ["## FINDINGS SUMMARY"]
        if findings_summary:
            for key, value in sorted(findings_summary.items()):
                summary_lines.append(f"- {key}: {value}")
        else:
            summary_lines.append("No findings summary available.")
        sections.append("\n".join(summary_lines))

        # Merged findings location
        if merged_findings_dir:
            sections.append(f"## MERGED FINDINGS\n\nRead merged findings from: {merged_findings_dir}")

        # Output format
        sections.append(
            "## OUTPUT FORMAT\n\n"
            "Return a single JSON object with:\n"
            '- "summary": Strategic assessment of findings impact on acquisition thesis\n'
            '- "recommendations": List of actionable recommendations\n'
            '- "risk_alignment": List of {focus_area, finding_count, assessment}\n'
            '- "deal_impact": "low" | "moderate" | "high" | "critical"\n'
            '- "key_concerns": List of key concern strings\n\n'
            "Output ONLY the JSON object. No explanatory text."
        )

        return "\n\n---\n\n".join(sections)

    # ------------------------------------------------------------------
    # Executive Synthesis prompt
    # ------------------------------------------------------------------

    def build_executive_synthesis_prompt(
        self,
        deal_config: dict[str, Any] | None,
        p0_findings: list[dict[str, Any]],
        p1_findings: list[dict[str, Any]],
        findings_summary: dict[str, Any],
        merged_findings_dir: str | None = None,
    ) -> str:
        """Build the Executive Synthesis agent prompt.

        Parameters
        ----------
        deal_config:
            Raw deal configuration dict.
        p0_findings:
            All P0 findings (title, description, entity).
        p1_findings:
            All P1 findings (title, description, entity).
        findings_summary:
            Summary statistics (total, by severity, by domain).
        merged_findings_dir:
            Path to merged findings for the agent to read.
        """
        sections: list[str] = []

        sections.append(
            "# EXECUTIVE SYNTHESIS — SENIOR M&A PARTNER REVIEW\n\n"
            "You are a senior M&A partner conducting a final review of the due diligence "
            "findings before presenting to the board. Your role is to apply professional "
            "judgment to re-evaluate the severity of flagged issues and produce a calibrated "
            "Go/No-Go recommendation.\n\n"
            f"Run ID: {self.run_id}\n\n"
            "CRITICAL RULES:\n"
            "- No-Go requires truly exceptional circumstances: evidence of fraud, regulatory "
            "prohibition, or irremediable structural issues.\n"
            "- Most deals are 'Conditional Go' — risks are managed through deal mechanics.\n"
            "- Intercompany obligations between target subsidiaries are eliminated at closing.\n"
            "- Standard change-of-control notifications are routine, not deal-breaking.\n\n"
            "CRITICAL EVALUATION FRAMEWORK FOR CoC/TERMINATION:\n"
            "- Competitor-only CoC: Assess whether the buyer actually competes with the "
            "customer. In most deals this is P3.\n"
            "- Notification-only CoC: Routine administrative step — never above P2.\n"
            "- Consent-required CoC: Assess cure period and revenue at risk.\n"
            "- TfC clauses: VALUATION concerns, not deal-blockers. Reclassify any P0/P1 "
            "TfC findings to P2 unless combined with other risk factors.\n"
            "- TfCause: Standard protective clause — P3 unless 'cause' is broadly defined.\n"
            "- Separate consent vs notice vs termination vs auto-termination in analysis."
        )

        # Deal context
        if deal_config:
            ctx_lines = ["## DEAL CONTEXT"]
            buyer = deal_config.get("buyer", {})
            target = deal_config.get("target", {})
            deal = deal_config.get("deal", {})
            if buyer.get("name"):
                ctx_lines.append(f"Buyer: {buyer['name']}")
            if target.get("name"):
                ctx_lines.append(f"Target: {target['name']}")
            if deal.get("type"):
                ctx_lines.append(f"Deal Type: {deal['type']}")
            if target.get("subsidiaries"):
                ctx_lines.append(f"Subsidiaries: {', '.join(target['subsidiaries'])}")
            sections.append("\n".join(ctx_lines))

        # P0 findings
        p0_lines = [f"## P0 FINDINGS ({len(p0_findings)} total)"]
        if p0_findings:
            for i, f in enumerate(p0_findings, 1):
                title = f.get("title", "Untitled")
                entity = f.get("entity", f.get("_customer", ""))
                desc = f.get("description", "")
                p0_lines.append(f"\n{i}. **{title}**")
                if entity:
                    p0_lines.append(f"   Entity: {entity}")
                if desc:
                    p0_lines.append(f"   {desc[:300]}")
        else:
            p0_lines.append("None.")
        sections.append("\n".join(p0_lines))

        # P1 findings
        p1_lines = [f"## P1 FINDINGS ({len(p1_findings)} total)"]
        if p1_findings:
            for i, f in enumerate(p1_findings[:20], 1):
                title = f.get("title", "Untitled")
                entity = f.get("entity", f.get("_customer", ""))
                p1_lines.append(f"{i}. {title}" + (f" ({entity})" if entity else ""))
            if len(p1_findings) > 20:
                p1_lines.append(f"... and {len(p1_findings) - 20} more P1 findings")
        else:
            p1_lines.append("None.")
        sections.append("\n".join(p1_lines))

        # Summary stats
        summary_lines = ["## FINDINGS SUMMARY"]
        if findings_summary:
            for key, value in sorted(findings_summary.items()):
                summary_lines.append(f"- {key}: {value}")
        sections.append("\n".join(summary_lines))

        # Merged findings location
        if merged_findings_dir:
            sections.append(
                f"## MERGED FINDINGS\n\nRead merged findings from: {merged_findings_dir}\n"
                "Review the full findings files for additional context on P0 and P1 issues."
            )

        # Output format
        sections.append(
            "## OUTPUT FORMAT\n\n"
            "Return a single JSON object with these fields:\n"
            "```json\n"
            "{\n"
            '  "go_no_go_signal": "Go | Conditional Go | Proceed with Caution | No-Go",\n'
            '  "go_no_go_rationale": "Board-ready paragraph explaining recommendation",\n'
            '  "executive_narrative": "2-3 paragraph DD summary for board presentation",\n'
            '  "risk_score_override": 0-100 or -1 to keep mechanical score,\n'
            '  "severity_overrides": [\n'
            "    {\n"
            '      "finding_title": "...",\n'
            '      "entity": "...",\n'
            '      "original_severity": "P0",\n'
            '      "recommended_severity": "P3",\n'
            '      "rationale": "..."\n'
            "    }\n"
            "  ],\n"
            '  "deal_breakers_ranked": [\n'
            "    {\n"
            '      "rank": 1,\n'
            '      "title": "...",\n'
            '      "entity": "...",\n'
            '      "impact_description": "...",\n'
            '      "remediation": "..."\n'
            "    }\n"
            "  ],\n"
            '  "key_themes": ["theme1", "theme2"]\n'
            "}\n"
            "```\n"
            "Output ONLY the JSON object. No explanatory text."
        )

        return "\n\n---\n\n".join(sections)

    # ------------------------------------------------------------------
    # Token estimation & batching
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_tokens(prompt: str) -> int:
        """Rough token estimation: characters / 4."""
        return len(prompt) // 4

    @staticmethod
    def _estimate_customer_tokens(
        customer: CustomerEntry,
        text_dir: Path | None = None,
    ) -> int:
        """Estimate the prompt tokens one customer entry will occupy.

        When *text_dir* is provided, measures actual extracted text sizes
        from ``<text_dir>/<filename>.md`` files.  This produces accurate
        token estimates based on real content rather than path-length
        heuristics.

        Without *text_dir*, falls back to header + path-length estimation.
        """
        # Fixed header: "### Customer: ...", safe_name, path, "Files (N):"
        chars = 160
        files = customer.files or []

        if text_dir is not None:
            # Measure actual extracted text sizes
            from pathlib import Path as _Path

            for fp in files:
                # Extraction writes <filename>.md in text_dir
                text_file = text_dir / (_Path(fp).name + ".md")
                if text_file.exists():
                    try:
                        chars += text_file.stat().st_size
                    except OSError:
                        chars += len(fp) + 8  # fallback to path estimate
                else:
                    # No extracted text — use path-based estimate
                    chars += len(fp) + 8
        else:
            for fp in files[: PromptBuilder.MAX_LISTED_FILES]:
                chars += len(fp) + 8  # "    - {fp}\n"
            if len(files) > PromptBuilder.MAX_LISTED_FILES:
                chars += 120  # truncation notice

        return max(1, chars // 4)

    @staticmethod
    def batch_customers(
        customers: list[CustomerEntry],
        max_tokens: int = 40_000,
        tokens_per_customer: int | None = None,
        overhead_tokens: int = 5_000,
        max_per_batch: int = 20,
        text_dir: Path | None = None,
    ) -> list[list[CustomerEntry]]:
        """Split *customers* into batches that each fit within *max_tokens*.

        Parameters
        ----------
        customers:
            Full customer list.
        max_tokens:
            Maximum tokens per batch (default 40 000 -- ~20 % of 200k context,
            leaving ample room for agent tool calls and file reads).
        tokens_per_customer:
            Estimated tokens per customer entry in the prompt.  When ``None``
            (default), computed automatically from the actual file listings
            in each customer entry.
        overhead_tokens:
            Fixed token overhead for prompt preamble, rules, etc.
        max_per_batch:
            Hard cap on customers per batch (default 20).  Prevents
            oversized batches when file listings are unavailable and
            the token estimation underestimates prompt size.
        text_dir:
            Path to the extracted text directory.  When provided, token
            estimation uses actual file sizes instead of path-length
            heuristics.

        Returns
        -------
        A list of customer batches.  If all customers fit in one batch, returns
        a single-element list.
        """
        if not customers:
            return []

        available = max_tokens - overhead_tokens
        if available <= 0:
            available = max_tokens

        # When tokens_per_customer is explicit, use uniform splitting.
        if tokens_per_customer is not None:
            cap = max(1, available // max(1, tokens_per_customer))
            cap = min(cap, max_per_batch)
            batches: list[list[CustomerEntry]] = []
            for i in range(0, len(customers), cap):
                batches.append(customers[i : i + cap])
            return batches

        # Data-driven greedy batching: pack customers until the batch is full.
        batches = []
        current_batch: list[CustomerEntry] = []
        current_tokens = 0

        for customer in customers:
            est = PromptBuilder._estimate_customer_tokens(customer, text_dir=text_dir)
            if current_batch and (current_tokens + est > available or len(current_batch) >= max_per_batch):
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(customer)
            current_tokens += est

        if current_batch:
            batches.append(current_batch)

        return batches

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_role_section(self, agent_name: str, deal_config: DealConfig | None) -> str:
        lines = [
            f"# {agent_name.upper()} SPECIALIST AGENT",
            "",
            f"You are the {agent_name} specialist for forensic M&A due diligence.",
            f"Run ID: {self.run_id}",
        ]
        if deal_config:
            lines.extend(
                [
                    "",
                    "## DEAL CONTEXT",
                    f"Buyer: {deal_config.buyer.name}",
                    f"Target: {deal_config.target.name}",
                    f"Deal type: {deal_config.deal.type}",
                    f"Focus areas: {', '.join(deal_config.deal.focus_areas)}",
                ]
            )
            if deal_config.target.subsidiaries:
                lines.append(f"Subsidiaries: {', '.join(deal_config.target.subsidiaries)}")
            if deal_config.buyer_strategy:
                bs = deal_config.buyer_strategy
                if bs.thesis:
                    lines.append(f"Acquisition thesis: {bs.thesis[:300]}")
                if bs.focus_areas:
                    lines.append(f"Buyer risk focus: {', '.join(bs.focus_areas[:5])}")
        return "\n".join(lines)

    # Maximum files to list inline per customer.  Beyond this, the agent
    # discovers remaining files via directory traversal.  Keeps prompts
    # within the model's context window for large single-target data rooms
    # (e.g. 4K files with long OneDrive/cloud-storage paths).
    MAX_LISTED_FILES: int = 200

    def _build_customer_list(
        self,
        agent_name: str,
        customers: list[CustomerEntry],
        file_precedence: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            "## ALL CUSTOMERS (you MUST process every one, every file)",
            "",
        ]
        for idx, cust in enumerate(customers, 1):
            lines.append(f"Customer {idx}: {cust.name} (safe_name: {cust.safe_name})")
            lines.append(f"  Path: {cust.path}")
            if cust.files:
                # Sort files by precedence score (highest first) if available
                sorted_files = list(cust.files)
                if file_precedence:
                    sorted_files.sort(
                        key=lambda fp: (
                            -(
                                file_precedence[fp].precedence_score
                                if fp in file_precedence and hasattr(file_precedence[fp], "precedence_score")
                                else 0.0
                            )
                        )
                    )

                # Cap inline listing for very large customers.
                truncated = len(sorted_files) > self.MAX_LISTED_FILES
                display_files = sorted_files[: self.MAX_LISTED_FILES] if truncated else sorted_files

                if file_precedence:
                    lines.append(f"  Files ({cust.file_count}) — ordered by precedence:")
                else:
                    lines.append(f"  Files ({cust.file_count}):")

                for fp in display_files:
                    annotation = self._file_annotation(fp, file_precedence)
                    lines.append(f"    - {fp}{annotation}")

                if truncated:
                    omitted = len(sorted_files) - self.MAX_LISTED_FILES
                    lines.append(
                        f'    ... and {omitted} more files. Use `Glob(pattern="**/*")` on the '
                        f"customer's directory to discover all files. You MUST analyze every file."
                    )
            lines.append("")

        lines.append(
            f"CRITICAL — OUTPUT FILENAMES:\n"
            f"Your output filename MUST be exactly: {{safe_name}}.json\n"
            f"Copy the safe_name character-for-character from above. Do NOT normalize, "
            f"transform, or recompute it. The safe_name is pre-computed and authoritative.\n"
            f"Write to: {self.run_dir}/findings/{agent_name}/{{safe_name}}.json\n\n"
            f"TOTAL: {len(customers)} customers. You must process every single one.\n\n"
            f"SPEED RULES (MANDATORY — violating these wastes budget and causes failures):\n"
            f"1. Do NOT read or validate existing output files in the findings "
            f"directory. Always write fresh output by analyzing source documents directly. "
            f"If a file already exists at the output path, overwrite it without reading it first.\n"
            f"2. Do NOT spawn sub-agents, background agents, or parallel agents. "
            f"You are a single agent processing customers one at a time IN THIS SESSION. "
            f"Never use the Agent tool or launch child processes. "
            f"Process each customer sequentially: read files → analyze → write JSON → next customer.\n"
            f"3. Write each customer's JSON file IMMEDIATELY after analyzing it. "
            f"Do NOT accumulate findings in memory across customers. "
            f"Write → move on → write → move on.\n"
            f"4. Do NOT summarize your progress, reflect on what you did, or produce final "
            f"status reports. Just write the JSON files and move to the next customer.\n"
            f"5. Do NOT re-read a customer's output file after writing it. Write it once correctly."
        )
        return "\n".join(lines)

    @staticmethod
    def _file_annotation(fp: str, file_precedence: dict[str, Any] | None) -> str:
        """Build a precedence annotation string for a file in the prompt."""
        if not file_precedence or fp not in file_precedence:
            return ""
        entry = file_precedence[fp]
        if not hasattr(entry, "is_latest_version"):
            return ""

        parts: list[str] = []
        if not entry.is_latest_version and entry.superseded_by:
            superseder_name = (
                entry.superseded_by.rsplit("/", 1)[-1] if "/" in entry.superseded_by else entry.superseded_by
            )
            parts.append(f"SUPERSEDED by {superseder_name}")
        elif entry.precedence_score >= 0.8:
            parts.append("AUTHORITATIVE")
        else:
            parts.append("CURRENT")

        if entry.version_indicator:
            parts.append(entry.version_indicator)
        if entry.mtime_iso:
            parts.append(entry.mtime_iso)

        return f"  [{', '.join(parts)}]" if parts else ""

    @staticmethod
    def _build_precedence_rules() -> str:
        """Build the document precedence rules section for agent prompts (Issue #163)."""
        return (
            "## DOCUMENT PRECEDENCE RULES\n\n"
            "Files above are annotated with precedence status. Follow these rules strictly:\n"
            "1. Files marked AUTHORITATIVE or CURRENT are the primary sources of truth.\n"
            "2. Files marked SUPERSEDED have been replaced by a newer version — read them for "
            "historical context only, never cite superseded terms as current.\n"
            "3. When two files contain conflicting terms for the same clause, the file with "
            "higher precedence wins. If still ambiguous, the file with the later modification "
            "date wins.\n"
            "4. Always note in your finding when you detect a conflict between document versions, "
            "citing both the current and superseded terms.\n"
            "5. Flag as a gap (P1) when only a superseded version exists with no authoritative "
            "replacement in the data room."
        )

    @staticmethod
    def _build_file_access_instructions() -> str:
        """Instructions telling agents to read original files directly (Issue #87)."""
        return (
            "## HOW TO READ FILES\n\n"
            "Use the **Read** tool for: .pdf, .csv, .txt, .json, .xml, images.\n\n"
            "Use the **read_office** tool for: .xlsx, .xls, .docx, .doc, .pptx, .ppt.\n"
            "The Read tool CANNOT read binary Office files — it returns garbled content. "
            'Always use `read_office(file_path="...")` for these formats. '
            "For Excel files you can optionally pass `sheet_name` to read a specific sheet.\n\n"
            "Read the EXACT paths shown in the customer file lists — do not "
            "construct alternative paths or look for converted versions.\n"
            "For large files (>100KB), use Grep to search for specific terms "
            "instead of reading the entire file.\n\n"
            "If the file list says '... and N more files', use `Glob(pattern=\"**/*\")` on the "
            "customer's directory (shown as 'Path:') to discover ALL files. "
            "You MUST analyze every file in the data room, not just those "
            "listed inline."
        )

    @staticmethod
    def _build_reference_section(reference_files: list[ReferenceFile]) -> str:
        if not reference_files:
            return "## GLOBAL REFERENCE FILES\n\nNo reference files assigned."

        lines = ["## GLOBAL REFERENCE FILES assigned to you", ""]
        for idx, ref in enumerate(reference_files, 1):
            lines.append(
                f"Reference {idx}: {ref.file_path}\n"
                f"  Category: {ref.category} / {ref.subcategory}\n"
                f"  Description: {ref.description}"
            )
            if ref.text_path:
                lines.append(f"  Pre-extracted at: {ref.text_path}")
            if ref.customers_mentioned:
                lines.append(f"  Customers mentioned: {', '.join(ref.customers_mentioned)}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_output_format(agent_name: str) -> str:
        return (
            "## OUTPUT FORMAT\n\n"
            "Write one JSON file per customer with the following structure:\n"
            "```json\n"
            "{\n"
            '  "customer": "Canonical customer name",\n'
            '  "customer_safe_name": "safe_name",\n'
            f'  "agent": "{agent_name}",\n'
            '  "run_id": "...",\n'
            '  "timestamp": "ISO-8601",\n'
            '  "files_analyzed": 0,\n'
            '  "file_headers": [],\n'
            '  "governance_graph": {"edges": []},\n'
            '  "findings": [],\n'
            '  "gaps": [],\n'
            '  "cross_references": [],\n'
            '  "metadata": {}\n'
            "}\n"
            "```\n\n"
            "### Finding Entry Schema\n\n"
            "Every entry in `findings` MUST be a JSON object with a non-empty "
            "`citations` array:\n"
            "```json\n"
            "{\n"
            '  "severity": "P0 | P1 | P2 | P3 (required)",\n'
            '  "category": "string (required)",\n'
            '  "title": "string (required, max 120 chars)",\n'
            '  "description": "string (required)",\n'
            '  "confidence": "high | medium | low",\n'
            '  "citations": [\n'
            "    {\n"
            '      "source_type": "file",\n'
            '      "source_path": "exact/path/to/document.pdf (required)",\n'
            '      "location": "Section X.Y or page number",\n'
            '      "exact_quote": "verbatim text from the document (REQUIRED — '
            'findings without exact_quote will be downgraded in severity)"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "**CRITICAL**: Every finding MUST have at least one citation with "
            "a valid `source_path` pointing to the actual file you read. "
            "Findings without citations will be downgraded in severity. "
            "For P0 and P1 findings, every citation MUST include `exact_quote` "
            "copied verbatim from the document.\n\n"
            "If a finding is based on aggregate data (e.g. revenue "
            "concentration from a reference spreadsheet), cite the specific "
            "reference file and the relevant cell, row, or tab.\n\n"
            "### Cross-Reference Entry Schema\n\n"
            "Cross-references compare a data point found in contracts against "
            "reference data (spreadsheets, financial statements, etc). Every "
            "entry in `cross_references` MUST be a JSON **object** with real "
            "values populated — do NOT create empty placeholders:\n"
            "```json\n"
            "{\n"
            '  "data_point": "ARR (required — the specific metric being compared)",\n'
            '  "data_type": "financial",\n'
            '  "contract_value": "$1.2M (actual value from the contract)",\n'
            '  "contract_source": {"file": "path/to/msa.pdf", "page": 5,\n'
            '    "quote": "Annual contract value of $1,200,000"},\n'
            '  "reference_value": "$1.1M (actual value from reference data)",\n'
            '  "reference_source": {"file": "path/to/cube.xlsx",\n'
            '    "tab": "Revenue", "row": "Row 42"},\n'
            '  "match_status": "mismatch",\n'
            '  "variance": "-8.3%",\n'
            '  "severity": "P2",\n'
            '  "interpretation": "Contract states $1.2M but revenue cube shows $1.1M"\n'
            "}\n"
            "```\n"
            "**Rules for cross-references:**\n"
            "- NEVER write a bare string — always a structured object.\n"
            "- NEVER create empty placeholders with `data_point: unknown` or "
            "empty values — these are filtered out and wasted.\n"
            "- ONLY create a cross-reference when you have an actual data point "
            "to compare with real values from two sources.\n"
            "- `contract_value` and `reference_value` MUST contain the actual "
            "values you found, not placeholders.\n"
            "- If you have no reference data to compare against, do NOT create "
            "a cross-reference — skip it.\n\n"
            "### Gap Entry Schema\n\n"
            "Every entry in `gaps` MUST be a JSON **object** (not a string):\n"
            "```json\n"
            "{\n"
            '  "missing_item": "string (required) — the missing document or data",\n'
            '  "gap_type": "Missing_Doc | Missing_Data | Ambiguous_Link '
            '| Unreadable | Contradiction | Data_Mismatch",\n'
            '  "priority": "P0 | P1 | P2 | P3",\n'
            '  "why_needed": "string — why this document/data is needed",\n'
            '  "risk_if_missing": "string — what could go wrong without it",\n'
            '  "request_to_company": "string — what to ask the target company",\n'
            '  "evidence": "string — where you noticed the gap",\n'
            '  "detection_method": "checklist | cross_reference | pattern_check | governance_resolution"\n'
            "}\n"
            "```\n"
            "NEVER write a bare string as a gap entry. "
            "If you cannot fill all fields, still write an object with at least "
            "`missing_item` and `gap_type`."
        )

    def _build_manifest_requirement(self, agent_name: str, customers: list[CustomerEntry]) -> str:
        return (
            "## COVERAGE MANIFEST\n\n"
            f"You MUST write: {self.run_dir}/findings/{agent_name}/"
            "coverage_manifest.json\n\n"
            f"Expected customers: {len(customers)}\n"
            "coverage_pct must be >= 0.90\n"
            "Every failed file must have fallback_attempted: true"
        )

    # ------------------------------------------------------------------
    # LLM robustness instructions (Issue #52, spec doc 22)
    # ------------------------------------------------------------------

    @staticmethod
    def robustness_instructions() -> str:
        """Return common LLM robustness mitigations appended to every specialist prompt.

        These instructions implement mitigations from ``docs/plan/22-llm-robustness.md``:
        - Structured output enforcement (AG-4, S-3)
        - Answer normalization (AG-8)
        - Citation format requirements (S-1, S-4)
        - Anti-hallucination guards (S-1, S-2)
        - Context window awareness (C-1, C-2)
        - Conflict handling (AG-3)
        - Completeness self-check (AG-6)
        - Not-Found protocol (AG-8)
        """
        return (
            "## ROBUSTNESS INSTRUCTIONS\n\n"
            "Follow these rules strictly for every finding, gap, and citation.\n\n"
            #
            # 1. Structured output enforcement
            #
            "### Structured Output\n\n"
            "Every finding MUST be a valid JSON object with a `citations` array "
            "containing at least one citation object:\n"
            "```json\n"
            "{\n"
            '  "severity": "P0 | P1 | P2 | P3 (required)",\n'
            '  "category": "string (required)",\n'
            '  "title": "string (required, max 120 chars)",\n'
            '  "description": "string (required)",\n'
            '  "confidence": "high | medium | low",\n'
            '  "citations": [\n'
            "    {\n"
            '      "source_type": "file",\n'
            '      "source_path": "exact/path/to/document.pdf (required)",\n'
            '      "location": "Section X.Y or page number",\n'
            '      "exact_quote": "verbatim text from document (REQUIRED for all findings)"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "Do NOT omit required fields. Do NOT produce findings with an empty "
            "or missing `citations` array — every finding MUST cite at least one "
            "source document.\n\n"
            #
            # 2. Answer normalization
            #
            "### Answer Normalization\n\n"
            "When a question requires a categorical answer, respond with exactly one of:\n"
            "  YES, NO, or NOT_ADDRESSED\n"
            "Do not use synonyms (e.g. 'N/A', 'Unknown', 'Maybe'). If the document "
            "does not address the question, answer NOT_ADDRESSED.\n\n"
            #
            # 3. Citation format
            #
            "### Citation Format\n\n"
            "Every citation object in the `citations` array MUST include:\n"
            "- source_type: 'file' (or 'web_research' with access_date)\n"
            "- source_path: exact path to the source file (required)\n"
            "- location: section heading, clause number, or page reference\n"
            "- exact_quote: verbatim text copied character-for-character "
            "(required for P0 and P1 findings)\n\n"
            "For aggregate/reference-data findings (e.g. revenue concentration "
            "from a spreadsheet), cite the reference file with tab/row details "
            "in the `location` field.\n\n"
            #
            # 4. Anti-hallucination
            #
            "### Anti-Hallucination Rules\n\n"
            "- Only cite text that appears VERBATIM in the source document.\n"
            "- Do NOT generate quotes from memory or paraphrase them.\n"
            "- Do NOT infer contract terms from general legal or industry knowledge.\n"
            "- Do NOT fabricate clauses, dollar amounts, dates, or party names.\n"
            "- If you are unsure whether text appears in the document, re-read the "
            "relevant section before citing it.\n\n"
            #
            # 5. Context window awareness
            #
            "### Context Window Awareness\n\n"
            "- If you encounter a file that appears truncated or cut off mid-sentence, "
            "note this in your finding with: 'WARNING: document appears truncated at page N'.\n"
            "- For large files (>120KB extracted text), use Grep to search for specific "
            "terms rather than reading the entire file.\n"
            "- Do NOT attempt to read all files into memory at once. Process one customer "
            "at a time.\n\n"
            #
            # 6. Conflict handling
            #
            "### Conflict Handling\n\n"
            "If two documents contain conflicting terms (e.g. different liability caps, "
            "different renewal dates, contradictory SLA commitments):\n"
            "- Cite BOTH documents with full citations.\n"
            "- Note the conflict explicitly in the finding description.\n"
            "- Do NOT silently choose one version over another.\n"
            "- Flag which document likely takes precedence based on document hierarchy "
            "(amendment > MSA > SOW), but note this is your assessment.\n\n"
            #
            # 7. Completeness self-check (AG-6)
            #
            "### Completeness Checklist\n\n"
            "BEFORE writing your coverage manifest, verify:\n"
            "1. ALL customers in your assigned list have been analyzed.\n"
            "2. ALL files for each customer have been read or searched.\n"
            "3. ALL required fields in every finding and gap are populated.\n"
            "4. EVERY finding has a non-empty `citations` array with at least one "
            "citation that includes `source_path`.\n"
            "5. ALL `exact_quote` values have been verified against the source document.\n"
            "6. Every P0/P1 finding has `exact_quote` in every citation.\n"
            "7. Every P0 finding has been re-read and its severity confirmed.\n"
            "8. ALL reference files assigned to you have been processed.\n\n"
            "### Quality Calibration Check\n\n"
            "Before finalizing, review your P0 and P1 findings critically:\n"
            "1. For each P0: Would an experienced M&A partner present this as a genuine deal-stopper?\n"
            "2. For each P1: Is this truly material? Does it require pre-close negotiation?\n"
            "3. Zero findings for a clean customer is acceptable. Do NOT manufacture findings.\n"
            "4. Fewer, well-calibrated findings > many poorly-calibrated ones.\n\n"
            #
            # 7b. Follow-up verification loop for P0/P1 (Issue #140)
            # Research: AG-6 finding shows 9.2% accuracy improvement from
            # mandatory follow-up prompts for high-value provisions.
            #
            "### MANDATORY P0/P1 Self-Verification Loop (CRITICAL)\n\n"
            "After drafting ALL findings for a customer, you MUST perform a "
            "structured self-verification for EVERY P0 and P1 finding before "
            "writing the output file. This step is NOT optional.\n\n"
            "For each P0/P1 finding, execute this 4-step verification:\n\n"
            "**Step 1 — Re-Read Source**: Go back to the source document cited in "
            "the finding. Use the Read tool to re-read the specific section. Do NOT "
            "rely on memory of what the document said.\n\n"
            "**Step 2 — Quote Verification**: Compare your `exact_quote` against "
            "the actual text you just re-read. If the quote does not appear verbatim, "
            "either fix it to match the actual text, or remove the finding entirely.\n\n"
            "**Step 3 — Severity Recheck**: Ask yourself:\n"
            "- P0: Is this genuinely a deal-stopper? Could a reasonable buyer walk away "
            "over this? If not, downgrade to P1.\n"
            "- P1: Does this require pre-close negotiation or price adjustment? If it's "
            "merely an observation, downgrade to P2.\n"
            "- Could there be mitigating factors (carve-outs, amendments, side letters) "
            "in other documents for this customer? If you haven't checked, search for them.\n\n"
            "**Step 4 — Context Check**: Re-read the 2 paragraphs before and after your "
            "cited quote. Check for:\n"
            "- Exceptions or carve-outs that modify the clause\n"
            "- Definitions section that changes the meaning of key terms\n"
            "- Amendment or superseding language\n"
            "If you find mitigating context, update the finding description and "
            "severity accordingly.\n\n"
            "After verification, mark each P0/P1 finding with:\n"
            '  "verified": true  (if all 4 steps pass)\n'
            '  "verified": false (if any step fails — also fix or downgrade the finding)\n\n'
            #
            # 8. Citation verification mandate (Issue #93)
            #
            "### Citation Verification (MANDATORY for P0 and P1)\n\n"
            "Before including any P0 or P1 finding in your output, call the "
            "`verify_citation` tool with the source_path and exact_quote.\n"
            "Only include the finding if verify_citation returns found: true.\n"
            "If verification fails, fix the quote to match the source text exactly, "
            "or downgrade the finding to P2.\n\n"
            #
            # 9. Not-Found protocol (AG-8)
            #
            "### Not-Found Protocol\n\n"
            "If you search for a specific clause or document and it genuinely does not "
            "exist in the customer's files, you MUST record this as a gap, NOT as a finding.\n\n"
            "DO NOT:\n"
            "- Fabricate clauses that you cannot find\n"
            "- Infer terms from general legal principles\n"
            "- Assume standard industry terms apply\n"
            "- Create findings based on what 'should' be in the contract\n\n"
            "DO:\n"
            "- Write a gap with gap_type: 'Not_Found'\n"
            "- Explain what you searched for and where you looked\n"
            "- Note which files you reviewed\n"
            "- Suggest what the missing clause means for the deal\n\n"
            #
            # 10. Red flag early detection (Issue #125)
            #
            "### Red Flag Priority Detection\n\n"
            "Prioritize scanning for these deal-killer patterns FIRST before "
            "detailed clause-by-clause analysis. If you find any of these, "
            "classify as P0 immediately and write the finding BEFORE continuing:\n\n"
            "1. **Active litigation** — lawsuits, regulatory actions, consent orders, "
            "pending enforcement. Look in legal summaries and board minutes.\n"
            "2. **IP ownership gaps** — work product not assigned to company, "
            "open-source license contamination (GPL in proprietary code), "
            "third-party IP claims.\n"
            "3. **Undisclosed material contracts** — documents referenced but "
            "not present in the data room. Flag as gap AND finding.\n"
            "4. **Customer concentration** — single customer >40% of revenue, "
            "or top 3 customers >70% of revenue.\n"
            "5. **Financial restatements** — corrections to prior financials, "
            "audit qualifications, going concern opinions.\n"
            "6. **Regulatory violations** — active or pending enforcement, "
            "consent decrees, material compliance failures.\n"
            "7. **Key-person risk** — single individual controls critical "
            "relationships, IP, or operations with no succession plan.\n"
            "8. **Debt covenant violations** — breach or near-breach of "
            "financial covenants in credit agreements."
        )

    # ------------------------------------------------------------------
    # Follow-up verification prompt (Issue #140, AG-6)
    # ------------------------------------------------------------------

    @staticmethod
    def build_follow_up_prompt(
        findings: list[dict[str, Any]],
        customer_name: str,
        agent_name: str,
    ) -> str:
        """Build a follow-up verification prompt for P0/P1 findings.

        Research (AG-6): mandatory follow-up for high-value provisions improves
        accuracy by 9.2%.  This prompt asks the agent to re-verify each critical
        finding against the source document.

        Returns an empty string if there are no P0/P1 findings to verify.
        """
        critical = [f for f in findings if str(f.get("severity", "")).upper() in ("P0", "P1")]
        if not critical:
            return ""

        lines: list[str] = [
            f"## FOLLOW-UP VERIFICATION — {customer_name} ({agent_name})\n",
            "You previously analyzed this customer and produced the following "
            "critical findings. For EACH finding below, you MUST:\n",
            "1. Re-read the cited source document using the Read tool.",
            "2. Verify the exact_quote appears verbatim in the document.",
            "3. Check for mitigating clauses (exceptions, carve-outs, amendments) in the surrounding paragraphs.",
            "4. Confirm or adjust the severity rating.\n",
            "Respond with a JSON array. For each finding, return:\n",
            "```json",
            "{",
            '  "original_title": "the finding title",',
            '  "verified": true | false,',
            '  "quote_confirmed": true | false,',
            '  "revised_severity": "P0 | P1 | P2 | P3",',
            '  "revision_reason": "why severity was kept or changed",',
            '  "mitigating_factors": "any carve-outs or context found"',
            "}",
            "```\n",
            "### Findings to Verify\n",
        ]

        for i, f in enumerate(critical, 1):
            title = f.get("title", "Untitled")
            severity = f.get("severity", "unknown")
            desc = f.get("description", "")[:300]
            citations = f.get("citations", [])
            source = ""
            quote = ""
            if citations and isinstance(citations, list):
                cit = citations[0] if isinstance(citations[0], dict) else {}
                source = cit.get("source_path", "unknown")
                quote = cit.get("exact_quote", "")[:200]

            lines.append(f"**Finding {i}**: [{severity}] {title}")
            lines.append(f"  Description: {desc}")
            lines.append(f"  Source: {source}")
            if quote:
                lines.append(f'  Quote: "{quote}"')
            lines.append("")

        return "\n".join(lines)
