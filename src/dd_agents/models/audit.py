"""Pydantic models for QA audit results, checks, and agent scoring."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dd_agents.models.enums import (  # noqa: TC001
    AuditAction,
    SpotCheckDimension,
    SpotCheckResult,
)


def _sev_count_init() -> dict[str, int]:
    """Return ``{P0: 0, P1: 0, P2: 0, P3: 0}``.

    Delegates to :func:`dd_agents.utils.constants._sev_count_init` via a
    lazy import to avoid a circular import chain (models -> utils.constants
    -> extraction -> models).
    """
    from dd_agents.utils.constants import _sev_count_init as _impl

    return _impl()


class AuditEntry(BaseModel):
    """
    Single audit log entry (one JSONL line).
    From dd-framework/schemas/audit-entry.schema.json.
    """

    ts: str = Field(description="ISO-8601 timestamp of the action")
    agent: str = Field(description="Agent name that performed the action")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    action: AuditAction = Field(description="Type of audited action")
    target: str = Field(description="What was acted upon (file path, subject name, etc.)")
    result: str = Field(description="Outcome of the action")
    details: str = Field(default="", description="Additional context or diagnostic information")


class AuditCheck(BaseModel):
    """
    Individual QA check result within the consolidated audit.
    Each check maps to one or more DoD items from section 9.
    """

    passed: bool = Field(description="Whether this check passed")
    dod_checks: list[int] = Field(default_factory=list, description="DoD check numbers this result covers")
    details: dict[str, Any] = Field(default_factory=dict, description="Structured check-specific details")
    rule: str = Field(default="", description="Human-readable rule description")


class AuditSummary(BaseModel):
    """Summary statistics within audit.json."""

    total_subjects: int = Field(default=0, description="Number of subjects analyzed")
    total_files: int = Field(default=0, description="Total files in the data room")
    total_findings: int = Field(default=0, description="Total findings across all agents")
    total_gaps: int = Field(default=0, description="Total gaps across all agents")
    # String keys (not Severity enum) are intentional here: these dicts are
    # serialised directly to JSON and consumed by external tools that expect
    # plain string keys ("P0", "P1", etc.).
    findings_by_severity: dict[str, int] = Field(
        default_factory=_sev_count_init,
        description="Finding counts keyed by severity level",
    )
    gaps_by_priority: dict[str, int] = Field(
        default_factory=_sev_count_init,
        description="Gap counts keyed by priority level",
    )
    clean_result_count: int = Field(default=0, description="Number of domain_reviewed_no_issues findings")
    agents_producing_gaps: list[str] = Field(
        default_factory=list, description="Agent names that produced at least one gap"
    )


class AuditReport(BaseModel):
    """
    Consolidated audit output. Written to {RUN_DIR}/audit.json.
    From SKILL.md section 8h.
    """

    audit_passed: bool = Field(description="Whether all blocking audit checks passed")
    timestamp: str = Field(description="ISO-8601 timestamp of audit completion")
    run_id: str = Field(description="Unique run identifier")
    checks: dict[str, AuditCheck] = Field(default_factory=dict, description="Named check results")
    summary: AuditSummary = Field(default_factory=AuditSummary, description="Aggregate statistics")


# --- Quality / Judge Models ---
# From agent-prompts.md section 6e, quality-score.schema.json


class SpotCheck(BaseModel):
    """
    Individual spot-check result from the Judge.
    From agent-prompts.md section 6e.
    """

    finding_id: str = Field(description="Identifier of the finding being checked")
    agent: str = Field(description="AgentName value of the agent that produced the finding")
    analysis_unit: str = Field(description="Subject name being analyzed")
    severity: str = Field(description="Severity level of the finding (P0-P3)")
    dimension: SpotCheckDimension = Field(description="Quality dimension being evaluated")
    result: SpotCheckResult = Field(description="Check outcome: pass, partial, or fail")
    notes: str = Field(default="", description="Judge's explanation or commentary")


class Contradiction(BaseModel):
    """
    Inter-agent factual contradiction identified by the Judge.
    From agent-prompts.md section 6e.
    """

    analysis_unit: str = Field(description="Subject name where contradiction was found")
    agents: list[str] = Field(description="AgentName values of the contradicting agents")
    fact_in_dispute: str = Field(description="Description of the contradicted fact")
    resolution: str = Field(description="How the contradiction was resolved")
    winning_agent: str = Field(description="AgentName value of the agent whose version was accepted")


class AgentScoreDimensions(BaseModel):
    """Per-dimension scores for an agent. From agent-prompts.md section 6d."""

    citation_verification: int = Field(default=0, ge=0, le=100, description="Score for citation accuracy (0-100)")
    contextual_validation: int = Field(default=0, ge=0, le=100, description="Score for contextual correctness (0-100)")
    financial_accuracy: int = Field(default=0, ge=0, le=100, description="Score for numerical accuracy (0-100)")
    cross_agent_consistency: int = Field(
        default=0, ge=0, le=100, description="Score for consistency with other agents (0-100)"
    )
    completeness: int = Field(default=0, ge=0, le=100, description="Score for coverage completeness (0-100)")


class AgentScore(BaseModel):
    """
    Judge quality score for one agent.
    From agent-prompts.md section 6e.
    """

    model_config = ConfigDict(populate_by_name=True)

    score: int = Field(ge=0, le=100, description="Overall agent quality score (0-100)")
    findings_reviewed: int = Field(default=0, description="Number of findings spot-checked by the Judge")
    findings_total: int = Field(default=0, description="Total findings produced by the agent")
    pass_count: int = Field(default=0, alias="pass", description="Number of spot checks that passed")
    # NOTE: Using "pass" as a Pydantic alias is safe. Pydantic aliases are
    # string keys for serialization/deserialization, not Python identifiers.
    # The Python field name is `pass_count`; "pass" is only used in JSON I/O.
    partial: int = Field(default=0, description="Number of spot checks with partial pass")
    fail: int = Field(default=0, description="Number of spot checks that failed")
    dimensions: AgentScoreDimensions = Field(
        default_factory=AgentScoreDimensions, description="Per-dimension quality breakdown"
    )
    quality_tier: str = Field(default="full_pass", description="Quality tier: full_pass, advisory, conditional, fail")


class UnitScore(BaseModel):
    """Per-subject (analysis unit) quality score."""

    score: int = Field(ge=0, le=100, description="Quality score for this subject (0-100)")
    agents_reviewed: int = Field(default=0, description="Number of agents reviewed for this subject")
    contradictions: int = Field(default=0, description="Number of inter-agent contradictions found")


class QualityScores(BaseModel):
    """
    Complete Judge output file. Written to {RUN_DIR}/judge/quality_scores.json.
    Single file containing spot_checks and contradictions inline
    (NOT as separate files). From agent-prompts.md section 6e.
    """

    run_id: str = Field(description="Unique run identifier")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    judge_config: dict[str, Any] = Field(default_factory=dict, description="Judge configuration snapshot")
    agent_scores: dict[str, AgentScore] = Field(default_factory=dict, description="Quality scores keyed by agent name")
    unit_scores: dict[str, UnitScore] = Field(default_factory=dict, description="Quality scores keyed by subject name")
    overall_quality: int = Field(ge=0, le=100, description="Aggregate quality score across all agents (0-100)")
    iteration_round: int = Field(default=1, description="Current Judge iteration round (1-based)")
    agents_below_threshold: list[str] = Field(
        default_factory=list, description="Agents scoring below the configured threshold"
    )
    spot_checks: list[SpotCheck] = Field(default_factory=list, description="Individual finding spot-check results")
    contradictions: list[Contradiction] = Field(
        default_factory=list, description="Inter-agent contradictions identified"
    )
