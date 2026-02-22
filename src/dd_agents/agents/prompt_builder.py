"""Prompt builder -- assembles self-contained agent prompts.

Constructs complete prompts from deal config, customer lists, reference files,
domain rules, and output format requirements.  Implements token estimation and
customer batching when prompts exceed the context budget.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.models.config import DealConfig
    from dd_agents.models.inventory import CustomerEntry, ReferenceFile

# ---------------------------------------------------------------------------
# Agent type enumeration
# ---------------------------------------------------------------------------


class AgentType(StrEnum):
    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"
    JUDGE = "judge"
    REPORTING_LEAD = "reportinglead"


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
        "Write gap files for EVERY missing document detected."
    ),
    AgentType.FINANCE: (
        "Cross-reference every customer's contract values against the Revenue Cube and any "
        "financial reference data. Flag ARR mismatches >5%. Check discount levels against "
        "Pricing Guidelines. Identify one-time fees incorrectly counted as recurring ARR. "
        "Flag minimum commitment shortfalls. IMPORTANT: You MUST analyze ALL customers, not "
        "just those with dedicated financial documents. For customers with only contract files, "
        "extract financial terms from their contracts and cross-reference against reference "
        "file data. Gap detection: Check for missing financial verification, missing pricing "
        "documentation, unexplained revenue variances. Write gap files."
    ),
    AgentType.COMMERCIAL: (
        "Evaluate renewal mechanics (auto vs manual, notice periods, penalties). Cross-reference "
        "contract terms against Customer Health Scores for churn risk. Compare pricing against "
        "rate cards. Flag SLA commitments and service credit exposure. Gap detection: Check for "
        "missing SOWs, missing order forms, missing renewal evidence, unsigned documents. "
        "Write gap files for EVERY missing document detected."
    ),
    AgentType.PRODUCTTECH: (
        "Validate DPA adequacy and subprocessor lists. Cross-reference security claims against "
        "SOC2/compliance evidence. Check technical SLA feasibility. Flag data residency "
        "restrictions and migration obligations. IMPORTANT: You MUST analyze ALL customers, "
        "not just those with dedicated tech/security documents. For every customer's contracts, "
        "extract technology-related clauses. Gap detection: Check for missing DPAs, missing "
        "security addenda, missing SLA documentation, missing architecture/integration specs. "
        "Write gap files."
    ),
}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Assembles self-contained agent prompts from templates and runtime data."""

    def __init__(
        self,
        project_dir: Path,
        run_dir: Path,
        run_id: str,
    ) -> None:
        self.project_dir = project_dir
        self.run_dir = run_dir
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Specialist prompt
    # ------------------------------------------------------------------

    def build_specialist_prompt(
        self,
        agent_name: str,
        customers: list[CustomerEntry],
        reference_files: list[ReferenceFile] | None = None,
        deal_config: DealConfig | None = None,
        text_dir: str | None = None,
    ) -> str:
        """Build a complete, self-contained specialist prompt.

        Parameters
        ----------
        agent_name:
            One of ``legal``, ``finance``, ``commercial``, ``producttech``.
        customers:
            List of :class:`CustomerEntry` objects -- every customer the agent
            must analyse.
        reference_files:
            Reference files routed to this agent.  May be ``None``.
        deal_config:
            The loaded :class:`DealConfig`.  May be ``None`` for tests.
        text_dir:
            Path to the extracted text directory (e.g.
            ``_dd/forensic-dd/index/text``).  Used to construct pointers.
        """
        sections: list[str] = []

        # 1. Role & deal context
        sections.append(self._build_role_section(agent_name, deal_config))

        # 2. Customer list
        sections.append(self._build_customer_list(agent_name, customers))

        # 3. Reference files
        sections.append(self._build_reference_section(reference_files or []))

        # 4. Specialist focus
        try:
            agent_type = AgentType(agent_name)
        except ValueError:
            agent_type = None
        if agent_type and agent_type in SPECIALIST_FOCUS:
            sections.append(f"## YOUR SPECIALIST FOCUS\n\n{SPECIALIST_FOCUS[agent_type]}")

        # 5. Output format requirements
        sections.append(self._build_output_format(agent_name))

        # 6. Manifest requirement
        sections.append(self._build_manifest_requirement(agent_name, customers))

        return "\n\n---\n\n".join(sections)

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
    # Reporting Lead prompt
    # ------------------------------------------------------------------

    def build_reporting_lead_prompt(
        self,
        findings_dir: str | Path | None = None,
        schema_path: str | Path | None = None,
        deal_config: DealConfig | None = None,
    ) -> str:
        """Build the Reporting Lead agent prompt."""
        sections: list[str] = []

        sections.append(
            "# REPORTING LEAD AGENT\n\n"
            "You are the Reporting Lead for forensic M&A due diligence.\n"
            "You do NOT perform new analysis. Your job is to:\n"
            "1. Merge and deduplicate specialist findings\n"
            "2. Build the numerical manifest\n"
            "3. Run the 5-layer numerical audit\n"
            "4. Generate the 14-sheet Excel report from report_schema.json\n"
            "5. Build the report diff (if prior run exists)\n\n"
            f"Run ID: {self.run_id}"
        )

        if findings_dir:
            sections.append(f"## FINDINGS DIRECTORY\n\n{findings_dir}")

        if schema_path:
            sections.append(f"## REPORT SCHEMA\n\n{schema_path}")

        if deal_config:
            sections.append(f"## DEAL CONTEXT\n\nBuyer: {deal_config.buyer.name}\nTarget: {deal_config.target.name}")

        sections.append(
            "## OUTPUT\n\n"
            f"Write merged findings to: {self.run_dir}/findings/merged/\n"
            f"Write report to: {self.run_dir}/report/"
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
    def batch_customers(
        customers: list[CustomerEntry],
        max_tokens: int = 80_000,
        tokens_per_customer: int = 50,
        overhead_tokens: int = 5_000,
    ) -> list[list[CustomerEntry]]:
        """Split *customers* into batches that each fit within *max_tokens*.

        Parameters
        ----------
        customers:
            Full customer list.
        max_tokens:
            Maximum tokens per batch (default 80 000 -- 80 % of 200k context).
        tokens_per_customer:
            Estimated tokens per customer entry in the prompt.
        overhead_tokens:
            Fixed token overhead for prompt preamble, rules, etc.

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

        max_per_batch = max(1, available // max(1, tokens_per_customer))

        batches: list[list[CustomerEntry]] = []
        for i in range(0, len(customers), max_per_batch):
            batches.append(customers[i : i + max_per_batch])
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
        return "\n".join(lines)

    def _build_customer_list(self, agent_name: str, customers: list[CustomerEntry]) -> str:
        lines = [
            "## ALL CUSTOMERS (you MUST process every one, every file)",
            "",
        ]
        for idx, cust in enumerate(customers, 1):
            lines.append(f"Customer {idx}: {cust.name} (safe_name: {cust.safe_name})")
            lines.append(f"  Path: {cust.path}")
            if cust.files:
                lines.append(f"  Files ({cust.file_count}):")
                for fp in cust.files:
                    lines.append(f"    - {fp}")
            lines.append("")

        lines.append(
            f"IMPORTANT: Use the exact safe_name provided above as the filename "
            f"for your output JSON.\n"
            f"Write: {self.run_dir}/findings/{agent_name}/{{safe_name}}.json\n\n"
            f"TOTAL: {len(customers)} customers. You must process every single one."
        )
        return "\n".join(lines)

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
            "```"
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
