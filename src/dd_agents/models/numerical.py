"""Pydantic models for numerical audit manifests and cross-document reconciliation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ManifestEntry(BaseModel):
    """
    A single traceable number in the numerical manifest.
    From numerical-validation.md section 1.
    """

    id: str  # N001, N002, ...
    label: str  # total_customers, total_files, etc.
    value: int | float
    source_file: str  # Path to source data
    derivation: str  # How the number was computed
    used_in: list[str] = Field(default_factory=list)  # Where it appears in outputs
    cross_check: str = ""  # Cross-source validation expression
    verified: bool = False  # Set to True after validation passes


class NumericalManifest(BaseModel):
    """
    Complete numerical manifest. Written to {RUN_DIR}/numerical_manifest.json.
    From numerical-validation.md section 1.
    Must contain at minimum entries N001-N010.
    """

    manifest_version: str = "1.0"
    generated_at: str  # ISO-8601
    numbers: list[ManifestEntry] = Field(
        default_factory=list, min_length=10, description="Must contain at minimum N001-N010"
    )
