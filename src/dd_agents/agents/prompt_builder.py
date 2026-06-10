"""Prompt builder -- assembles self-contained agent prompts.

Constructs complete prompts from deal config, subject lists, reference files,
domain rules, and output format requirements.  Implements token estimation and
subject batching when prompts exceed the context budget.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.agents.prompt_constants import (
    FINDING_SCHEMA_BLOCK,
    JSON_OUTPUT_CONSTRAINT,
)
from dd_agents.agents.prompts.loader import PROMPTS_DIR, load_builtin_specialist
from dd_agents.agents.severity_thresholds import (
    ARR_MISMATCH_P1_PCT,
    COC_AUTOTERM_REVENUE_PCT,
    COC_REVENUE_PCT,
)
from dd_agents.models.enums import AgentName
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1

logger = logging.getLogger(__name__)

#: Directory of the bundled per-specialist prompt markdown files.
PROMPTS_SPECIALISTS_DIR = PROMPTS_DIR / "specialists"

if TYPE_CHECKING:
    from dd_agents.models.config import AgentCustomization, DealConfig
    from dd_agents.models.inventory import ReferenceFile, SubjectEntry

# ---------------------------------------------------------------------------
# Agent type enumeration — canonical definition lives in ``models.enums.AgentName``.
# ``AgentType`` is kept as a public alias for backward compatibility.
# ---------------------------------------------------------------------------

AgentType = AgentName


# ---------------------------------------------------------------------------
# Focus area instructions per specialist
# ---------------------------------------------------------------------------

#: Per-specialist focus instructions. Source of truth is the editable markdown
#: at ``agents/prompts/specialists/{agent}.md`` (``## Specialist Focus`` section);
#: severity-threshold placeholders are resolved from ``severity_thresholds.py``.
#: Built loader-backed so the assembled prompt is byte-identical to the former
#: hardcoded dict while the prose lives in markdown an M&A reviewer can edit.
SPECIALIST_FOCUS: dict[AgentType, str] = {
    _at: load_builtin_specialist(_at.value).specialist_focus
    for _at in AgentType
    if (PROMPTS_SPECIALISTS_DIR / f"{_at.value}.md").is_file()
}


# ---------------------------------------------------------------------------
# Deal-config customization helper
# ---------------------------------------------------------------------------


def _get_agent_customization(
    deal_config: DealConfig | None,
    agent_name: str,
) -> AgentCustomization | None:
    """Retrieve per-agent customization from the deal config, if any.

    Returns ``None`` when no customization is configured for *agent_name*.
    """
    if deal_config is None:
        return None
    forensic_dd = getattr(deal_config, "forensic_dd", None)
    specialists_cfg = getattr(forensic_dd, "specialists", None)
    customizations: dict[str, Any] = getattr(specialists_cfg, "customizations", {}) or {}
    cust: object = customizations.get(agent_name)
    if cust is None:
        return None
    # If the value is already an AgentCustomization, return directly.
    from dd_agents.models.config import AgentCustomization as _AgentCustomization

    if isinstance(cust, _AgentCustomization):
        return cust
    return None


def _strip_trailing_citation_mandate(text: str) -> str:
    """Remove a trailing ``### MANDATORY Citation Requirements`` block.

    Each agent's ``domain_robustness()`` text ends with the citation mandate
    (via ``build_citation_mandate``). Since the non-removable safety floor
    appends the authoritative, domain-specific mandate last, injecting the
    domain-guidance copy too duplicated the block. Trim it here so the prompt
    carries the mandate exactly once (the floor's copy). The descriptor method
    itself is unchanged (introspection/tests still see the full text).
    """
    marker = "### MANDATORY Citation Requirements"
    idx = text.find(marker)
    if idx == -1:
        return text
    return text[:idx].rstrip()


def render_customization(
    base_prompt: str,
    cust: AgentCustomization | None,
    agent_name: str,
) -> str:
    """Append a resolved :class:`AgentCustomization`'s content to *base_prompt*.

    Pure renderer (no config lookup). Used by both the deal-config path and the
    ``dd-config/`` markdown path, so the two surfaces render identically.

    - ``persona``: prepended PERSONA OVERRIDE section (safety floor still last).
    - ``extra_focus_areas``: appended as a bullet list.
    - ``extra_instructions``: appended verbatim.
    - ``severity_overrides``: injected as calibration rules.

    Returns *base_prompt* unchanged when *cust* is ``None`` or empty.
    """
    if cust is None:
        return base_prompt

    additions: list[str] = []

    if cust.persona:
        # KISS persona replace: prepend a PERSONA OVERRIDE section. The safety
        # floor still appends last (see build_specialist_prompt), so this is safe.
        additions.append(f"## PERSONA OVERRIDE ({agent_name})\n\n{cust.persona}")

    if cust.extra_focus_areas:
        lines = [f"## ADDITIONAL FOCUS AREAS ({agent_name})\n"]
        for area in cust.extra_focus_areas:
            lines.append(f"- {area}")
        additions.append("\n".join(lines))

    if cust.extra_instructions:
        additions.append(f"## ADDITIONAL INSTRUCTIONS ({agent_name})\n\n{cust.extra_instructions}")

    if cust.severity_overrides:
        lines = [f"## SEVERITY OVERRIDES ({agent_name})\n"]
        lines.append("Apply these severity calibration overrides for this deal:")
        for category, severity in cust.severity_overrides.items():
            lines.append(f"- {category}: {severity}")
        additions.append("\n".join(lines))

    if not additions:
        return base_prompt

    return base_prompt + "\n\n---\n\n" + "\n\n---\n\n".join(additions)


def apply_deal_config_customizations(
    base_prompt: str,
    deal_config: DealConfig | None,
    agent_name: str,
) -> str:
    """Apply *deal_config* inline customizations to a specialist prompt.

    Back-compat wrapper: reads
    ``deal_config.forensic_dd.specialists.customizations[agent_name]`` and
    renders it via :func:`render_customization`. The ``dd-config/`` markdown
    path is applied separately in :meth:`PromptBuilder.build_specialist_prompt`
    via :func:`resolve_agent_customization`.
    """
    return render_customization(base_prompt, _get_agent_customization(deal_config, agent_name), agent_name)


def resolve_agent_customization(
    project_dir: Path | None,
    deal_config: DealConfig | None,
    agent_name: str,
) -> AgentCustomization | None:
    """Fold ``dd-config/`` markdown + deal-config inline into one customization.

    This is the single entry point that makes the documented ``dd-config/``
    workflow actually reach the assembled prompt (audit fix). Layer order
    (lowest→highest precedence): bundled profile ``extends`` chain →
    ``{project_dir}/dd-config/agents/{agent}.md`` → deal-config inline
    ``customizations[agent]``. Returns ``None`` when nothing customizes *agent*.

    Falls back to the deal-config-only customization if the loader is
    unavailable or errors, so a malformed ``dd-config/`` never breaks a run.
    """
    deal_cust = _get_agent_customization(deal_config, agent_name)
    if project_dir is None:
        return deal_cust

    dd_config_dir = Path(project_dir) / "dd-config"
    if not dd_config_dir.is_dir():
        return deal_cust  # no dd-config/ → inline-only (back-compat)

    try:
        from dd_agents.customization.loader import resolve_chain

        profiles_dir = Path(__file__).parent.parent / "customization" / "profiles"
        resolved = resolve_chain(agent_name, dd_config_dir, deal_cust, profiles_dir)
        return resolved.customization
    except Exception:  # noqa: BLE001 — never let customization break prompt assembly
        logger.warning("dd-config resolution failed for agent '%s'; using inline only", agent_name, exc_info=True)
        return deal_cust


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Assembles self-contained agent prompts from templates and runtime data."""

    # Prompt version tracking (Issue #146) — bump on prompt changes
    # 2.1.0: HR specialist prompt — surface each workforce risk as a distinct
    # finding (removed the "defer to Legal" suppression; added granularity rule).
    # 2.2.0: ESG specialist prompt — added current EU/sustainability keyword
    # aliases (EU Taxonomy, EUDR, Scope 4, avoided emissions, just transition).
    # 2.3.0: Finance specialist prompt — added Financial Model Integrity guidance
    # (formula-audit findings: hardcoded overrides, circular refs, broken links)
    # paired with the read_office formula-integrity section (Issue #194).
    PROMPT_VERSION: str = "2.3.0"

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
        self.max_listed_files: int = self.MAX_LISTED_FILES
        # Build-time preamble cache (audit §4.1a).  The static preamble
        # (role + deal context) is identical across batches in a run — only
        # the subject list changes — so memoize it per (agent, config) on the
        # instance.  Byte-identity is preserved because the cached string is
        # the exact output of the deterministic builder for the same inputs;
        # per-call layers (customizations, safety floor) still apply unchanged.
        self._role_section_cache: dict[str, str] = {}

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
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not coerce deal_config to DealConfig: %s", exc)
                return None

        return None

    @staticmethod
    def _coerce_subjects(subjects: list[SubjectEntry] | list[str] | list[Any]) -> list[SubjectEntry]:
        """Ensure *subjects* is a list of :class:`SubjectEntry` objects.

        When ``_run_specialist`` falls back to ``build_prompt()``, subjects
        may be plain safe-name strings from ``PipelineState.subject_safe_names``.
        This converts them to minimal :class:`SubjectEntry` instances so that
        ``_build_subject_list`` can access ``.name`` / ``.safe_name`` etc.
        """
        if not subjects:
            return []

        first = subjects[0]
        if hasattr(first, "safe_name"):
            return subjects  # type: ignore[return-value]

        # Plain strings — convert to minimal SubjectEntry objects.
        from dd_agents.models.inventory import SubjectEntry as _SubjectEntry

        return [_SubjectEntry(group="", name=str(s), safe_name=str(s), path=str(s)) for s in subjects]

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
            f"Examples: undisclosed fraud, regulatory prohibition, auto-termination of "
            f">{COC_AUTOTERM_REVENUE_PCT}% revenue on CoC with no cure, material IP ownership dispute.",
            "Anti-examples: routine CoC notifications, standard consent requirements, approaching "
            "renewal deadlines, TfC clauses (valuation concern, not deal-stopper), "
            "competitor-only CoC restrictions (buyer rarely competes with customers).",
            "",
            "### P1 — Material Risk Requiring Pre-Close Negotiation",
            "Issues that require specific deal protection (indemnity, escrow, price adjustment) "
            "but do not fundamentally threaten the deal.",
            f"Examples: consent-required assignment for >{COC_REVENUE_PCT}% revenue customers, "
            f"ARR mismatch >{ARR_MISMATCH_P1_PCT}%, "
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
        elif deal_type in ("asset_sale", "asset_purchase"):
            lines.extend(
                [
                    "### Deal-Type Context: Asset Sale / Asset Purchase",
                    f"This is a {deal_type}. Key calibration rules:",
                    "- Only PURCHASED ASSETS transfer — liabilities, contracts, and IP not "
                    "explicitly listed in the APA do NOT transfer. Flag ambiguous asset "
                    "schedules as P1.",
                    "- Contract assignability is critical — each customer/vendor contract "
                    "needs consent or court order to assign. Non-assignable contracts "
                    "covering >5% revenue are P0.",
                    "- Excluded liabilities remain with the seller — but verify the APA "
                    "clearly delineates assumed vs. excluded. Ambiguity is P1.",
                    "- Employee transfer is selective — buyer chooses which employees to "
                    "offer positions. Flag key-person risk if critical staff are not "
                    "confirmed as transferring (P1).",
                    "- IP must be explicitly scheduled — any IP not listed in purchased "
                    "assets does NOT transfer. Missing IP schedules for core technology "
                    "are P0.",
                    "- If the sale is out of receivership/bankruptcy, assets vest free and "
                    "clear via court order — pre-existing liens are less relevant, but "
                    "court approval is a closing condition (P0 if at risk).",
                    "- Cure costs for defaulted contracts may be required — flag material cure obligations as P1.",
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
        subjects: list[SubjectEntry] | list[str],
        reference_files: list[ReferenceFile] | None = None,
        deal_config: DealConfig | dict[str, Any] | None = None,
        file_precedence: dict[str, Any] | None = None,
    ) -> str:
        """Build a complete, self-contained specialist prompt.

        Parameters
        ----------
        agent_name:
            One of ``legal``, ``finance``, ``commercial``, ``producttech``.
        subjects:
            List of :class:`SubjectEntry` objects -- every subject the agent
            must analyse.  Plain strings (safe_names) are also accepted and
            automatically coerced to minimal :class:`SubjectEntry` objects.
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
        subjects = self._coerce_subjects(subjects)
        sections: list[str] = []

        # Section ordering is intentional (audit §3.2, highest-recall tail):
        # the subject/file listing sits in the MIDDLE (section 2) while the
        # severity rubric (5b), output format (6), and citation/robustness
        # mandates (8) come LAST so the model reads them most recently. The
        # non-removable safety floor is appended after all sections (below) and
        # must remain the true last layer — do not move it.
        # 1. Role & deal context (memoized per agent+config — audit §4.1a;
        #    byte-identical to the un-cached build for the same inputs).
        sections.append(self._cached_role_section(agent_name, deal_config))

        # 2. Subject list (with optional precedence annotations)
        sections.append(self._build_subject_list(agent_name, subjects, file_precedence))

        # 2b. Document precedence rules (Issue #163)
        if file_precedence:
            sections.append(self._build_precedence_rules())

        # 3. File access instructions (Issue #87)
        sections.append(self._build_file_access_instructions())

        # 4. Reference files
        sections.append(self._build_reference_section(reference_files or []))

        # 5. Specialist focus (hardcoded SPECIALIST_FOCUS dict is primary;
        #    registry descriptor fields supplement when available)
        try:
            agent_type = AgentType(agent_name)
        except ValueError:
            agent_type = None
        if agent_type and agent_type in SPECIALIST_FOCUS:
            sections.append(f"## YOUR SPECIALIST FOCUS\n\n{SPECIALIST_FOCUS[agent_type]}")

        # 5a. Supplement from AgentRegistry descriptor (if fields are non-empty)
        try:
            from dd_agents.agents.registry import AgentRegistry

            descriptor = AgentRegistry.get(agent_name)
            # NOTE: descriptor.citation_examples is the citation mandate; it is
            # NOT injected as its own section here because the non-removable
            # safety floor (appended last) already carries the authoritative,
            # domain-specific mandate. Injecting it here too produced the
            # citation block 3x in the assembled prompt (audit finding). The
            # field is retained on the descriptor for introspection/describe.

            # 5a-bis. Canonical focus areas (§3.1). The descriptor carries the
            # authoritative focus_areas list; surface it (humanized) so the agent
            # references the canonical taxonomy alongside the hand-written
            # SPECIALIST_FOCUS sentence above.
            if descriptor.focus_areas:
                focus_lines = "\n".join(f"- {area.replace('_', ' ')}" for area in descriptor.focus_areas)
                sections.append(f"## YOUR FOCUS AREAS (canonical)\n\n{focus_lines}")

            # 5b. Domain-specific extraction guidance (descriptor field was captured at
            # registration but never injected — audit §2.2). This carries each agent's
            # keyword/extraction playbook (e.g. Legal CoC subtypes) into the prompt.
            # Strip the trailing citation mandate the domain_robustness text ends
            # with — the safety floor is the single authoritative copy (dedup).
            if descriptor.domain_robustness:
                sections.append(_strip_trailing_citation_mandate(descriptor.domain_robustness))
        except KeyError:
            pass  # Unknown agent — no descriptor supplement

        # 5b. Severity calibration rubric (accepts both DealConfig and raw dict)
        sections.append(self._build_severity_rubric(deal_config or raw_deal_config))

        # 6. Output format requirements
        sections.append(self._build_output_format(agent_name))

        # 7. Manifest requirement
        sections.append(self._build_manifest_requirement(agent_name, subjects))

        # 8. Robustness instructions (Issue #52 -- spec doc 22)
        sections.append(self.robustness_instructions())

        prompt = "\n\n---\n\n".join(sections)

        # Safety guard: if the assembled prompt exceeds the model context
        # (200K tokens ≈ 800K chars), truncate the subject file listing.
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
                self.max_listed_files,
                self.max_listed_files // 2,
            )
            self.max_listed_files = max(50, self.max_listed_files // 2)
            sections[1] = self._build_subject_list(agent_name, subjects, file_precedence)
            prompt = "\n\n---\n\n".join(sections)

        # Apply customizations (persona / focus / instructions / severity) as a
        # pass over the assembled prompt. This folds the ``dd-config/`` markdown
        # path (profiles via ``extends`` → dd-config/agents/{agent}.md) together
        # with the deal-config inline form, so BOTH surfaces reach the prompt.
        # User content is appended here, so the safety floor (next) lands
        # structurally AFTER it and cannot be overridden. NOTE: the truncation
        # guard above re-joins only ``sections`` — the floor is appended
        # afterwards and is therefore outside the truncation boundary.
        resolved_cust = resolve_agent_customization(self.project_dir, deal_config, agent_name)
        prompt = render_customization(prompt, resolved_cust, agent_name)

        # Non-removable safety floor — TRUE last layer (audit AD-2 / §7.1).
        from dd_agents.agents.prompt_constants import assemble_safety_floor

        prompt = f"{prompt}\n\n---\n\n{assemble_safety_floor(agent_name)}"

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

        sections.append(
            f"## OUTPUT\n\n"
            f"Write quality_scores.json to: {self.run_dir}/judge/quality_scores.json\n\n"
            "You MUST output valid JSON matching this exact schema:\n\n"
            "```json\n"
            "{\n"
            f'  "run_id": "{self.run_id}",\n'
            '  "skill": "forensic-dd",\n'
            '  "agent_scores": {\n'
            '    "legal": {\n'
            '      "score": 85,\n'
            '      "findings_reviewed": 10,\n'
            '      "findings_total": 25,\n'
            '      "pass": 8,\n'
            '      "partial": 1,\n'
            '      "fail": 1,\n'
            '      "dimensions": {\n'
            '        "citation_verification": 90,\n'
            '        "contextual_validation": 85,\n'
            '        "financial_accuracy": 80,\n'
            '        "cross_agent_consistency": 75,\n'
            '        "completeness": 95\n'
            "      },\n"
            '      "quality_tier": "full_pass"\n'
            "    }\n"
            "    // ... repeat for finance, commercial, producttech\n"
            "  },\n"
            '  "unit_scores": {\n'
            '    "subject_name": { "score": 80, "agents_reviewed": 4, "contradictions": 0 }\n'
            "  },\n"
            '  "overall_quality": 82,\n'
            '  "iteration_round": 1,\n'
            '  "agents_below_threshold": [],\n'
            '  "spot_checks": [\n'
            "    {\n"
            '      "finding_id": "forensic-dd_legal_subject_0001",\n'
            '      "agent": "legal",\n'
            '      "analysis_unit": "subject_name",\n'
            '      "severity": "P1",\n'
            '      "dimension": "citation_verification",\n'
            '      "result": "pass",\n'
            '      "notes": "Citation verified in source document"\n'
            "    }\n"
            "  ],\n"
            '  "contradictions": [\n'
            "    {\n"
            '      "analysis_unit": "subject_name",\n'
            '      "agents": ["legal", "finance"],\n'
            '      "fact_in_dispute": "Contract expiration date",\n'
            '      "resolution": "Legal agent version is correct per MSA §4.2",\n'
            '      "winning_agent": "legal"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n\n"
            "CRITICAL RULES:\n"
            "- agent_scores MUST contain an entry for EACH of: legal, finance, commercial, producttech\n"
            "- Each score is 0-100; quality_tier is one of: full_pass, advisory, conditional, fail\n"
            "- spot_checks dimension is one of: citation_verification, contextual_validation, "
            "financial_accuracy, cross_agent_consistency, completeness\n"
            "- spot_checks result is one of: pass, partial, fail\n"
            "- " + JSON_OUTPUT_CONSTRAINT
        )

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
            '- "key_concerns": List of key concern strings\n\n' + JSON_OUTPUT_CONSTRAINT
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
            "findings for the deal team. Your role is to apply professional "
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
            "subject. In most deals this is P3.\n"
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
                entity = f.get("entity", f.get("_subject", ""))
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
                entity = f.get("entity", f.get("_subject", ""))
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
            '  "go_no_go_rationale": "Concise paragraph explaining recommendation",\n'
            '  "executive_narrative": "2-3 paragraph DD summary for the deal team",\n'
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
            "```\n" + JSON_OUTPUT_CONSTRAINT
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
    def _estimate_subject_tokens(
        subject: SubjectEntry,
        text_dir: Path | None = None,
    ) -> int:
        """Estimate the prompt tokens one subject entry will occupy.

        When *text_dir* is provided, measures actual extracted text sizes
        from ``<text_dir>/<filename>.md`` files.  This produces accurate
        token estimates based on real content rather than path-length
        heuristics.

        Without *text_dir*, falls back to header + path-length estimation.
        """
        # Fixed header: "### Subject: ...", safe_name, path, "Files (N):"
        chars = 160
        files = subject.files or []

        if text_dir is not None:
            # Measure actual extracted text sizes
            for fp in files:
                # Extraction writes <filename>.md in text_dir
                text_file = text_dir / (Path(fp).name + ".md")
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
    def batch_subjects(
        subjects: list[SubjectEntry],
        max_tokens: int = 40_000,
        tokens_per_subject: int | None = None,
        overhead_tokens: int = 5_000,
        max_per_batch: int = 20,
        text_dir: Path | None = None,
    ) -> list[list[SubjectEntry]]:
        """Split *subjects* into batches that each fit within *max_tokens*.

        Parameters
        ----------
        subjects:
            Full subject list.
        max_tokens:
            Maximum tokens per batch (default 40 000 -- ~20 % of 200k context,
            leaving ample room for agent tool calls and file reads).
        tokens_per_subject:
            Estimated tokens per subject entry in the prompt.  When ``None``
            (default), computed automatically from the actual file listings
            in each subject entry.
        overhead_tokens:
            Fixed token overhead for prompt preamble, rules, etc.
        max_per_batch:
            Hard cap on subjects per batch (default 20).  Prevents
            oversized batches when file listings are unavailable and
            the token estimation underestimates prompt size.
        text_dir:
            Path to the extracted text directory.  When provided, token
            estimation uses actual file sizes instead of path-length
            heuristics.

        Returns
        -------
        A list of subject batches.  If all subjects fit in one batch, returns
        a single-element list.
        """
        if not subjects:
            return []

        available = max_tokens - overhead_tokens
        if available <= 0:
            available = max_tokens

        # When tokens_per_subject is explicit, use uniform splitting.
        if tokens_per_subject is not None:
            cap = max(1, available // max(1, tokens_per_subject))
            cap = min(cap, max_per_batch)
            batches: list[list[SubjectEntry]] = []
            for i in range(0, len(subjects), cap):
                batches.append(subjects[i : i + cap])
            return batches

        # Data-driven greedy batching: pack subjects until the batch is full.
        batches = []
        current_batch: list[SubjectEntry] = []
        current_tokens = 0

        for subject in subjects:
            est = PromptBuilder._estimate_subject_tokens(subject, text_dir=text_dir)
            if current_batch and (current_tokens + est > available or len(current_batch) >= max_per_batch):
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0
            current_batch.append(subject)
            current_tokens += est

        if current_batch:
            batches.append(current_batch)

        return batches

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cached_role_section(self, agent_name: str, deal_config: DealConfig | None) -> str:
        """Return the role/deal-context section, memoized per (agent, config).

        Build-time preamble cache (audit §4.1a): within a run the static
        preamble does not vary across batches, so the deterministic output of
        :meth:`_build_role_section` is cached on the instance.  The cache key
        folds the agent name, run id, and a stable digest of the deal config so
        distinct configs never collide.  The returned string is byte-identical
        to calling :meth:`_build_role_section` directly.
        """
        if deal_config is None:
            config_key = "none"
        else:
            dump = getattr(deal_config, "model_dump_json", None)
            try:
                config_key = dump(exclude_none=False) if callable(dump) else repr(deal_config)
            except Exception:  # noqa: BLE001 — never let cache keying break prompt assembly
                config_key = repr(deal_config)
        key = f"{agent_name}\x00{self.run_id}\x00{config_key}"
        cached = self._role_section_cache.get(key)
        if cached is not None:
            return cached
        built = self._build_role_section(agent_name, deal_config)
        self._role_section_cache[key] = built
        return built

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
            # Output language (audit AD-4): only emit when non-default so the
            # English-default prompt is byte-unchanged for existing configs.
            output_language = getattr(deal_config.deal, "output_language", "en")
            if output_language and output_language != "en":
                lines.append(
                    f"Output language: write all finding prose in '{output_language}'. "
                    "Read source documents in any language and quote verbatim in the "
                    "original language for citations."
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

    # Maximum files to list inline per subject.  Beyond this, the agent
    # discovers remaining files via directory traversal.  Keeps prompts
    # within the model's context window for large single-target data rooms
    # (e.g. 4K files with long OneDrive/cloud-storage paths).
    MAX_LISTED_FILES: int = 200

    def _build_subject_list(
        self,
        agent_name: str,
        subjects: list[SubjectEntry],
        file_precedence: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            "## ALL SUBJECTS (you MUST process every one, every file)",
            "",
        ]
        for idx, subj in enumerate(subjects, 1):
            lines.append(f"Subject {idx}: {subj.name} (safe_name: {subj.safe_name})")
            lines.append(f"  Path: {subj.path}")
            if subj.files:
                # Sort files by precedence score (highest first) if available
                sorted_files = list(subj.files)
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

                # Cap inline listing for very large subjects.
                truncated = len(sorted_files) > self.max_listed_files
                display_files = sorted_files[: self.max_listed_files] if truncated else sorted_files

                if file_precedence:
                    lines.append(f"  Files ({subj.file_count}) — ordered by precedence:")
                else:
                    lines.append(f"  Files ({subj.file_count}):")

                for fp in display_files:
                    annotation = self._file_annotation(fp, file_precedence)
                    lines.append(f"    - {fp}{annotation}")

                if truncated:
                    omitted = len(sorted_files) - self.max_listed_files
                    lines.append(
                        f'    ... and {omitted} more files. Use `Glob(pattern="**/*")` on the '
                        f"subject's directory to discover all files. You MUST analyze every file."
                    )
            lines.append("")

        lines.append(
            f"CRITICAL — OUTPUT FILENAMES:\n"
            f"Your output filename MUST be exactly: {{safe_name}}.json\n"
            f"Copy the safe_name character-for-character from above. Do NOT normalize, "
            f"transform, or recompute it. The safe_name is pre-computed and authoritative.\n"
            f"Write to: {self.run_dir}/findings/{agent_name}/{{safe_name}}.json\n\n"
            f"TOTAL: {len(subjects)} subjects. You must process every single one.\n\n"
            f"SPEED RULES (MANDATORY — violating these wastes budget and causes failures):\n"
            f"1. Do NOT read or validate existing output files in the findings "
            f"directory. Always write fresh output by analyzing source documents directly. "
            f"If a file already exists at the output path, overwrite it without reading it first.\n"
            f"2. Do NOT spawn sub-agents, background agents, or parallel agents. "
            f"You are a single agent processing subjects one at a time IN THIS SESSION. "
            f"Never use the Agent tool or launch child processes. "
            f"Process each subject sequentially: read files → analyze → write JSON → next subject.\n"
            f"3. Write each subject's JSON file IMMEDIATELY after analyzing it. "
            f"Do NOT accumulate findings in memory across subjects. "
            f"Write → move on → write → move on.\n"
            f"4. Do NOT summarize your progress, reflect on what you did, or produce final "
            f"status reports. Just write the JSON files and move to the next subject.\n"
            f"5. Do NOT re-read a subject's output file after writing it. Write it once correctly.\n\n"
            f"CITATION QUALITY RULE (MANDATORY — uncited findings are worthless):\n"
            f"A finding without citations is AUTOMATICALLY downgraded to P3 (informational). "
            f"A P1 finding without citations becomes P3 — it loses ALL impact.\n"
            f"5 well-cited findings are worth MORE than 20 uncited findings.\n"
            f"If you are running low on turns, write FEWER findings with proper citations "
            f"rather than many findings without citations. Every finding MUST have:\n"
            f"- citations[].source_path pointing to a real file you actually read\n"
            f"- citations[].exact_quote copied verbatim from that file\n"
            f"If you cannot cite a specific document passage, write a GAP instead of a finding."
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
            "Read the EXACT paths shown in the subject file lists — do not "
            "construct alternative paths or look for converted versions.\n"
            "For large files (>100KB), use Grep to search for specific terms "
            "instead of reading the entire file.\n\n"
            "If the file list says '... and N more files', use `Glob(pattern=\"**/*\")` on the "
            "subject's directory (shown as 'Path:') to discover ALL files. "
            "You MUST analyze every file in the data room, not just those "
            "listed inline."
        )

    @staticmethod
    def _build_reference_section(reference_files: list[ReferenceFile]) -> str:
        if not reference_files:
            return "## GLOBAL REFERENCE FILES\n\nNo reference files assigned."

        from dd_agents.agents.prompt_constants import wrap_untrusted

        lines = ["## GLOBAL REFERENCE FILES assigned to you", ""]
        for idx, ref in enumerate(reference_files, 1):
            # The description is derived from document content (untrusted): wrap
            # it in provenance delimiters so the agent treats it as evidence,
            # never as instructions (audit §7.1). Path/category stay outside.
            lines.append(
                f"Reference {idx}: {ref.file_path}\n"
                f"  Category: {ref.category} / {ref.subcategory}\n"
                f"  Description: {wrap_untrusted(ref.description)}"
            )
            if ref.text_path:
                lines.append(f"  Pre-extracted at: {ref.text_path}")
            if ref.subjects_mentioned:
                lines.append(f"  Subjects mentioned: {', '.join(ref.subjects_mentioned)}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_output_format(agent_name: str) -> str:
        return (
            "## OUTPUT FORMAT\n\n"
            "Write one JSON file per subject with the following structure:\n"
            "```json\n"
            "{\n"
            '  "subject": "Canonical subject name",\n'
            '  "subject_safe_name": "safe_name",\n'
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
            "`citations` array:\n" + FINDING_SCHEMA_BLOCK + "\n"
            "**CRITICAL**: Every finding MUST have at least one citation with "
            "a valid `source_path` pointing to the actual file you read. "
            "Findings without citations will be downgraded in severity. "
            "For P0 and P1 findings, every citation MUST include `exact_quote` "
            "copied verbatim from the document. "
            "P2 findings without `exact_quote` are automatically downgraded to P3. "
            "Include `exact_quote` on ALL findings to preserve severity.\n\n"
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
            '  "match_status": "mismatch (MUST be one of: match | mismatch | not_available | unverified)",\n'
            '  "variance": "-8.3%",\n'
            '  "severity": "P2",\n'
            '  "interpretation": "Contract states $1.2M but revenue cube shows $1.1M"\n'
            "}\n"
            "```\n"
            "**Rules for cross-references:**\n"
            "- NEVER write a bare string — always a structured object.\n"
            "- NEVER create empty placeholders with `data_point: unknown` or "
            "empty values — these are filtered out and wasted.\n"
            "- `match_status` MUST be exactly one of: `match`, `mismatch`, "
            "`not_available`, `unverified`. No other values are accepted.\n"
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
            '  "detection_method": "One of the following EXACT values:\\n'
            "    checklist — gap found by comparing against a standard DD checklist\\n"
            "    cross_reference — gap found by comparing two documents that should agree\\n"
            "    cross_reference_ghost — document referenced in another doc but missing from data room\\n"
            "    cross_reference_phantom — entity/clause referenced but not found anywhere\\n"
            "    cross_reference_mismatch — two documents contradict each other on same data point\\n"
            "    pattern_check — gap found by structural/naming/date patterns in the data room\\n"
            "    governance_resolution — gap found during governance graph cycle resolution\\n"
            "    file_inventory — gap found via data room file listing (expected doc absent)\\n"
            "    file_read_failure — gap found because a file could not be read/extracted"
            '"\n'
            "}\n"
            "```\n"
            "NEVER write a bare string as a gap entry. "
            "If you cannot fill all fields, still write an object with at least "
            "`missing_item` and `gap_type`."
        )

    def _build_manifest_requirement(self, agent_name: str, subjects: list[SubjectEntry]) -> str:
        return (
            "## COVERAGE MANIFEST\n\n"
            f"You MUST write: {self.run_dir}/findings/{agent_name}/"
            "coverage_manifest.json\n\n"
            f"Expected subjects: {len(subjects)}\n"
            "coverage_pct must be >= 0.90\n"
            "Every failed file must have fallback_attempted: true"
        )

    # ------------------------------------------------------------------
    # LLM robustness instructions (Issue #52, spec doc 22)
    # ------------------------------------------------------------------

    @staticmethod
    def robustness_instructions() -> str:
        """Return common LLM robustness mitigations appended to every specialist prompt.

        These instructions implement research-informed LLM robustness mitigations:
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
            "containing at least one citation object:\n" + FINDING_SCHEMA_BLOCK + "\n"
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
            "(required for P0 and P1; P2 without exact_quote is auto-downgraded to P3)\n\n"
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
            "- Do NOT attempt to read all files into memory at once. Process one subject "
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
            "1. ALL subjects in your assigned list have been analyzed.\n"
            "2. ALL files for each subject have been read or searched.\n"
            "3. ALL required fields in every finding and gap are populated.\n"
            "4. EVERY finding has a non-empty `citations` array with at least one "
            "citation that includes `source_path`.\n"
            "5. ALL `exact_quote` values have been verified against the source document.\n"
            "6. Every P0/P1/P2 finding has `exact_quote` in every citation "
            "(P2 without quote is downgraded to P3).\n"
            "7. Every P0 finding has been re-read and its severity confirmed.\n"
            "8. ALL reference files assigned to you have been processed.\n\n"
            "### Quality Calibration Check\n\n"
            "Before finalizing, review your P0 and P1 findings critically:\n"
            "1. For each P0: Would an experienced M&A partner present this as a genuine deal-stopper?\n"
            "2. For each P1: Is this truly material? Does it require pre-close negotiation?\n"
            "3. Zero findings for a clean subject is acceptable. Do NOT manufacture findings.\n"
            "4. Fewer, well-calibrated findings > many poorly-calibrated ones.\n\n"
            #
            # 7b. Follow-up verification loop for P0/P1 (Issue #140)
            # Research: AG-6 finding shows 9.2% accuracy improvement from
            # mandatory follow-up prompts for high-value provisions.
            #
            "### MANDATORY P0/P1 Self-Verification Loop (CRITICAL)\n\n"
            "After drafting ALL findings for a subject, you MUST perform a "
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
            "in other documents for this subject? If you haven't checked, search for them.\n\n"
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
            "exist in the subject's files, you MUST record this as a gap, NOT as a finding.\n\n"
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
        subject_name: str,
        agent_name: str,
    ) -> str:
        """Build a follow-up verification prompt for P0/P1 findings.

        Research (AG-6): mandatory follow-up for high-value provisions improves
        accuracy by 9.2%.  This prompt asks the agent to re-verify each critical
        finding against the source document.

        Returns an empty string if there are no P0/P1 findings to verify.
        """
        critical = [f for f in findings if str(f.get("severity", "")).upper() in (SEVERITY_P0, SEVERITY_P1)]
        if not critical:
            return ""

        lines: list[str] = [
            f"## FOLLOW-UP VERIFICATION — {subject_name} ({agent_name})\n",
            "You previously analyzed this subject and produced the following "
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
