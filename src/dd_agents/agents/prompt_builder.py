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
    """All agent roles in the pipeline: 4 specialists + judge + reporting lead."""

    LEGAL = "legal"
    FINANCE = "finance"
    COMMERCIAL = "commercial"
    PRODUCTTECH = "producttech"
    JUDGE = "judge"
    REPORTING_LEAD = "reporting_lead"


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

    def build_specialist_prompt(
        self,
        agent_name: str,
        customers: list[CustomerEntry] | list[str],
        reference_files: list[ReferenceFile] | None = None,
        deal_config: DealConfig | dict[str, Any] | None = None,
        text_dir: str | None = None,
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
        text_dir:
            Path to the extracted text directory (e.g.
            ``_dd/forensic-dd/index/text``).  Used to construct pointers.
        """
        deal_config = self._coerce_deal_config(deal_config)
        customers = self._coerce_customers(customers)
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

        # 7. Robustness instructions (Issue #52 -- spec doc 22)
        sections.append(self.robustness_instructions())

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
        deal_config: DealConfig | dict[str, Any] | None = None,
    ) -> str:
        """Build the Reporting Lead agent prompt."""
        deal_config = self._coerce_deal_config(deal_config)
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
    def _estimate_customer_tokens(customer: CustomerEntry) -> int:
        """Estimate the prompt tokens one customer entry will occupy.

        Accounts for the header lines (name, safe_name, path, file count)
        plus one line per file in the listing.
        """
        # Fixed header: "### Customer: ...", safe_name, path, "Files (N):"
        chars = 160
        for fp in customer.files or []:
            chars += len(fp) + 8  # "    - {fp}\n"
        return max(1, chars // 4)

    @staticmethod
    def batch_customers(
        customers: list[CustomerEntry],
        max_tokens: int = 40_000,
        tokens_per_customer: int | None = None,
        overhead_tokens: int = 5_000,
        max_per_batch: int = 20,
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
            est = PromptBuilder._estimate_customer_tokens(customer)
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
            "Every finding MUST be a valid JSON object matching this schema:\n"
            "```json\n"
            "{\n"
            '  "customer_safe_name": "string (required)",\n'
            '  "severity": "P0 | P1 | P2 | P3 (required)",\n'
            '  "title": "string (required)",\n'
            '  "description": "string (required)",\n'
            '  "file_path": "string (required)",\n'
            '  "page": "integer or null",\n'
            '  "section_ref": "string or null",\n'
            '  "exact_quote": "string (required)"\n'
            "}\n"
            "```\n"
            "Do NOT omit required fields. Do NOT add fields not in the schema.\n\n"
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
            "Every citation MUST include ALL of these fields:\n"
            "- file_path: exact path to the source file\n"
            "- page: page number where the text appears (integer, or null if not applicable)\n"
            "- section_ref: section heading or clause number (e.g. 'Section 12.3')\n"
            "- exact_quote: the verbatim text from the document, copied character-for-character\n\n"
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
            "4. ALL exact_quote values have been verified against the source document.\n"
            "5. Every P0 finding has been re-read and its severity confirmed.\n"
            "6. Every customer with zero findings has been re-checked for missed issues.\n"
            "7. ALL reference files assigned to you have been processed.\n\n"
            "YOU MAY HAVE MISSED CRITICAL INFORMATION. Go back and re-examine any "
            "customers where you produced fewer findings than expected relative to "
            "their file count.\n\n"
            #
            # 8. Not-Found protocol (AG-8)
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
            "- Suggest what the missing clause means for the deal"
        )
