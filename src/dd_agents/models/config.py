"""Pydantic models for deal configuration (deal-config.json schema)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dd_agents.models.enums import AgentName, DealType, ExecutionMode


class BuyerInfo(BaseModel):
    """Buyer entity information."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    ticker: str = ""
    exchange: str = ""
    notes: str = ""


class PreviousName(BaseModel):
    """Historical name of the target entity."""

    name: str
    period: str = ""
    notes: str = ""


class AcquiredEntity(BaseModel):
    """Entity previously acquired by the target."""

    name: str
    acquisition_date: str = ""  # YYYY-MM-DD
    deal_type: str = ""
    notes: str = ""

    @field_validator("acquisition_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if v and not __import__("re").match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError("acquisition_date must be YYYY-MM-DD format")
        return v


class TargetInfo(BaseModel):
    """Target entity information."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    subsidiaries: list[str] = Field(default_factory=list)
    previous_names: list[PreviousName] = Field(default_factory=list)
    acquired_entities: list[AcquiredEntity] = Field(default_factory=list)
    entity_name_variants_for_contract_matching: list[str] = Field(default_factory=list)
    notes: str = ""


class EntityAliases(BaseModel):
    """Entity resolution alias configuration. From entity-resolution-protocol.md."""

    model_config = ConfigDict(extra="allow")

    canonical_to_variants: dict[str, list[str]] = Field(default_factory=dict)
    short_name_guard: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    parent_child: dict[str, list[str]] = Field(default_factory=dict)


class ActiveFilter(BaseModel):
    """Filter criteria for identifying active customers in the database."""

    arr_column: int | None = None
    arr_condition: str = ""
    end_date_condition: str = ""


class CustomerDatabaseColumns(BaseModel):
    """Column index mapping for the customer database spreadsheet."""

    model_config = ConfigDict(extra="allow")

    customer_name: int = Field(ge=1)
    parent_account: int | None = None
    entity: int | None = None
    platform: int | None = None
    contract_start: int | None = None
    contract_end: int | None = None
    arr: int | None = None


class CustomerDatabase(BaseModel):
    """Customer database reference for contract date reconciliation."""

    file: str = Field(min_length=1)
    sheet: str = ""
    header_row: int = Field(default=1, ge=1)
    columns: CustomerDatabaseColumns
    active_filter: ActiveFilter | None = None


class SourceOfTruth(BaseModel):
    """Authoritative data source configuration. From SKILL.md section 5."""

    model_config = ConfigDict(extra="allow")

    customer_database: CustomerDatabase | None = None


class KeyExecutive(BaseModel):
    """Key executive of the target company."""

    name: str
    title: str
    company: str
    notes: str = ""


class DealInfo(BaseModel):
    """Deal parameters and focus areas."""

    model_config = ConfigDict(extra="allow")

    type: DealType
    focus_areas: list[str] = Field(min_length=1)
    notes: str = ""


class SamplingRates(BaseModel):
    """Judge sampling rates per severity level."""

    p0: float = Field(default=1.0, ge=0.0, le=1.0)
    p1: float = Field(default=0.20, ge=0.0, le=1.0)
    p2: float = Field(default=0.10, ge=0.0, le=1.0)
    p3: float = Field(default=0.0, ge=0.0, le=1.0)


class JudgeConfig(BaseModel):
    """Judge agent configuration. From agent-prompts.md section 6."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    max_iteration_rounds: int = Field(default=2, ge=1, le=5)
    score_threshold: int = Field(default=70, ge=0, le=100)
    sampling_rates: SamplingRates = Field(default_factory=SamplingRates)
    ocr_completeness_check: bool = True
    cross_agent_contradiction_check: bool = True


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

    execution_mode: ExecutionMode = ExecutionMode.FULL
    staleness_threshold: int = Field(default=3, ge=1, le=100)
    force_full_on_config_change: bool = True
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

    report_schema_override: str | None = None
    include_diff_sheet: bool = True
    include_metadata_sheet: bool = True


class CustomDomain(BaseModel):
    """Custom analysis domain definition."""

    id: str = Field(pattern=r"^[a-z_]+$")
    name: str
    description: str = ""
    agent_assignment: AgentName
    expected_finding_categories: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    weight: int = Field(default=3, ge=1, le=3)


class DomainConfig(BaseModel):
    """Analysis domain configuration for forensic-dd."""

    disabled: list[str] = Field(default_factory=list)
    custom: list[CustomDomain] = Field(default_factory=list)


class ForensicDDConfig(BaseModel):
    """Forensic DD skill-specific configuration."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    domains: DomainConfig = Field(default_factory=DomainConfig)


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
    notes: str = ""

    @field_validator("risk_tolerance")
    @classmethod
    def validate_risk_tolerance(cls, v: str) -> str:
        allowed = {"conservative", "moderate", "aggressive"}
        if v and v not in allowed:
            raise ValueError(f"risk_tolerance must be one of {allowed}, got '{v}'")
        return v


class DealConfig(BaseModel):
    """
    Root configuration model. Validated from deal-config.json.
    Source: deal-config.schema.json + deal-config.template.json
    """

    model_config = ConfigDict(extra="allow")

    config_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    buyer: BuyerInfo
    target: TargetInfo
    entity_aliases: EntityAliases = Field(default_factory=EntityAliases)
    source_of_truth: SourceOfTruth = Field(default_factory=SourceOfTruth)
    key_executives: list[KeyExecutive] = Field(default_factory=list)
    deal: DealInfo
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    forensic_dd: ForensicDDConfig = Field(default_factory=ForensicDDConfig)
    buyer_strategy: BuyerStrategy | None = Field(
        default=None,
        description="Optional buyer strategy context. When absent, all buyer-specific features are disabled.",
    )

    @field_validator("config_version")
    @classmethod
    def check_minimum_version(cls, v: str) -> str:
        parts = [int(x) for x in v.split(".")]
        if parts < [1, 0, 0]:
            raise ValueError("config_version must be >= 1.0.0")
        return v
