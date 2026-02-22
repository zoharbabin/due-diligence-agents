from __future__ import annotations

from pydantic import BaseModel, Field

from dd_agents.models.enums import CustomerClassificationStatus  # noqa: TC001


class RunMetadata(BaseModel):
    """
    Run metadata. Written to {RUN_DIR}/metadata.json.
    From SKILL.md step 3 (initialization) and step 32 (finalization).
    """

    run_id: str
    timestamp: str  # ISO-8601
    skill: str = "forensic-dd"
    execution_mode: str  # "full" or "incremental"
    config_hash: str  # SHA-256 of deal-config.json
    framework_version: str = "unknown"
    cross_skill_run_ids: dict[str, str] = Field(
        default_factory=dict, description="Map of skill name to run_id for cross-skill data"
    )
    # Finalization fields (added at step 32):
    file_checksums: dict[str, str] = Field(default_factory=dict, description="Per-customer SHA-256 map")
    customer_assignments: dict[str, list[str]] = Field(default_factory=dict)
    finding_counts: dict[str, int] = Field(default_factory=dict)
    gap_counts: dict[str, int] = Field(default_factory=dict)
    agent_scores: dict[str, int] = Field(default_factory=dict)
    completion_status: str = "in_progress"  # in_progress, completed, failed
    batch_counts: dict[str, int] = Field(
        default_factory=dict, description="Number of batch instances spawned per agent type"
    )


class CustomerClassEntry(BaseModel):
    """
    Per-customer classification for incremental mode.
    From SKILL.md section 0e.
    """

    customer: str
    customer_safe_name: str
    classification: CustomerClassificationStatus
    reason: str
    files_added: list[str] = Field(default_factory=list)
    files_removed: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    prior_checksum: str | None = None  # Required for all non-NEW
    current_checksum: str | None = None  # Required for all non-NEW
    consecutive_unchanged_runs: int = 0


class ClassificationSummary(BaseModel):
    """Summary counts by classification status."""

    new: int = 0
    changed: int = 0
    stale_refresh: int = 0
    unchanged: int = 0
    deleted: int = 0


class Classification(BaseModel):
    """
    Customer classification document for incremental mode.
    Written to {RUN_DIR}/classification.json.
    From SKILL.md section 0e.
    """

    run_id: str
    execution_mode: str  # "incremental"
    prior_run_id: str | None = None
    classification_summary: ClassificationSummary = Field(default_factory=ClassificationSummary)
    customers: list[CustomerClassEntry] = Field(default_factory=list)


class AnalysisUnitCounts(BaseModel):
    """Analysis unit counts for run history."""

    total: int = 0
    analyzed: int = 0
    carried_forward: int = 0
    new: int = 0
    changed: int = 0
    stale_refresh: int = 0
    deleted: int = 0


class FindingCounts(BaseModel):
    """Finding counts for run history."""

    p0: int = 0
    p1: int = 0
    p2: int = 0
    p3: int = 0
    total: int = 0


class RunHistoryEntry(BaseModel):
    """
    Entry in _dd/run_history.json (shared across all DD skills).
    From SKILL.md step 33.
    """

    run_id: str
    skill: str = "forensic-dd"
    timestamp: str  # ISO-8601
    execution_mode: str  # "full" or "incremental"
    analysis_unit_counts: AnalysisUnitCounts = Field(default_factory=AnalysisUnitCounts)
    finding_counts: FindingCounts = Field(default_factory=FindingCounts)
    agent_scores: dict[str, int] = Field(default_factory=dict)
    judge_enabled: bool = False
    iteration_rounds: int = 0
