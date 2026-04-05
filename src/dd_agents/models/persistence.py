"""Pydantic models for run metadata, customer classifications, and incremental state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from dd_agents.models.enums import (
    CompletionStatus,
    CustomerClassificationStatus,  # noqa: TC001
    ExecutionMode,
)


class RunMetadata(BaseModel):
    """
    Run metadata. Written to {RUN_DIR}/metadata.json.
    From SKILL.md step 3 (initialization) and step 32 (finalization).
    """

    run_id: str = Field(description="Unique run identifier")
    timestamp: str = Field(description="ISO-8601 timestamp of run start")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    execution_mode: ExecutionMode = Field(description="Execution mode: 'full' or 'incremental'")
    config_hash: str = Field(description="SHA-256 hash of deal-config.json")
    framework_version: str = Field(default="unknown", description="Version of the dd-agents framework")
    cross_skill_run_ids: dict[str, str] = Field(
        default_factory=dict, description="Map of skill name to run_id for cross-skill data"
    )
    # Finalization fields (added at step 32):
    file_checksums: dict[str, str] = Field(default_factory=dict, description="Per-customer SHA-256 map")
    customer_assignments: dict[str, list[str]] = Field(
        default_factory=dict, description="Agent name to list of assigned customer safe names"
    )
    finding_counts: dict[str, int] = Field(default_factory=dict, description="Finding counts keyed by severity level")
    gap_counts: dict[str, int] = Field(default_factory=dict, description="Gap counts keyed by priority level")
    agent_scores: dict[str, int] = Field(default_factory=dict, description="Quality scores keyed by agent name")
    completion_status: CompletionStatus = Field(
        default=CompletionStatus.IN_PROGRESS, description="Run completion status"
    )
    batch_counts: dict[str, int] = Field(
        default_factory=dict, description="Number of batch instances spawned per agent type"
    )

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _coerce_execution_mode(cls, v: Any) -> ExecutionMode:
        """Coerce string values to ExecutionMode enum for backward compatibility."""
        if isinstance(v, str) and not isinstance(v, ExecutionMode):
            return ExecutionMode(v)
        return v  # type: ignore[no-any-return]

    @field_validator("completion_status", mode="before")
    @classmethod
    def _coerce_completion_status(cls, v: Any) -> CompletionStatus:
        """Coerce string values to CompletionStatus enum for backward compatibility."""
        if isinstance(v, str) and not isinstance(v, CompletionStatus):
            return CompletionStatus(v)
        return v  # type: ignore[no-any-return]


class CustomerClassEntry(BaseModel):
    """
    Per-customer classification for incremental mode.
    From SKILL.md section 0e.
    """

    customer: str = Field(description="Customer display name")
    customer_safe_name: str = Field(description="Normalized customer_safe_name")
    classification: CustomerClassificationStatus = Field(description="Classification status for this customer")
    reason: str = Field(description="Human-readable reason for the classification")
    files_added: list[str] = Field(default_factory=list, description="New files since the prior run")
    files_removed: list[str] = Field(default_factory=list, description="Files removed since the prior run")
    files_modified: list[str] = Field(default_factory=list, description="Files modified since the prior run")
    prior_checksum: str | None = Field(default=None, description="SHA-256 of prior run output (required for non-NEW)")
    current_checksum: str | None = Field(default=None, description="SHA-256 of current file set (required for non-NEW)")
    consecutive_unchanged_runs: int = Field(
        default=0, description="Number of consecutive runs with no changes (triggers stale_refresh)"
    )


class ClassificationSummary(BaseModel):
    """Summary counts by classification status."""

    new: int = Field(default=0, description="Customers classified as new")
    changed: int = Field(default=0, description="Customers with changed files")
    stale_refresh: int = Field(default=0, description="Unchanged customers due for stale refresh")
    unchanged: int = Field(default=0, description="Customers with no changes (carried forward)")
    deleted: int = Field(default=0, description="Customers removed from the data room")


class Classification(BaseModel):
    """
    Customer classification document for incremental mode.
    Written to {RUN_DIR}/classification.json.
    From SKILL.md section 0e.
    """

    run_id: str = Field(description="Unique run identifier")
    execution_mode: ExecutionMode = Field(description="Execution mode (always 'incremental' for this document)")
    prior_run_id: str | None = Field(default=None, description="Run ID of the prior run used for diffing")
    classification_summary: ClassificationSummary = Field(
        default_factory=ClassificationSummary, description="Aggregate counts by status"
    )
    customers: list[CustomerClassEntry] = Field(default_factory=list, description="Per-customer classification entries")

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _coerce_execution_mode(cls, v: Any) -> ExecutionMode:
        """Coerce string values to ExecutionMode enum for backward compatibility."""
        if isinstance(v, str) and not isinstance(v, ExecutionMode):
            return ExecutionMode(v)
        return v  # type: ignore[no-any-return]


class AnalysisUnitCounts(BaseModel):
    """Analysis unit counts for run history."""

    total: int = Field(default=0, description="Total analysis units (customers)")
    analyzed: int = Field(default=0, description="Units analyzed in this run")
    carried_forward: int = Field(default=0, description="Units carried from prior run (unchanged)")
    new: int = Field(default=0, description="New units added in this run")
    changed: int = Field(default=0, description="Units with changed files")
    stale_refresh: int = Field(default=0, description="Unchanged units refreshed due to staleness")
    deleted: int = Field(default=0, description="Units removed from the data room")


class FindingCounts(BaseModel):
    """Finding counts for run history."""

    p0: int = Field(default=0, description="Number of P0 (deal-stopper) findings")
    p1: int = Field(default=0, description="Number of P1 (high-risk) findings")
    p2: int = Field(default=0, description="Number of P2 (medium-risk) findings")
    p3: int = Field(default=0, description="Number of P3 (low-risk / informational) findings")
    total: int = Field(default=0, description="Total findings (must equal p0+p1+p2+p3)")

    @field_validator("total", mode="after")
    @classmethod
    def _validate_total_consistency(cls, v: int, info: Any) -> int:
        """Validate that total equals sum of p0+p1+p2+p3 when explicitly set.

        When total is 0 (default), it is accepted as-is only if all
        severity counts are also 0 (to allow incremental construction).
        Raises ValueError if total=0 but severity counts are non-zero.
        """
        if v == 0:
            p0 = info.data.get("p0", 0)
            p1 = info.data.get("p1", 0)
            p2 = info.data.get("p2", 0)
            p3 = info.data.get("p3", 0)
            if p0 + p1 + p2 + p3 > 0:
                msg = f"FindingCounts total=0 but severity counts sum to {p0 + p1 + p2 + p3}"
                raise ValueError(msg)
            return v
        data = info.data
        expected = data.get("p0", 0) + data.get("p1", 0) + data.get("p2", 0) + data.get("p3", 0)
        if v != expected:
            msg = f"total ({v}) must equal p0+p1+p2+p3 ({expected})"
            raise ValueError(msg)
        return v


class RunHistoryEntry(BaseModel):
    """
    Entry in _dd/run_history.json (shared across all DD skills).
    From SKILL.md step 33.
    """

    run_id: str = Field(description="Unique run identifier")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    timestamp: str = Field(description="ISO-8601 timestamp of run completion")
    execution_mode: ExecutionMode = Field(description="Execution mode: 'full' or 'incremental'")
    analysis_unit_counts: AnalysisUnitCounts = Field(
        default_factory=AnalysisUnitCounts, description="Customer-level analysis counts"
    )
    finding_counts: FindingCounts = Field(default_factory=FindingCounts, description="Finding counts by severity")
    agent_scores: dict[str, int] = Field(default_factory=dict, description="Quality scores keyed by agent name")
    judge_enabled: bool = Field(default=False, description="Whether the Judge agent was enabled for this run")
    iteration_rounds: int = Field(default=0, description="Number of Judge iteration rounds completed")

    @field_validator("execution_mode", mode="before")
    @classmethod
    def _coerce_execution_mode(cls, v: Any) -> ExecutionMode:
        """Coerce string values to ExecutionMode enum for backward compatibility."""
        if isinstance(v, str) and not isinstance(v, ExecutionMode):
            return ExecutionMode(v)
        return v  # type: ignore[no-any-return]
