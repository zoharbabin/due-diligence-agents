"""Pydantic models for numerical audit manifests and cross-document reconciliation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    """
    A single traceable number in the numerical manifest.
    From numerical-validation.md section 1.
    """

    id: str = Field(description="Manifest entry identifier (e.g. N001, N002)")
    label: str = Field(description="Human-readable label (e.g. total_subjects, total_files)")
    value: int | float = Field(description="The numeric value being tracked")
    source_file: str = Field(description="Path to the source data file")
    derivation: str = Field(description="How the number was computed (formula or method)")
    used_in: list[str] = Field(default_factory=list, description="Output files where this number appears")
    cross_check: str = Field(default="", description="Cross-source validation expression")
    verified: bool = Field(default=False, description="Set to True after validation passes")


class NumericalManifest(BaseModel):
    """
    Complete numerical manifest. Written to {RUN_DIR}/numerical_manifest.json.
    From numerical-validation.md section 1.
    Must contain at minimum entries N001-N010.
    """

    manifest_version: str = Field(default="1.0", description="Schema version of the manifest format")
    generated_at: str = Field(description="ISO-8601 timestamp of manifest generation")
    numbers: list[ManifestEntry] = Field(
        default_factory=list, min_length=10, description="Must contain at minimum N001-N010"
    )
