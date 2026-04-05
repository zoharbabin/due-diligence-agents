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
    "consistent": "match",
    "approximate_match": "match",
    "reference_only": "not_available",
    "derived": "match",
    "informational": "not_available",
    "explainable_difference": "mismatch",
    "concern": "mismatch",
    "gap": "not_available",
    "unverifiable": "unverified",
}

_VALID_MATCH_STATUSES: set[str] = {s.value for s in MatchStatus}

_VALID_DETECTION_METHODS: set[str] = {d.value for d in DetectionMethod}

_DETECTION_METHOD_ALIASES: dict[str, str] = {
    "": "checklist",
    "keyword_search": "pattern_check",
    "document_review": "checklist",
    "questionnaire": "checklist",
    "manual_review": "checklist",
    "pattern": "pattern_check",
    "cross_ref": "cross_reference",
    "crossref": "cross_reference",
    "governance": "governance_resolution",
}


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


class FindingProvenance(BaseModel):
    """Per-finding audit trail for chain of custody (#145)."""

    extraction_method: str = Field(
        default="unknown", description="Extraction method: pymupdf, glm_ocr, markitdown, etc."
    )
    extraction_confidence: float = Field(default=0.0, description="Extraction confidence 0.0-1.0")
    agent_name: str = Field(default="", description="Agent that produced the finding")
    citation_verified: bool = Field(default=False, description="Whether citation was independently verified")
    merge_action: str = Field(
        default="kept", description="Merge action: kept, severity_escalated, deduped, semantic_deduped"
    )
    contributing_agents: list[str] = Field(default_factory=list, description="All agents that identified this finding")
    recalibrated: bool = Field(default=False, description="Whether severity was recalibrated")
    recalibration_reason: str = Field(default="", description="Reason for recalibration if applied")


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

    source_type: SourceType = Field(description="Source type: file, database, or web_research")
    source_path: str = Field(description="Path to the source document or URL")
    location: str = Field(default="", description="Location within the source (e.g. 'Section X.Y' or page number)")
    exact_quote: str | None = Field(
        default=None,
        description="Verbatim text from the document. OMIT (do not set to null) "
        "for clean-result findings. Serialize with exclude_none=True.",
    )
    # NOTE: exact_quote is stored as a plain string. When the quote contains
    # special characters (newlines, quotes), they are escaped using standard
    # JSON string escaping. No custom serializer needed -- Pydantic v2 handles
    # this natively via model_dump_json().
    access_date: str | None = Field(default=None, description="Access date (required when source_type is web_research)")
    source_language: str | None = Field(
        default=None,
        description="ISO 639-1 language code of the source document (Issue #144).",
    )
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
    Produced during the merge step (step 24), not by specialist agents directly.
    """

    id: str = Field(
        pattern=r"^[a-z][a-z0-9-]*_[a-z][a-z0-9_-]*_\d{4,}$",
        description="Format: {skill}_{agent}_{sequential_number} e.g. forensic-dd_legal_0001",
    )
    severity: Severity = Field(description="Finding severity: P0 (deal-stopper) through P3 (informational)")
    category: str = Field(description="Finding category (e.g. change_of_control, termination)")
    title: str = Field(max_length=120, description="Brief finding title (max 120 chars)")
    description: str = Field(description="Detailed description of the finding")
    citations: list[Citation] = Field(min_length=1, description="Supporting citations (at least one required)")
    confidence: Confidence = Field(description="Confidence level: high, medium, or low")
    agent: AgentName = Field(description="Agent that produced this finding")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    run_id: str = Field(description="Unique run identifier")
    timestamp: str = Field(description="ISO-8601 timestamp of finding creation")
    analysis_unit: str = Field(description="Customer name this finding pertains to")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional key-value metadata")

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
    These are added during the merge step (step 24).
    From agent-prompts.md section 4c.
    """

    severity: Severity = Field(description="Finding severity: P0 through P3")
    category: str = Field(description="Finding category")
    title: str = Field(max_length=120, description="Brief finding title (max 120 chars)")
    description: str = Field(description="Detailed description of the finding")
    citations: list[Citation] = Field(min_length=1, description="Supporting citations (at least one required)")
    confidence: Confidence = Field(description="Confidence level: high, medium, or low")
    verified: bool | None = Field(
        default=None,
        description="Set by P0/P1 self-verification loop (Issue #140). "
        "True if finding passed all 4 verification steps.",
    )
    verification_note: str | None = Field(
        default=None,
        description="Explanation of verification outcome or severity adjustment.",
    )

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

    customer: str = Field(description="Customer name this gap pertains to")
    priority: Severity = Field(description="Gap priority: P0 through P3")
    gap_type: GapType = Field(description="Type of gap: Missing_Doc, Incomplete_Doc, etc.")
    missing_item: str = Field(max_length=200, description="What is missing (max 200 chars)")
    why_needed: str = Field(description="Why this item is needed for due diligence")
    risk_if_missing: str = Field(description="Risk to the deal if this gap is not resolved")
    request_to_company: str = Field(description="Specific request to send to the target company")
    evidence: str = Field(description="Evidence supporting the gap identification")
    detection_method: DetectionMethod = Field(description="How the gap was detected")
    source_file: str | None = Field(default=None, description="Source file where gap was identified")
    agent: AgentName | None = Field(default=None, description="Agent that identified this gap")
    run_id: str | None = Field(default=None, description="Run ID when gap was identified")

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, v: Any) -> Severity:
        return _coerce_severity(v)

    @field_validator("detection_method", mode="before")
    @classmethod
    def coerce_detection_method(cls, v: Any) -> str:
        """Coerce common detection_method variants to canonical values."""
        if isinstance(v, DetectionMethod):
            return v.value
        if not isinstance(v, str):
            _logger.warning("Non-string detection_method %r coerced to 'checklist'", v)
            return "checklist"
        raw: str = v.strip().lower()
        if raw in _DETECTION_METHOD_ALIASES:
            return _DETECTION_METHOD_ALIASES[raw]
        if raw in _VALID_DETECTION_METHODS:
            return raw
        _logger.warning("Unknown detection_method %r coerced to 'checklist'", v)
        return "checklist"

    @field_validator("agent", mode="before")
    @classmethod
    def coerce_agent(cls, v: Any) -> AgentName | None:
        if v is None:
            return None
        return _coerce_agent_name(v)


class CrossReferenceData(BaseModel):
    """Per-file cross-reference data extracted from document. From domain-definitions.md section 1."""

    contract_value: str | None = Field(default=None, description="Total contract value extracted from document")
    pricing_terms: str | None = Field(default=None, description="Pricing terms extracted from document")
    term_dates: dict[str, str] | None = Field(
        default=None, description="Contract term dates: {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}"
    )
    payment_terms: str | None = Field(default=None, description="Payment terms (e.g. 'Net 30')")
    discount_pct: str | None = Field(default=None, description="Discount percentage if applicable")


class FileHeader(BaseModel):
    """
    Per-file extraction header. From domain-definitions.md section 1.
    Recorded in the customer JSON for every file processed.
    """

    file_path: str = Field(description="File path relative to data room root")
    text_path: str | None = Field(default=None, description="Path to extracted text file")
    doc_type_guess: str = Field(description="Guessed document type: MSA, Order Form, SOW, Amendment, etc.")
    effective_date_guess: str | None = Field(default=None, description="Guessed effective date (YYYY-MM-DD)")
    expiry_date_guess: str | None = Field(default=None, description="Guessed expiry date (YYYY-MM-DD)")
    parties: list[str] = Field(default_factory=list, description="Party names identified in the document")
    governed_by: str = Field(description="Governing document: file path, 'SELF', or 'UNRESOLVED'")
    references_found: list[str] = Field(default_factory=list, description="File paths referenced by this document")
    content_summary: str = Field(default="", description="Brief summary of document contents")
    cross_reference_data: CrossReferenceData = Field(
        default_factory=CrossReferenceData, description="Extracted cross-reference data points"
    )

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

    file: str = Field(default="", description="Source file path")
    page: int | str | None = Field(default=None, description="Page number or reference")
    quote: str = Field(default="", description="Exact quote from the source")
    tab: str | None = Field(default=None, description="Excel sheet/tab name if applicable")
    row: str | None = Field(default=None, description="Row reference if from a spreadsheet")


class CrossReference(BaseModel):
    """
    Cross-reference entry comparing contract data vs reference data.
    From domain-definitions.md section 7a.
    """

    data_type: str = Field(default="", description="Data category: financial, pricing, entity, or operational")
    data_point: str = Field(description="Data point name (e.g. 'ARR', 'Payment Terms')")
    contract_value: str = Field(default="", description="Value found in the contract")
    contract_source: CrossReferenceSource = Field(
        default_factory=CrossReferenceSource, description="Location of the contract value"
    )
    reference_value: str = Field(default="", description="Value found in the reference data")
    reference_source: CrossReferenceSource = Field(
        default_factory=CrossReferenceSource, description="Location of the reference value"
    )
    match_status: str = Field(default="unverified", description="match, mismatch, not_available, or unverified")
    variance: str = Field(default="", description="Calculated variance (e.g. '-20.8%')")
    severity: Severity | None = Field(default=None, description="Severity if mismatch generates a finding")
    interpretation: str = Field(default="", description="Analyst interpretation of the comparison")

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

    reference_files_checked: list[str] = Field(
        default_factory=list, description="Reference files used for cross-referencing"
    )
    data_points_compared: int = Field(default=0, description="Total data points compared")
    matches: int = Field(default=0, description="Number of matching data points")
    mismatches: int = Field(default=0, description="Number of mismatched data points")
    not_available: int = Field(default=0, description="Data points where comparison was not possible")
    findings_generated: int = Field(default=0, description="Findings generated from mismatches")
    gaps_generated: int = Field(default=0, description="Gaps generated from missing data")


class CustomerAnalysis(BaseModel):
    """
    Per-customer output from each specialist agent.
    From agent-prompts.md section 4c.
    Written to {RUN_DIR}/findings/{agent}/{customer_safe_name}.json
    """

    customer: str = Field(description="Canonical customer name")
    customer_safe_name: str = Field(description="Normalized safe name per SKILL.md 1b convention")
    agent: AgentName = Field(description="Agent that produced this analysis")
    run_id: str = Field(description="Unique run identifier")
    timestamp: str = Field(description="ISO-8601 completion timestamp")
    files_analyzed: int = Field(description="Count of files processed for this customer")
    file_headers: list[FileHeader] = Field(default_factory=list, description="Per-file extraction headers")
    governance_graph: GovernanceGraph = Field(
        default_factory=GovernanceGraph, description="Contract governance graph for this customer"
    )
    findings: list[AgentFinding] = Field(default_factory=list, description="Findings produced by the agent")
    gaps: list[Gap] = Field(default_factory=list, description="Gaps identified by the agent")
    cross_references: list[CrossReference] = Field(default_factory=list, description="Cross-reference comparisons")
    cross_reference_summary: CrossReferenceSummary | None = Field(
        default=None, description="Aggregate cross-reference statistics"
    )
    diagrams: list[dict[str, Any]] = Field(default_factory=list, description="Generated diagrams (e.g. mermaid)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional key-value metadata")
    # Incremental mode fields in metadata:
    # _carried_forward: bool
    # _original_run_id: str
    # _consecutive_unchanged_runs: int


class MergedCustomerOutput(BaseModel):
    """
    Merged per-customer output. Written to {RUN_DIR}/findings/merged/{customer_safe_name}.json.
    From reporting-protocol.md section 1.
    """

    customer: str = Field(description="Canonical customer name")
    customer_safe_name: str = Field(description="Normalized safe name for file naming")
    findings: list[Finding] = Field(
        default_factory=list, description="Fully transformed findings conforming to finding.schema.json"
    )
    gaps: list[Gap] = Field(
        default_factory=list, description="Collected gaps from all specialist agents (step 6 of merge protocol)"
    )
    cross_references: list[CrossReference] = Field(
        default_factory=list, description="Merged cross-reference comparisons from all agents"
    )
    cross_reference_summary: CrossReferenceSummary | None = Field(
        default=None, description="Aggregate cross-reference statistics"
    )
    governance_graph: GovernanceGraph = Field(
        default_factory=GovernanceGraph, description="Merged governance graph from all agents"
    )
    governance_resolved_pct: float = Field(
        default=0.0, ge=0.0, le=1.0, description="(files with governed_by in [file_path, SELF]) / total_customer_files"
    )
