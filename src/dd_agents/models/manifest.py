"""Pydantic models for coverage manifests (files read, skipped, and failed per customer)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileRead(BaseModel):
    """File successfully read by an agent."""

    path: str = Field(description="File path relative to data room root")
    extraction_quality: str = Field(description="Extraction method used (e.g. primary, fallback_pdftotext)")
    pages_read: str = Field(default="all", description="Pages read from the file (e.g. 'all', '1-10')")
    bytes_analyzed: int = Field(default=0, description="Number of bytes of extracted text analyzed")


class FileSkipped(BaseModel):
    """File skipped by an agent with reason."""

    path: str = Field(description="File path relative to data room root")
    reason: str = Field(description="FileSkipReason value explaining why the file was skipped")
    reason_detail: str = Field(description="Human-readable elaboration on the skip reason")


class FileFailed(BaseModel):
    """File that failed extraction after full fallback chain."""

    path: str = Field(description="File path relative to data room root")
    reason: str = Field(description="Reason for extraction failure")
    fallback_attempted: bool = Field(default=True, description="Whether the fallback chain was tried (must be True)")
    fallback_result: str = Field(default="", description="Outcome of the fallback attempt")


class ManifestCustomer(BaseModel):
    """Per-customer tracking within the coverage manifest."""

    name: str = Field(description="Customer safe name")
    files_assigned: list[str] = Field(default_factory=list, description="Files assigned to this customer")
    files_processed: list[str] = Field(default_factory=list, description="Files successfully processed")
    files_skipped: list[str] = Field(default_factory=list, description="Files skipped during processing")
    status: str = Field(default="complete", description="Processing status: 'complete' or 'partial'")


class CoverageManifest(BaseModel):
    """
    Agent coverage manifest. From agent-prompts.md section 4.
    Conforms to dd-framework/schemas/coverage-manifest.schema.json
    with forensic-dd customer-centric extensions.
    """

    agent: str = Field(description="AgentName value identifying the producing agent")
    skill: str = Field(default="forensic-dd", description="Skill identifier")
    run_id: str = Field(description="Unique run identifier")
    files_assigned: list[str] = Field(default_factory=list, description="All files assigned to this agent")
    files_read: list[FileRead] = Field(default_factory=list, description="Files successfully read and analyzed")
    files_skipped: list[FileSkipped] = Field(default_factory=list, description="Files skipped with reasons")
    files_failed: list[FileFailed] = Field(
        default_factory=list, description="Files that failed the full fallback chain"
    )
    coverage_pct: float = Field(ge=0.0, le=1.0, description="Fraction of assigned files successfully processed")
    analysis_units_assigned: int = Field(default=0, description="Number of customers assigned to this agent")
    analysis_units_completed: int = Field(default=0, description="Number of customers fully analyzed")
    customers: list[ManifestCustomer] = Field(default_factory=list, description="Per-customer processing details")
    reference_files_processed: list[str] = Field(
        default_factory=list, description="Forensic-dd extension: reference file paths the agent analyzed"
    )
