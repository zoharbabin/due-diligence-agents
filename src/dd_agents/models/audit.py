from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dd_agents.models.enums import (  # noqa: TC001
    AuditAction,
    SpotCheckDimension,
    SpotCheckResult,
)


class AuditEntry(BaseModel):
    """
    Single audit log entry (one JSONL line).
    From dd-framework/schemas/audit-entry.schema.json.
    """

    ts: str  # ISO-8601 timestamp
    agent: str  # Agent name
    skill: str = "forensic-dd"
    action: AuditAction
    target: str  # What was acted upon
    result: str  # Outcome
    details: str = ""


class AuditCheck(BaseModel):
    """
    Individual QA check result within the consolidated audit.
    Each check maps to one or more DoD items from section 9.
    """

    passed: bool
    dod_checks: list[int] = Field(default_factory=list)  # DoD check numbers
    details: dict[str, Any] = Field(default_factory=dict)
    rule: str = Field(default="", description="Human-readable rule description")


class AuditSummary(BaseModel):
    """Summary statistics within audit.json."""

    total_customers: int = 0
    total_files: int = 0
    total_findings: int = 0
    total_gaps: int = 0
    findings_by_severity: dict[str, int] = Field(default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0})
    gaps_by_priority: dict[str, int] = Field(default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0})
    clean_result_count: int = 0
    agents_producing_gaps: list[str] = Field(default_factory=list)


class AuditReport(BaseModel):
    """
    Consolidated audit output. Written to {RUN_DIR}/audit.json.
    From SKILL.md section 8h.
    """

    audit_passed: bool
    timestamp: str  # ISO-8601
    run_id: str
    checks: dict[str, AuditCheck] = Field(default_factory=dict)
    summary: AuditSummary = Field(default_factory=AuditSummary)


# --- Quality / Judge Models ---
# From agent-prompts.md section 6e, quality-score.schema.json


class SpotCheck(BaseModel):
    """
    Individual spot-check result from the Judge.
    From agent-prompts.md section 6e.
    """

    finding_id: str
    agent: str  # AgentName value
    analysis_unit: str  # Customer name
    severity: str  # Severity value
    dimension: SpotCheckDimension
    result: SpotCheckResult
    notes: str = ""


class Contradiction(BaseModel):
    """
    Inter-agent factual contradiction identified by the Judge.
    From agent-prompts.md section 6e.
    """

    analysis_unit: str  # Customer name
    agents: list[str]  # AgentName values
    fact_in_dispute: str
    resolution: str
    winning_agent: str  # AgentName value


class AgentScoreDimensions(BaseModel):
    """Per-dimension scores for an agent. From agent-prompts.md section 6d."""

    citation_verification: int = Field(default=0, ge=0, le=100)
    contextual_validation: int = Field(default=0, ge=0, le=100)
    financial_accuracy: int = Field(default=0, ge=0, le=100)
    cross_agent_consistency: int = Field(default=0, ge=0, le=100)
    completeness: int = Field(default=0, ge=0, le=100)


class AgentScore(BaseModel):
    """
    Judge quality score for one agent.
    From agent-prompts.md section 6e.
    """

    model_config = ConfigDict(populate_by_name=True)

    score: int = Field(ge=0, le=100)
    findings_reviewed: int = 0
    findings_total: int = 0
    pass_count: int = Field(default=0, alias="pass")
    # NOTE: Using "pass" as a Pydantic alias is safe. Pydantic aliases are
    # string keys for serialization/deserialization, not Python identifiers.
    # The Python field name is `pass_count`; "pass" is only used in JSON I/O.
    partial: int = 0
    fail: int = 0
    dimensions: AgentScoreDimensions = Field(default_factory=AgentScoreDimensions)


class UnitScore(BaseModel):
    """Per-customer (analysis unit) quality score."""

    score: int = Field(ge=0, le=100)
    agents_reviewed: int = 0
    contradictions: int = 0


class QualityScores(BaseModel):
    """
    Complete Judge output file. Written to {RUN_DIR}/judge/quality_scores.json.
    Single file containing spot_checks and contradictions inline
    (NOT as separate files). From agent-prompts.md section 6e.
    """

    run_id: str
    skill: str = "forensic-dd"
    judge_config: dict[str, Any] = Field(default_factory=dict)
    agent_scores: dict[str, AgentScore] = Field(default_factory=dict)
    unit_scores: dict[str, UnitScore] = Field(default_factory=dict)
    overall_quality: int = Field(ge=0, le=100)
    iteration_round: int = 1
    agents_below_threshold: list[str] = Field(default_factory=list)
    spot_checks: list[SpotCheck] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
