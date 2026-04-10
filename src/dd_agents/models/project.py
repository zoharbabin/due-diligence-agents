"""Pydantic models for multi-project portfolio management (Issue #118)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectEntry(BaseModel):
    """Registry entry for one deal project."""

    name: str = Field(description="Human-readable deal name")
    slug: str = Field(description="Directory-safe name (lowercase, underscores)")
    path: str = Field(description="Absolute path to data room root")
    config_path: str = Field(default="", description="Path to deal-config.json")
    created_at: str = Field(description="ISO-8601 creation timestamp")
    last_run_at: str | None = Field(default=None, description="ISO-8601 of most recent run")
    last_run_id: str | None = Field(default=None, description="Most recent run ID")
    status: str = Field(default="created", description="created | running | completed | failed | archived")
    total_runs: int = Field(default=0, ge=0, description="Total pipeline runs completed")
    total_subjects: int = Field(default=0, ge=0, description="Total subjects in the data room")
    total_findings: int = Field(default=0, ge=0, description="Total findings across all runs")
    finding_counts: dict[str, int] = Field(default_factory=dict, description="Finding counts by severity")
    deal_type: str = Field(default="", description="acquisition, merger, etc.")
    buyer: str = Field(default="", description="Buyer company name")
    target: str = Field(default="", description="Target company name")
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Overall risk score 0-100")
    notes: str = Field(default="", description="Free-form notes about this deal")
    locked_by: int | None = Field(default=None, description="PID if currently running")


class ProjectRegistry(BaseModel):
    """Global registry of all deal projects."""

    version: int = Field(default=1, description="Registry format version")
    base_dir: str = Field(description="Base directory for the registry file")
    projects: list[ProjectEntry] = Field(default_factory=list, description="All registered deal projects")
    last_updated: str = Field(default="", description="ISO-8601 timestamp of last registry update")


class PortfolioComparison(BaseModel):
    """Cross-deal comparison data for portfolio view."""

    projects: list[ProjectEntry] = Field(default_factory=list, description="Projects included in comparison")
    total_arr: float = Field(default=0.0, description="Sum of ARR across all deals")
    avg_risk_score: float = Field(default=0.0, description="Average risk score")
    total_findings: int = Field(default=0, description="Total findings across all projects")
    severity_distribution: dict[str, int] = Field(
        default_factory=dict, description="Finding counts keyed by severity across all projects"
    )
    risk_benchmarks: dict[str, float] = Field(default_factory=dict, description="Risk score percentiles")
