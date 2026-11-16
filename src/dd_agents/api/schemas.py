"""Request and response models for the local API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data_room: str = Field(min_length=1, description="Absolute path to the data room folder")
    deal_type: str = Field(default="", max_length=60)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ScanSummary(BaseModel):
    total_files: int
    total_bytes: int
    by_extension: dict[str, int]
    truncated: bool = False


class ConfigError(BaseModel):
    loc: str
    msg: str
    type: str


class ConfigValidation(BaseModel):
    valid: bool
    errors: list[ConfigError] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    is_latest: bool
    has_findings: bool
    reports: list[str]


class FindingsPage(BaseModel):
    run_id: str
    total: int
    items: list[dict[str, Any]]
    facets: dict[str, dict[str, int]]
