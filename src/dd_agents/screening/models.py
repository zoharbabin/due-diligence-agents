"""Data shapes shared by list adapters, the matcher and the coverage report."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EntryKind = Literal["person", "organization", "vessel", "aircraft", "unknown"]
MatchBand = Literal["exact", "strong", "possible"]
CoverageStatus = Literal["screened", "stale", "missing", "failed"]


class ListEntry(BaseModel):
    """One listed party, normalised across sources."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Source id, e.g. ofac_sdn, un, eu, uk, or user:<name>")
    uid: str = Field(description="Id of the entry inside its source")
    name: str = Field(min_length=1, description="Primary name as published")
    aliases: list[str] = Field(default_factory=list, description="Other names, original script included")
    kind: EntryKind = "unknown"
    birth_years: list[int] = Field(default_factory=list, description="Birth years (dates vary in precision)")
    countries: list[str] = Field(default_factory=list, description="Nationality or address country, as published")
    programs: list[str] = Field(default_factory=list, description="Sanctions programs or list categories")
    url: str = Field(default="", description="Public reference for the entry")
    listed_on: str = Field(default="", description="ISO date the entry was listed, when published")
    remarks: str = ""


class ListSnapshot(BaseModel):
    """A downloaded and parsed list, as stored on disk."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str
    fetched_at: str = Field(description="ISO 8601 UTC time of download")
    published: str = Field(default="", description="Publication date stated by the source, if any")
    sha256: str = Field(description="SHA-256 of the raw downloaded bytes")
    entries: list[ListEntry]


class Coverage(BaseModel):
    """One row of the coverage table: what was screened against, and how."""

    model_config = ConfigDict(extra="forbid")

    source: str
    status: CoverageStatus
    list_date: str = Field(default="", description="Publication or download date of the list used")
    entry_count: int = 0
    detail: str = ""


class ScreenHit(BaseModel):
    """A possible match between a screened name and a list entry. Never a conclusion."""

    model_config = ConfigDict(extra="forbid")

    query: str
    query_kind: Literal["person", "organization"]
    entry: ListEntry
    matched_name: str = Field(description="Which name or alias matched")
    score: float = Field(ge=0.0, le=100.0)
    band: MatchBand
    corroboration: list[str] = Field(default_factory=list, description="e.g. birth year or country agrees")
