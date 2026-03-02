"""Pydantic models for findings, citations, gaps, and cross-references."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from dd_agents.models.enums import (
    AgentName,
    Confidence,
    DetectionMethod,
    GapType,
    MatchStatus,
    Severity,
    SourceType,
)
from dd_agents.models.governance import GovernanceGraph

_logger = logging.getLogger(__name__)

_MATCH_STATUS_ALIASES: dict[str, str] = {
    "": "unverified",
    "confirmed": "match",
    "unable_to_verify": "not_available",
    "partial_match": "mismatch",
}

_VALID_MATCH_STATUSES: set[str] = {s.value for s in MatchStatus}


def _coerce_severity(v: Any) -> Severity:
    """Coerce string values to Severity enum."""
    if isinstance(v, Severity):
        return v
    if isinstance(v, str):
        return Severity(v)
    raise ValueError(f"Cannot coerce {v!r} to Severity")


def _coerce_confidence(v: Any) -> Confidence:
    """Coerce string values to Confidence enum."""
    if isinstance(v, Confidence):
        return v
    if isinstance(v, str):
        return Confidence(v)
    raise ValueError(f"Cannot coerce {v!r} to Confidence")


def _coerce_agent_name(v: Any) -> AgentName:
    """Coerce string values to AgentName enum."""
    if isinstance(v, AgentName):
        return v
    if isinstance(v, str):
        return AgentName(v)
    raise ValueError(f"Cannot coerce {v!r} to AgentName")


class BoundingBox(BaseModel):
    """Page-level bounding box for visual grounding of findings."""

    x0: float = Field(description="Left edge in points")
    y0: float = Field(description="Top edge in points")
    x1: float = Field(description="Right edge in points")
    y1: float = Field(description="Bottom edge in points")
    page: int = Field(description="1-based page number")


class Citation(BaseModel):
    """
    Citation attached to a finding. From domain-definitions.md section 2.

    IMPORTANT: exact_quote is typed as str (not Optional). For clean-result
    findings (domain_reviewed_no_issues), OMIT the exact_quote field entirely
    rather than setting it to null. Serialize with exclude_none=True.
    """

    model_config = ConfigDict(populate_by_name=True)

    source_type: SourceType
    source_path: str
    location: str = ""  # "Section X.Y" or page number
    exact_quote: str | None = Field(
        default=None,
        description="Verbatim text from the document. OMIT (do not set to null) "
        "for clean-result findings. Serialize with exclude_none=True.",
    )
    # NOTE: exact_quote is stored as a plain string. When the quote contains
    # special characters (newlines, quotes), they are escaped using standard
    # JSON string escaping. No custom serializer needed -- Pydantic v2 handles
    # this natively via model_dump_json().
    access_date: str | None = None  # Required when source_type == web_research
    page_number: int | None = Field(default=None, description="1-based page number for visual grounding")
    bounding_box: BoundingBox | None = Field(default=None, description="Coordinate box for visual grounding")
    verification_status: str | None = Field(
        default=None,
        description="Result of verify_citation tool call: 'verified', 'failed', or None if not checked.",
    )

    @model_validator(mode="after")
    def web_research_needs_access_date(self) -> Citation:
        if self.source_type == SourceType.WEB_RESEARCH and not self.access_date:
            raise ValueError("access_date is required when source_type is 'web_research'")
        return self


class Finding(BaseModel):
    """
    Full framework-schema-compliant finding.
    Conforms to dd-framework/schemas/finding.schema.json.
    Produced by the Reporting Lead during merge (not by specialist agents directly).
    """

    id: str = Field(
        pattern=r"^[a-z][a-z0-9-]*_[a-z][a-z0-9_-]*_\d{4,}$",
        description="Format: {skill}_{agent}_{sequential_number} e.g. forensic-dd_legal_0001",
    )
    severity: Severity
    category: str
    title: str = Field(max_length=120)
    description: str
    citations: list[Citation] = Field(min_length=1)
    confidence: Confidence
    agent: AgentName
    skill: str = "forensic-dd"
    run_id: str
    timestamp: str  # ISO-8601
    analysis_unit: str  # customer name
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("severity", mode="before")
    @classmethod
    def coerce_severity(cls, v: Any) -> Severity:
        return _coerce_severity(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: Any) -> Confidence:
        return _coerce_confidence(v)

    @field_validator("agent", mode="before")
    @classmethod
    def coerce_agent(cls, v: Any) -> AgentName:
        return _coerce_agent_name(v)

    @field_validator("citations")
    @classmethod
    def p0_p1_require_exact_quote(cls, v: list[Citation], info: ValidationInfo) -> list[Citation]:
        severity = info.data.get("severity")
        if severity in (Severity.P0, Severity.P1):
            for cit in v:
                if not cit.exact_quote:
                    raise ValueError(f"{severity.value} finding must have exact_quote in all citations")
        return v


class AgentFinding(BaseModel):
    """
    Agent-internal finding format (pre-transformation).
    Missing id/agent/skill/run_id/timestamp/analysis_unit fields.
    These are added by the Reporting Lead during merge.
    From agent-prompts.md section 4c.
    """

    severity: Severity
    category: str
    title: str = Field(max_length=120)
    description: str
    citations: list[Citation] = Field(min_length=1)
    confidence: Confidence

    @field_validator("severity", mode="before")
    @classmethod
    def coerce_severity(cls, v: Any) -> Severity:
        return _coerce_severity(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, v: Any) -> Confidence:
        return _coerce_confidence(v)


class Gap(BaseModel):
    """
    Missing document or data gap. From domain-definitions.md section 6d.
    Every gap MUST have all required fields -- missing fields cause QA failure.
    """

    customer: str
    priority: Severity
    gap_type: GapType
    missing_item: str = Field(max_length=200)
    why_needed: str
    risk_if_missing: str
    request_to_company: str
    evidence: str
    detection_method: DetectionMethod
    source_file: str | None = None  # Recommended
    agent: AgentName | None = None  # Recommended
    run_id: str | None = None  # Recommended

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, v: Any) -> Severity:
        return _coerce_severity(v)

    @field_validator("agent", mode="before")
    @classmethod
    def coerce_agent(cls, v: Any) -> AgentName | None:
        if v is None:
            return None
        return _coerce_agent_name(v)


class CrossReferenceData(BaseModel):
    """Per-file cross-reference data extracted from document. From domain-definitions.md section 1."""

    contract_value: str | None = None
    pricing_terms: str | None = None
    term_dates: dict[str, str] | None = None  # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    payment_terms: str | None = None
    discount_pct: str | None = None


class FileHeader(BaseModel):
    """
    Per-file extraction header. From domain-definitions.md section 1.
    Recorded in the customer JSON for every file processed.
    """

    file_path: str
    text_path: str | None = None
    doc_type_guess: str  # MSA, Order Form, SOW, Amendment, etc.
    effective_date_guess: str | None = None  # YYYY-MM-DD or None
    expiry_date_guess: str | None = None  # YYYY-MM-DD or None
    parties: list[str] = Field(default_factory=list)
    governed_by: str  # File path, "SELF", or "UNRESOLVED"
    references_found: list[str] = Field(default_factory=list)
    content_summary: str = ""
    cross_reference_data: CrossReferenceData = Field(default_factory=CrossReferenceData)

    @field_validator("governed_by")
    @classmethod
    def validate_governed_by(cls, v: str) -> str:
        """
        Ensures governed_by is either a valid file path (contains '/' or '.'),
        "SELF", or "UNRESOLVED".
        """
        if v in ("SELF", "UNRESOLVED"):
            return v
        if "/" in v or "." in v:
            return v
        raise ValueError(f"governed_by must be a file path (contains '/' or '.'), 'SELF', or 'UNRESOLVED'. Got: '{v}'")


class CrossReferenceSource(BaseModel):
    """Source location for a cross-reference data point."""

    file: str = ""
    page: int | str | None = None
    quote: str = ""
    tab: str | None = None
    row: str | None = None


class CrossReference(BaseModel):
    """
    Cross-reference entry comparing contract data vs reference data.
    From domain-definitions.md section 7a.
    """

    data_type: str = ""  # financial, pricing, entity, operational
    data_point: str  # "ARR", "Payment Terms", etc.
    contract_value: str = ""
    contract_source: CrossReferenceSource = Field(default_factory=CrossReferenceSource)
    reference_value: str = ""
    reference_source: CrossReferenceSource = Field(default_factory=CrossReferenceSource)
    match_status: str = Field(default="unverified", description="match, mismatch, not_available, or unverified")
    variance: str = ""  # e.g., "-20.8%"
    severity: Severity | None = None
    interpretation: str = ""

    @field_validator("match_status", mode="before")
    @classmethod
    def coerce_match_status(cls, v: Any) -> str:
        """Coerce common match_status variants to canonical values."""
        if not isinstance(v, str):
            _logger.warning("Non-string match_status %r coerced to 'unverified'", v)
            return "unverified"
        raw: str = v.strip()
        # Check aliases first
        if raw in _MATCH_STATUS_ALIASES:
            return _MATCH_STATUS_ALIASES[raw]
        # Accept canonical values
        if raw in _VALID_MATCH_STATUSES:
            return raw
        # Unknown value -> unverified with warning
        _logger.warning("Unknown match_status %r coerced to 'unverified'", raw)
        return "unverified"


class CrossReferenceSummary(BaseModel):
    """Per-customer cross-reference summary. From domain-definitions.md section 7f."""

    reference_files_checked: list[str] = Field(default_factory=list)
    data_points_compared: int = 0
    matches: int = 0
    mismatches: int = 0
    not_available: int = 0
    findings_generated: int = 0
    gaps_generated: int = 0


class CustomerAnalysis(BaseModel):
    """
    Per-customer output from each specialist agent.
    From agent-prompts.md section 4c.
    Written to {RUN_DIR}/findings/{agent}/{customer_safe_name}.json
    """

    customer: str  # Canonical customer name
    customer_safe_name: str  # Safe name per SKILL.md 1b convention
    agent: AgentName
    run_id: str
    timestamp: str  # ISO-8601 completion timestamp
    files_analyzed: int  # Count of files processed
    file_headers: list[FileHeader] = Field(default_factory=list)
    governance_graph: GovernanceGraph = Field(default_factory=GovernanceGraph)
    findings: list[AgentFinding] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    cross_references: list[CrossReference] = Field(default_factory=list)
    cross_reference_summary: CrossReferenceSummary | None = None
    diagrams: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Incremental mode fields in metadata:
    # _carried_forward: bool
    # _original_run_id: str
    # _consecutive_unchanged_runs: int


class MergedCustomerOutput(BaseModel):
    """
    Merged per-customer output. Written to {RUN_DIR}/findings/merged/{customer_safe_name}.json.
    From reporting-protocol.md section 1.
    """

    customer: str
    customer_safe_name: str
    findings: list[Finding] = Field(
        default_factory=list, description="Fully transformed findings conforming to finding.schema.json"
    )
    gaps: list[Gap] = Field(
        default_factory=list, description="Collected gaps from all specialist agents (step 6 of merge protocol)"
    )
    cross_references: list[CrossReference] = Field(default_factory=list)
    cross_reference_summary: CrossReferenceSummary | None = None
    governance_graph: GovernanceGraph = Field(default_factory=GovernanceGraph)
    governance_resolved_pct: float = Field(
        default=0.0, ge=0.0, le=1.0, description="(files with governed_by in [file_path, SELF]) / total_customer_files"
    )
