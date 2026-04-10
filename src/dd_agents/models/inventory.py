"""Pydantic models for data room inventory: files, subjects, mentions, and counts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileEntry(BaseModel):
    """Individual file in the data room."""

    path: str = Field(description="File path relative to data room root")
    text_path: str | None = Field(default=None, description="Path to extracted text, or None if not yet extracted")
    mime_type: str = Field(default="", description="MIME type of the file")
    size: int = Field(default=0, description="File size in bytes")
    checksum: str = Field(default="", description="SHA-256 checksum of the file")
    # Precedence metadata (Issue #163)
    mtime: float = Field(default=0.0, description="File modification timestamp (epoch seconds)")
    mtime_iso: str = Field(default="", description="Human-readable ISO-8601 modification time")
    version_indicator: str = Field(default="", description="Parsed from filename: v1, signed, draft, etc.")
    version_rank: int = Field(default=0, description="Version authority rank (higher = more authoritative)")
    folder_tier: int = Field(
        default=2, description="Folder trust tier: 1=authoritative, 2=working, 3=supplementary, 4=historical"
    )
    precedence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Composite precedence score")
    superseded_by: str = Field(default="", description="Path of file that supersedes this one")
    is_latest_version: bool = Field(default=True, description="False if superseded by another file")


class SubjectEntry(BaseModel):
    """One subject in the subject registry (subjects.csv row)."""

    model_config = ConfigDict(populate_by_name=True)

    group: str = Field(description="Group folder name containing this subject")
    name: str = Field(description="Subject display name")
    safe_name: str = Field(description="Normalized subject_safe_name for file naming")
    path: str = Field(description="Subject directory path relative to data room root")
    file_count: int = Field(default=0, description="Number of files belonging to this subject")
    files: list[str] = Field(default_factory=list, description="List of file paths for this subject")


class ReferenceFile(BaseModel):
    """
    Global reference file (not under a subject directory).
    From SKILL.md section 2b.
    """

    file_path: str = Field(description="Original file path relative to data room root")
    text_path: str | None = Field(default=None, description="Extracted text path, or None if not available")
    category: str = Field(description="High-level category (Financial, Pricing, Corporate/Legal, etc.)")
    subcategory: str = Field(description="Finer classification within the category")
    description: str = Field(description="1-2 sentence description of the file contents")
    subjects_mentioned: list[str] = Field(
        default_factory=list, description="Subject names mentioned in this reference file"
    )
    subjects_mentioned_count: int = Field(default=0, description="Number of distinct subjects mentioned")
    data_points_extractable: list[str] = Field(
        default_factory=list, description="Types of data points that can be extracted from this file"
    )
    assigned_to_agents: list[str] = Field(
        default_factory=list,
        description="Agents assigned to process this file (empty for DD Output files excluded from analysis)",
    )


class CountsJson(BaseModel):
    """Aggregate inventory counts. From SKILL.md section 2a."""

    total_files: int = Field(default=0, description="Total number of files in the data room")
    total_subjects: int = Field(default=0, description="Total number of distinct subjects")
    total_reference_files: int = Field(default=0, description="Number of global reference files")
    files_by_extension: dict[str, int] = Field(
        default_factory=dict, description="File counts keyed by extension (e.g. '.pdf': 42)"
    )
    files_by_group: dict[str, int] = Field(default_factory=dict, description="File counts keyed by group folder name")
    subjects_by_group: dict[str, int] = Field(
        default_factory=dict,
        description="Subject counts keyed by group folder name",
    )


class SubjectMention(BaseModel):
    """
    Subject-mention index entry. From SKILL.md section 2c.
    Records which subjects are mentioned in which reference files.
    """

    subject_name: str = Field(description="Subject display name")
    subject_safe_name: str = Field(description="Normalized subject_safe_name")
    reference_files: list[str] = Field(
        default_factory=list, description="Reference file paths that mention this subject"
    )
    mention_count: int = Field(default=0, description="Total number of mentions across reference files")


class SubjectMentionIndex(BaseModel):
    """Complete subject-mention index. Written to subject_mentions.json."""

    matches: list[SubjectMention] = Field(default_factory=list, description="Subjects with reference file mentions")
    unmatched_in_reference: list[str] = Field(
        default_factory=list, description="Names in reference files not matching any subject folder (ghost subjects)"
    )
    subjects_without_reference_data: list[str] = Field(
        default_factory=list, description="Subject folders with no mentions in any reference file (phantom contracts)"
    )


class ExtractionQualityEntry(BaseModel):
    """Extraction quality record for a single file. From SKILL.md section 1b."""

    file_path: str = Field(description="File path relative to data room root")
    method: str = Field(description="ExtractionQualityMethod value (e.g. primary, ocr, fallback)")
    bytes_extracted: int = Field(default=0, description="Number of bytes of text extracted")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Extraction confidence score (0.0-1.0)")
    fallback_chain: list[str] = Field(default_factory=list, description="Methods attempted in order")
    failure_reasons: list[str] = Field(default_factory=list, description="Diagnostic strings for each gate failure")
    source_language: str = Field(
        default="en", description="ISO 639-1 language code detected during extraction (Issue #144)"
    )
