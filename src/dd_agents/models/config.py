"""Pydantic models for deal configuration (deal-config.json schema)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dd_agents.models.enums import AgentName, DealType, ExecutionMode


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
        if v and not __import__("re").match(r"^\d{4}-\d{2}-\d{2}$", v):
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
    """Filter criteria for identifying active customers in the database."""

    arr_column: int | None = Field(default=None, description="Column index for ARR values")
    arr_condition: str = Field(default="", description="Filter condition for ARR (e.g. '> 0')")
    end_date_condition: str = Field(default="", description="Filter condition for end date")


class CustomerDatabaseColumns(BaseModel):
    """Column index mapping for the customer database spreadsheet."""

    model_config = ConfigDict(extra="allow")

    customer_name: int = Field(ge=1, description="1-based column index for customer name")
    parent_account: int | None = Field(default=None, description="Column index for parent account")
    entity: int | None = Field(default=None, description="Column index for legal entity")
    platform: int | None = Field(default=None, description="Column index for platform/product")
    contract_start: int | None = Field(default=None, description="Column index for contract start date")
    contract_end: int | None = Field(default=None, description="Column index for contract end date")
    arr: int | None = Field(default=None, description="Column index for annual recurring revenue")


class CustomerDatabase(BaseModel):
    """Customer database reference for contract date reconciliation."""

    file: str = Field(min_length=1, description="Path to the customer database spreadsheet")
    sheet: str = Field(default="", description="Sheet name to read (empty for first sheet)")
    header_row: int = Field(default=1, ge=1, description="1-based row number containing column headers")
    columns: CustomerDatabaseColumns = Field(description="Column index mapping")
    active_filter: ActiveFilter | None = Field(default=None, description="Filter criteria for active customers")


class SourceOfTruth(BaseModel):
    """Authoritative data source configuration. From SKILL.md section 5."""

    model_config = ConfigDict(extra="allow")

    customer_database: CustomerDatabase | None = Field(
        default=None, description="Customer database spreadsheet configuration"
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
        "customers, so parallelism is safe. Default 6.",
    )


class ReportingConfig(BaseModel):
    """Report generation configuration. From reporting-protocol.md section 3."""

    model_config = ConfigDict(extra="allow")

    report_schema_override: str | None = Field(default=None, description="Path to custom report_schema.json override")
    include_diff_sheet: bool = Field(default=True, description="Include run-over-run diff sheet in Excel report")
    include_metadata_sheet: bool = Field(default=True, description="Include metadata sheet in Excel report")


class CustomDomain(BaseModel):
    """Custom analysis domain definition."""

    id: str = Field(pattern=r"^[a-z_]+$", description="Unique domain identifier (lowercase with underscores)")
    name: str = Field(description="Human-readable domain name")
    description: str = Field(default="", description="Description of what this domain analyzes")
    agent_assignment: AgentName = Field(description="Agent responsible for analyzing this domain")
    expected_finding_categories: list[str] = Field(
        default_factory=list, description="Expected finding categories for this domain"
    )
    key_terms: list[str] = Field(default_factory=list, description="Domain-specific key terms to search for")
    weight: int = Field(default=3, ge=1, le=3, description="Domain importance weight (1=low, 3=high)")


class DomainConfig(BaseModel):
    """Analysis domain configuration for forensic-dd."""

    disabled: list[str] = Field(default_factory=list, description="Domain IDs to disable")
    custom: list[CustomDomain] = Field(default_factory=list, description="Custom domain definitions")


class ForensicDDConfig(BaseModel):
    """Forensic DD skill-specific configuration."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="Whether forensic-dd skill is enabled")
    domains: DomainConfig = Field(default_factory=DomainConfig, description="Domain configuration")


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


class AgentModelsConfig(BaseModel):
    """Agent model selection configuration (Issue #129).

    Supports three preset profiles (economy/standard/premium) and
    per-agent overrides for fine-grained control.
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
    budget_limit_usd: float | None = Field(
        default=None,
        description="Optional hard budget limit in USD per pipeline run.",
    )

    def resolve_model(self, agent_name: str) -> str:
        """Return the model ID for a given agent, checking overrides first.

        Uses a deferred import of ``agents.cost_tracker`` to avoid a
        circular dependency (models → agents → models).  This is
        intentional — the method belongs on the config model because it
        encapsulates profile + override resolution logic.
        """
        if agent_name in self.overrides:
            return self.overrides[agent_name]

        from dd_agents.agents.cost_tracker import get_model_profiles

        profiles = get_model_profiles()
        profile = profiles.get(self.profile, profiles["standard"])
        return profile.get_model_for_agent(agent_name)


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

    @field_validator("config_version")
    @classmethod
    def check_minimum_version(cls, v: str) -> str:
        parts = [int(x) for x in v.split(".")]
        if parts < [1, 0, 0]:
            raise ValueError("config_version must be >= 1.0.0")
        return v
