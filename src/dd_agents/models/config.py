"""Pydantic models for deal configuration (deal-config.json schema)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dd_agents.models.enums import DealType, ExecutionMode


class BuyerInfo(BaseModel):
    """Buyer entity information."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, description="Buyer company name")
    ticker: str = Field(default="", description="Stock ticker symbol if publicly traded")
    exchange: str = Field(default="", description="Stock exchange (e.g. NYSE, NASDAQ)")
    notes: str = Field(default="", description="Additional notes about the buyer")


class PreviousName(BaseModel):
    """Historical name of the target entity."""

    name: str = Field(description="Previous company name")
    period: str = Field(default="", description="Time period when the name was used")
    notes: str = Field(default="", description="Additional context about the name change")


class AcquiredEntity(BaseModel):
    """Entity previously acquired by the target."""

    name: str = Field(description="Name of the acquired entity")
    acquisition_date: str = Field(default="", description="Acquisition date (YYYY-MM-DD)")
    deal_type: str = Field(default="", description="Type of acquisition deal")
    notes: str = Field(default="", description="Additional notes about the acquisition")

    @field_validator("acquisition_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        import re

        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("acquisition_date must be YYYY-MM-DD format")
        return v


class TargetInfo(BaseModel):
    """Target entity information."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, description="Target company name")
    subsidiaries: list[str] = Field(default_factory=list, description="Known subsidiary names")
    previous_names: list[PreviousName] = Field(default_factory=list, description="Historical company names")
    acquired_entities: list[AcquiredEntity] = Field(default_factory=list, description="Previously acquired entities")
    entity_name_variants_for_contract_matching: list[str] = Field(
        default_factory=list, description="Name variants to match in contracts"
    )
    notes: str = Field(default="", description="Additional notes about the target")


class EntityAliases(BaseModel):
    """Entity resolution alias configuration. From entity-resolution-protocol.md."""

    model_config = ConfigDict(extra="allow")

    canonical_to_variants: dict[str, list[str]] = Field(
        default_factory=dict, description="Canonical name to known variant names"
    )
    short_name_guard: list[str] = Field(
        default_factory=list, description="Short names requiring exact match (no fuzzy)"
    )
    exclusions: list[str] = Field(default_factory=list, description="Names to exclude from entity resolution")
    parent_child: dict[str, list[str]] = Field(
        default_factory=dict, description="Parent company to subsidiary name mappings"
    )


class ActiveFilter(BaseModel):
    """Filter criteria for identifying active subjects in the database."""

    arr_column: int | None = Field(default=None, description="Column index for ARR values")
    arr_condition: str = Field(default="", description="Filter condition for ARR (e.g. '> 0')")
    end_date_condition: str = Field(default="", description="Filter condition for end date")


class SubjectDatabaseColumns(BaseModel):
    """Column index mapping for the subject database spreadsheet."""

    model_config = ConfigDict(extra="allow")

    subject_name: int = Field(ge=1, description="1-based column index for subject name")
    parent_account: int | None = Field(default=None, description="Column index for parent account")
    entity: int | None = Field(default=None, description="Column index for legal entity")
    platform: int | None = Field(default=None, description="Column index for platform/product")
    contract_start: int | None = Field(default=None, description="Column index for contract start date")
    contract_end: int | None = Field(default=None, description="Column index for contract end date")
    arr: int | None = Field(default=None, description="Column index for annual recurring revenue")


class SubjectDatabase(BaseModel):
    """Subject database reference for contract date reconciliation."""

    file: str = Field(min_length=1, description="Path to the subject database spreadsheet")
    sheet: str = Field(default="", description="Sheet name to read (empty for first sheet)")
    header_row: int = Field(default=1, ge=1, description="1-based row number containing column headers")
    columns: SubjectDatabaseColumns = Field(description="Column index mapping")
    active_filter: ActiveFilter | None = Field(default=None, description="Filter criteria for active subjects")


class SourceOfTruth(BaseModel):
    """Authoritative data source configuration. From SKILL.md section 5."""

    model_config = ConfigDict(extra="allow")

    subject_database: SubjectDatabase | None = Field(
        default=None, description="Subject database spreadsheet configuration"
    )


class KeyExecutive(BaseModel):
    """Key executive of the target company."""

    name: str = Field(description="Executive's name")
    title: str = Field(description="Executive's title/position")
    company: str = Field(description="Company the executive belongs to")
    notes: str = Field(default="", description="Additional notes about the executive")


class DealInfo(BaseModel):
    """Deal parameters and focus areas."""

    model_config = ConfigDict(extra="allow")

    type: DealType = Field(description="Deal type: acquisition, merger, etc.")
    focus_areas: list[str] = Field(min_length=1, description="Key areas of focus for due diligence")
    notes: str = Field(default="", description="Additional notes about the deal")
    output_language: str = Field(
        default="en",
        description=(
            "ISO language code for finding prose (audit AD-4). Agents read source "
            "documents in any language and quote verbatim in the original, but write "
            "finding descriptions in this language. Default 'en'."
        ),
    )


class SamplingRates(BaseModel):
    """Judge sampling rates per severity level."""

    p0: float = Field(default=1.0, ge=0.0, le=1.0, description="Sampling rate for P0 findings (0.0-1.0)")
    p1: float = Field(default=0.20, ge=0.0, le=1.0, description="Sampling rate for P1 findings (0.0-1.0)")
    p2: float = Field(default=0.10, ge=0.0, le=1.0, description="Sampling rate for P2 findings (0.0-1.0)")
    p3: float = Field(default=0.0, ge=0.0, le=1.0, description="Sampling rate for P3 findings (0.0-1.0)")


class JudgeConfig(BaseModel):
    """Judge agent configuration. From agent-prompts.md section 6."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Whether the Judge agent is enabled")
    max_iteration_rounds: int = Field(default=2, ge=1, le=5, description="Maximum Judge iteration rounds (1-5)")
    score_threshold: int = Field(default=70, ge=0, le=100, description="Minimum quality score to pass (0-100)")
    sampling_rates: SamplingRates = Field(
        default_factory=SamplingRates, description="Finding sampling rates by severity"
    )
    ocr_completeness_check: bool = Field(default=True, description="Whether to check OCR extraction completeness")
    cross_agent_contradiction_check: bool = Field(
        default=True, description="Whether to check for inter-agent contradictions"
    )
    web_research_enabled: bool = Field(
        default=False,
        description="Enable web research via google-researcher-mcp for claim verification (Issue #139).",
    )


class ExtractionConfig(BaseModel):
    """Extraction pipeline configuration."""

    model_config = ConfigDict(extra="allow")

    ocr_backend: str = Field(
        default="auto",
        description='OCR backend selection: "auto", "glm_ocr", or "pytesseract"',
    )


class ExecutionConfig(BaseModel):
    """Pipeline execution configuration. From SKILL.md section 0e."""

    model_config = ConfigDict(extra="allow")

    execution_mode: ExecutionMode = Field(default=ExecutionMode.FULL, description="Execution mode: full or incremental")
    staleness_threshold: int = Field(
        default=3, ge=1, le=100, description="Consecutive unchanged runs before stale refresh"
    )
    force_full_on_config_change: bool = Field(
        default=True, description="Force full re-analysis when deal config changes"
    )
    batch_concurrency: int = Field(
        default=6,
        ge=1,
        le=10,
        description="Max concurrent batches per agent in step 16. "
        "Each batch is an independent SDK session processing different "
        "subjects, so parallelism is safe. Default 6.",
    )


class VerdictRubricConfig(BaseModel):
    """Optional overrides for the deterministic Go/No-Go verdict rubric.

    Mirrors ``reporting.verdict.VerdictRubric``. Each field is optional; only
    the keys present override the conservative built-in defaults.
    """

    model_config = ConfigDict(extra="forbid")

    no_go_p0_min: int | None = Field(default=None, ge=1, description="P0 findings that trigger NO-GO (default 1)")
    conditional_p1_min: int | None = Field(
        default=None, ge=1, description="P1 findings that trigger CONDITIONAL (default 3)"
    )
    proceed_with_conditions_p1_min: int | None = Field(
        default=None,
        ge=1,
        description="P1 findings that trigger PROCEED WITH CONDITIONS (default 1)",
    )
    high_exposure_pct: float | None = Field(
        default=None,
        ge=0.0,
        description="Revenue-at-risk percent treated as high exposure (default 20.0)",
    )


class ReportingConfig(BaseModel):
    """Report generation configuration. From reporting-protocol.md section 3."""

    model_config = ConfigDict(extra="allow")

    report_schema_override: str | None = Field(default=None, description="Path to custom report_schema.json override")
    include_diff_sheet: bool = Field(default=True, description="Include run-over-run diff sheet in Excel report")
    include_metadata_sheet: bool = Field(default=True, description="Include metadata sheet in Excel report")
    verdict: VerdictRubricConfig | None = Field(
        default=None,
        description="Override the deterministic verdict rubric thresholds (Issue #195)",
    )


class AgentCustomization(BaseModel):
    """Per-agent customization applied via deal-config.json.

    Business users add focus areas, instructions, or severity overrides
    without touching Python code.
    """

    model_config = ConfigDict(extra="allow")

    extra_focus_areas: list[str] = Field(
        default_factory=list, description="Additional focus areas appended to the agent's defaults"
    )
    extra_instructions: str = Field(
        default="", description="Additional instructions appended to the agent's specialist focus"
    )
    severity_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Category-to-severity overrides, e.g. {'change_of_control': 'P2'}",
    )
    persona: str | None = Field(
        default=None,
        description="Replaces the agent's built-in persona when set via '## Persona (replaces default)'",
    )


class SpecialistsConfig(BaseModel):
    """Specialist agent enablement and customization."""

    model_config = ConfigDict(extra="allow")

    disabled: list[str] = Field(default_factory=list, description="Agent names to disable for this run")
    customizations: dict[str, AgentCustomization] = Field(
        default_factory=dict, description="Per-agent customization keyed by agent name"
    )
    allow_user_downgrade_of_dealbreakers: bool = Field(
        default=False,
        description=(
            "Safety bound for user severity_overrides (audit AD-3a). When False "
            "(default), a user override may not downgrade a deal-breaker finding "
            "(one currently at P0 or P1) below the P1 floor. When True, such a "
            "downgrade is permitted but is still CLAMPED to P1 — never below — so "
            "a genuine deal-breaker can never be silenced. A tamper/integrity "
            "finding is never downgradable in either mode. Escalations are always "
            "allowed, and non-deal-breaker findings (P2/P3) can be freely "
            "re-ranked regardless of this flag."
        ),
    )


class CrossDomainConfig(BaseModel):
    """Cross-domain analysis configuration (Issue #189).

    Controls the neurosymbolic trigger engine that fires pass-2
    targeted specialist reviews when pass-1 findings have implications
    for other domains.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Enable cross-domain analysis between pass-1 and Judge review")
    max_pass2_budget_usd: float = Field(
        default=5.0, ge=0.0, le=50.0, description="Maximum budget for pass-2 cross-domain analysis"
    )
    min_trigger_severity: str = Field(
        default="P2",
        pattern=r"^P[0-4]$",
        description="Minimum severity to trigger cross-domain analysis (P0=most severe)",
    )
    disabled_rules: list[str] = Field(
        default_factory=list, description="Trigger rule names to disable (e.g. 'sla_financial_impact')"
    )
    custom_rules: list[str] = Field(
        default_factory=list,
        description="Custom trigger rule entry-point names to load (e.g. 'my_package.rules:my_rule')",
    )


class ForensicDDConfig(BaseModel):
    """Forensic DD skill-specific configuration."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Whether forensic-dd skill is enabled")
    specialists: SpecialistsConfig = Field(
        default_factory=SpecialistsConfig, description="Specialist agent configuration"
    )
    cross_domain: CrossDomainConfig = Field(
        default_factory=CrossDomainConfig, description="Cross-domain analysis configuration"
    )


class BuyerStrategy(BaseModel):
    """Optional buyer strategy context for acquirer-specific analysis.

    When present, enables the Acquirer Intelligence Agent (#110)
    and the Buyer Strategy report section (#111). When absent,
    the report is a generic DD report with no buyer-specific content.
    """

    model_config = ConfigDict(extra="allow")

    thesis: str = Field(default="", description="Buyer's acquisition thesis / strategic rationale")
    key_synergies: list[str] = Field(default_factory=list, description="Expected synergies")
    integration_priorities: list[str] = Field(default_factory=list, description="Post-close integration priorities")
    risk_tolerance: str = Field(default="moderate", description="Risk tolerance: conservative, moderate, aggressive")
    focus_areas: list[str] = Field(default_factory=list, description="Buyer-specific focus areas for analysis")
    budget_range: str = Field(default="", description="Deal budget range context")
    notes: str = Field(default="", description="Additional notes about buyer strategy")

    @field_validator("risk_tolerance")
    @classmethod
    def validate_risk_tolerance(cls, v: str) -> str:
        allowed = {"conservative", "moderate", "aggressive"}
        if v and v not in allowed:
            raise ValueError(f"risk_tolerance must be one of {allowed}, got '{v}'")
        return v


class AgentRoute(BaseModel):
    """Per-agent LLM routing override (Issue #233).

    Lets a single agent run on a different model AND/OR provider than the
    run-wide default — e.g. a cheap gateway model for the Red Flag Scanner, a
    premium provider for the Judge. All fields optional; an empty route is a
    no-op. Routing is applied through the one LLM seam
    (``llm.build_agent_options`` via ``extra_env``) — never by mutating process
    env — so concurrent sessions stay isolated.
    """

    model_config = ConfigDict(extra="allow")

    model: str | None = Field(default=None, description="Model id for this agent (overrides profile/overrides).")
    base_url: str | None = Field(
        default=None,
        description="Anthropic-compatible gateway base URL for this agent (sets ANTHROPIC_BASE_URL for its call only).",
    )
    auth_token_env: str | None = Field(
        default=None,
        description="Name of an env var holding the gateway auth token for this agent (its value is read at run "
        "time and passed as ANTHROPIC_AUTH_TOKEN for the agent's call). The token itself is NEVER stored in config.",
    )

    @field_validator("base_url")
    @classmethod
    def _reject_credentialed_base_url(cls, v: str | None) -> str | None:
        """Reject a base_url that embeds credentials (``scheme://user:pw@host``).

        Credentials belong in ``auth_token_env`` (an env-var name), never in the
        URL — a credentialed base_url would otherwise be persisted in config and
        forwarded to the subprocess. Fail-closed at the config boundary.
        """
        if v:
            from urllib.parse import urlsplit

            parts = urlsplit(v)
            if parts.username or parts.password:
                raise ValueError(
                    "agent_models.routes[*].base_url must not contain credentials (userinfo). "
                    "Put the token's env-var name in auth_token_env instead."
                )
        return v

    @property
    def safe_base_url(self) -> str | None:
        """``base_url`` with any userinfo/query/fragment stripped (defensive)."""
        if not self.base_url:
            return None
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.base_url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", "")) or None


class AgentModelsConfig(BaseModel):
    """Agent model selection configuration (Issue #129, extended #233).

    Supports three preset profiles (economy/standard/premium), per-agent model
    overrides, and per-agent provider/model routing (``routes``).
    """

    model_config = ConfigDict(extra="allow")

    profile: str = Field(
        default="standard",
        description="Model profile: economy (Haiku-heavy), standard (Sonnet-heavy), premium (Opus for synthesis).",
    )
    overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Per-agent model overrides. Keys are agent names, values are model IDs.",
    )
    routes: dict[str, AgentRoute] = Field(
        default_factory=dict,
        description="Per-agent provider/model routing (Issue #233). Keys are agent names; each route may set "
        "model, base_url (gateway), and auth_token_env. Routing applies through the LLM seam per call.",
    )
    budget_limit_usd: float | None = Field(
        default=None,
        description="Optional hard budget limit in USD per pipeline run.",
    )

    def resolve_model(self, agent_name: str) -> str:
        """Return the model ID for a given agent.

        Precedence: per-agent ``routes[agent].model`` → ``overrides[agent]`` →
        profile default. Uses a deferred import of ``agents.cost_tracker`` to
        avoid a circular dependency (models → agents → models).
        """
        route = self.routes.get(agent_name)
        if route is not None and route.model:
            return route.model

        if agent_name in self.overrides:
            return self.overrides[agent_name]

        from dd_agents.agents.cost_tracker import get_model_profiles

        profiles = get_model_profiles()
        profile = profiles.get(self.profile, profiles["standard"])
        return profile.get_model_for_agent(agent_name)

    def resolve_route(self, agent_name: str) -> AgentRoute | None:
        """Return the per-agent route, or None when the agent has no routing override.

        Note: per-agent routing is part of the deal config, so it is already
        covered by the run's ``config_hash`` (and therefore the provenance hash)
        — a routing change busts a stale checkpoint with no extra plumbing.
        """
        return self.routes.get(agent_name)


class PrecedenceConfig(BaseModel):
    """Document precedence configuration (Issue #163).

    Controls folder priority classification and version chain detection.
    All fields are optional — sensible defaults apply when absent.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Enable document precedence analysis")
    folder_priority: dict[str, int] = Field(
        default_factory=dict,
        description="Folder name → tier override (1=authoritative, 2=working, 3=supplementary, 4=historical)",
    )
    vdr_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="VDR folder-convention overrides (Issue #193): folder-name substring (case-insensitive) → "
        "specialist domain (legal, finance, commercial, producttech, cybersecurity, hr, tax, regulatory, esg). "
        "Corrects a misclassified numbered VDR folder; takes precedence over the built-in convention table.",
    )


class RequestedDocument(BaseModel):
    """One expected document/category in a request list (Issue #192).

    Plain data — declares what the deal team expects to receive. Reconciliation
    against discovered files produces received-vs-missing gaps.
    """

    model_config = ConfigDict(extra="allow")

    category: str = Field(description="Expected document or category, e.g. 'Signed MSA', 'Cap table'")
    keywords: list[str] = Field(
        default_factory=list,
        description="Filename/path keywords that satisfy this item (case-insensitive). "
        "Defaults to words from `category` when empty.",
    )
    required: bool = Field(default=True, description="True = missing is a material gap; False = optional/nice-to-have")
    subject: str | None = Field(
        default=None,
        description="Subject this item applies to (subject_safe_name or display name). None = all subjects.",
    )


class RequestListConfig(BaseModel):
    """Optional request list: what documents are expected in the data room.

    When present, the pipeline (and `dd-agents assess`) reconciles expected
    items against discovered files and reports received / missing / unexpected.
    Absent = feature off (parity — nothing changes).
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Enable request-list reconciliation")
    items: list[RequestedDocument] = Field(default_factory=list, description="Expected documents/categories")
    seed_from_vdr: bool = Field(
        default=False,
        description="When True, auto-seed expected categories from a detected VDR convention (Issue #193) "
        "if no items are declared.",
    )


class DealConfig(BaseModel):
    """
    Root configuration model. Validated from deal-config.json.
    Source: deal-config.schema.json + deal-config.template.json
    """

    model_config = ConfigDict(extra="allow")

    config_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="Semver config format version (>= 1.0.0)")
    buyer: BuyerInfo = Field(description="Buyer entity information")
    target: TargetInfo = Field(description="Target entity information")
    entity_aliases: EntityAliases = Field(
        default_factory=EntityAliases, description="Entity resolution alias configuration"
    )
    source_of_truth: SourceOfTruth = Field(
        default_factory=SourceOfTruth, description="Authoritative data source configuration"
    )
    key_executives: list[KeyExecutive] = Field(default_factory=list, description="Key executives of the target company")
    deal: DealInfo = Field(description="Deal parameters and focus areas")
    judge: JudgeConfig = Field(default_factory=JudgeConfig, description="Judge agent configuration")
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig, description="Extraction pipeline config")
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig, description="Pipeline execution config")
    reporting: ReportingConfig = Field(default_factory=ReportingConfig, description="Report generation config")
    forensic_dd: ForensicDDConfig = Field(default_factory=ForensicDDConfig, description="Forensic DD skill config")
    agent_models: AgentModelsConfig = Field(
        default_factory=AgentModelsConfig, description="Agent model selection config"
    )
    buyer_strategy: BuyerStrategy | None = Field(
        default=None,
        description="Optional buyer strategy context. When absent, all buyer-specific features are disabled.",
    )
    precedence: PrecedenceConfig | None = Field(
        default=None,
        description="Optional document precedence config. When absent, default tier patterns apply.",
    )
    request_list: RequestListConfig | None = Field(
        default=None,
        description="Optional request list (expected documents). When absent, reconciliation is skipped.",
    )

    @field_validator("config_version")
    @classmethod
    def check_minimum_version(cls, v: str) -> str:
        parts = [int(x) for x in v.split(".")]
        if parts < [1, 0, 0]:
            raise ValueError("config_version must be >= 1.0.0")
        return v
