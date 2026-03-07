"""Pydantic models for data room inventory: files, customers, mentions, and counts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FileEntry(BaseModel):
    """Individual file in the data room."""

    path: str
    text_path: str | None = None  # Path to extracted text, or None
    mime_type: str = ""
    size: int = 0
    checksum: str = ""  # SHA-256


class CustomerEntry(BaseModel):
    """One customer in the customer registry (customers.csv row)."""

    group: str  # Group folder name
    name: str  # Customer display name
    safe_name: str  # customer_safe_name convention
    path: str  # Customer directory path
    file_count: int = 0
    files: list[str] = Field(default_factory=list)  # List of file paths


class ReferenceFile(BaseModel):
    """
    Global reference file (not under a customer directory).
    From SKILL.md section 2b.
    """

    file_path: str  # Original file path (REQUIRED)
    text_path: str | None = None  # Extracted text path, or None
    category: str  # Financial, Pricing, Corporate/Legal, etc.
    subcategory: str  # Finer classification
    description: str  # 1-2 sentence description
    customers_mentioned: list[str] = Field(default_factory=list)
    customers_mentioned_count: int = 0
    data_points_extractable: list[str] = Field(default_factory=list)
    assigned_to_agents: list[str] = Field(
        min_length=1, description="Every reference file must be assigned to at least one agent"
    )


class CountsJson(BaseModel):
    """Aggregate inventory counts. From SKILL.md section 2a."""

    total_files: int = 0
    total_customers: int = 0
    total_reference_files: int = 0
    files_by_extension: dict[str, int] = Field(default_factory=dict)
    files_by_group: dict[str, int] = Field(default_factory=dict)
    customers_by_group: dict[str, int] = Field(default_factory=dict)


class CustomerMention(BaseModel):
    """
    Customer-mention index entry. From SKILL.md section 2c.
    Records which customers are mentioned in which reference files.
    """

    customer_name: str
    customer_safe_name: str
    reference_files: list[str] = Field(default_factory=list)
    mention_count: int = 0


class CustomerMentionIndex(BaseModel):
    """Complete customer-mention index. Written to customer_mentions.json."""

    matches: list[CustomerMention] = Field(default_factory=list)
    unmatched_in_reference: list[str] = Field(
        default_factory=list, description="Names in reference files not matching any customer folder (ghost customers)"
    )
    customers_without_reference_data: list[str] = Field(
        default_factory=list, description="Customer folders with no mentions in any reference file (phantom contracts)"
    )


class ExtractionQualityEntry(BaseModel):
    """Extraction quality record for a single file. From SKILL.md section 1b."""

    file_path: str
    method: str  # ExtractionQualityMethod value
    bytes_extracted: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_chain: list[str] = Field(default_factory=list, description="Methods attempted in order")
    failure_reasons: list[str] = Field(default_factory=list, description="Diagnostic strings for each gate failure")
    source_language: str = Field(
        default="en", description="ISO 639-1 language code detected during extraction (Issue #144)"
    )
