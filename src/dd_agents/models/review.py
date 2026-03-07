"""Pydantic models for Collaborative Review & Annotation Layer (Issue #122)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Annotation(BaseModel):
    """A reviewer annotation on a specific finding."""

    id: str = Field(description="Unique annotation ID")
    finding_id: str = Field(description="ID of the annotated finding (title hash)")
    customer_safe_name: str = Field(default="", description="Customer the finding belongs to")
    reviewer: str = Field(description="Name or ID of the reviewer")
    timestamp: str = Field(description="ISO-8601 timestamp")
    comment: str = Field(default="", description="Reviewer's comment")
    status: str = Field(
        default="pending",
        description="pending | reviewed | disputed | accepted | rejected",
    )
    severity_override: str | None = Field(
        default=None,
        description="Override severity (P0-P4) with justification",
    )
    severity_justification: str = Field(default="", description="Reason for severity change")


class ReviewAssignment(BaseModel):
    """Assignment of a report section or domain to a reviewer."""

    id: str = Field(description="Unique assignment ID")
    reviewer: str = Field(description="Assigned reviewer name/ID")
    section: str = Field(default="", description="Report section name (e.g. 'legal', 'finance')")
    customer_safe_name: str = Field(default="", description="Specific customer if assigned per-entity")
    assigned_at: str = Field(description="ISO-8601 timestamp")
    signed_off: bool = Field(default=False, description="Whether the reviewer has signed off")
    signed_off_at: str | None = Field(default=None, description="ISO-8601 sign-off timestamp")


class ReviewProgress(BaseModel):
    """Aggregated review progress for a report."""

    total_findings: int = Field(default=0)
    reviewed: int = Field(default=0)
    disputed: int = Field(default=0)
    accepted: int = Field(default=0)
    pending: int = Field(default=0)
    pct_complete: float = Field(default=0.0, description="Percentage reviewed (0-100)")
    by_section: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Progress counts per section",
    )
    by_reviewer: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Progress counts per reviewer",
    )


class ReviewState(BaseModel):
    """Complete review state for a report run."""

    version: int = Field(default=1)
    run_id: str = Field(default="")
    annotations: list[Annotation] = Field(default_factory=list)
    assignments: list[ReviewAssignment] = Field(default_factory=list)
    last_updated: str = Field(default="")
