from __future__ import annotations

from pydantic import BaseModel, Field


class FileRead(BaseModel):
    """File successfully read by an agent."""

    path: str
    extraction_quality: str  # primary, fallback_pdftotext, etc.
    pages_read: str = "all"
    bytes_analyzed: int = 0


class FileSkipped(BaseModel):
    """File skipped by an agent with reason."""

    path: str
    reason: str  # FileSkipReason value
    reason_detail: str


class FileFailed(BaseModel):
    """File that failed extraction after full fallback chain."""

    path: str
    reason: str
    fallback_attempted: bool = True  # MUST be true; false = QA failure
    fallback_result: str = ""


class ManifestCustomer(BaseModel):
    """Per-customer tracking within the coverage manifest."""

    name: str
    files_assigned: list[str] = Field(default_factory=list)
    files_processed: list[str] = Field(default_factory=list)
    files_skipped: list[str] = Field(default_factory=list)
    status: str = "complete"  # "complete" or "partial"


class CoverageManifest(BaseModel):
    """
    Agent coverage manifest. From agent-prompts.md section 4.
    Conforms to dd-framework/schemas/coverage-manifest.schema.json
    with forensic-dd customer-centric extensions.
    """

    agent: str  # AgentName value
    skill: str = "forensic-dd"
    run_id: str
    files_assigned: list[str] = Field(default_factory=list)
    files_read: list[FileRead] = Field(default_factory=list)
    files_skipped: list[FileSkipped] = Field(default_factory=list)
    files_failed: list[FileFailed] = Field(default_factory=list)
    coverage_pct: float = Field(ge=0.0, le=1.0)
    analysis_units_assigned: int = 0
    analysis_units_completed: int = 0
    customers: list[ManifestCustomer] = Field(default_factory=list)
    reference_files_processed: list[str] = Field(
        default_factory=list, description="Forensic-dd extension: reference file paths the agent analyzed"
    )
