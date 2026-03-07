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
    total_runs: int = Field(default=0, ge=0)
    total_customers: int = Field(default=0, ge=0)
    total_findings: int = Field(default=0, ge=0)
    finding_counts: dict[str, int] = Field(default_factory=dict, description="Finding counts by severity")
    deal_type: str = Field(default="", description="acquisition, merger, etc.")
    buyer: str = Field(default="", description="Buyer company name")
    target: str = Field(default="", description="Target company name")
    risk_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Overall risk score 0-100")
    notes: str = Field(default="")
    locked_by: int | None = Field(default=None, description="PID if currently running")


class ProjectRegistry(BaseModel):
    """Global registry of all deal projects."""

    version: int = Field(default=1, description="Registry format version")
    base_dir: str = Field(description="Base directory for the registry file")
    projects: list[ProjectEntry] = Field(default_factory=list)
    last_updated: str = Field(default="")


class PortfolioComparison(BaseModel):
    """Cross-deal comparison data for portfolio view."""

    projects: list[ProjectEntry] = Field(default_factory=list)
    total_arr: float = Field(default=0.0, description="Sum of ARR across all deals")
    avg_risk_score: float = Field(default=0.0, description="Average risk score")
    total_findings: int = Field(default=0)
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    risk_benchmarks: dict[str, float] = Field(default_factory=dict, description="Risk score percentiles")
