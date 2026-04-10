"""Pydantic models for entity resolution: matches, cache entries, and match logs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntityMatch(BaseModel):
    """
    A confirmed entity match. From entity-resolution-protocol.md section 5.
    """

    source_name: str = Field(description="Name as found in the source dataset")
    source: str = Field(description="Source dataset: 'database', 'directory', or 'reference_file'")
    matched_name: str = Field(description="Name as found in the target dataset")
    target: str = Field(description="Target dataset: 'directory', 'database', or 'reference_file'")
    match_pass: int = Field(description="Which resolution pass matched (1-6)")
    match_method: str = Field(
        description="Method used: preprocessing, exact, alias_lookup, fuzzy, tfidf, or parent_child"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Match confidence score (0.0-1.0)")
    canonical_name: str = Field(description="Resolved canonical subject name")


class MatchAttempt(BaseModel):
    """Record of a single match pass attempt for an unmatched entity."""

    model_config = ConfigDict(populate_by_name=True)

    pass_num: int = Field(alias="pass", description="Pass number (1-6)")
    method: str = Field(description="Match method attempted")
    result: str = Field(description="Outcome: 'no_match' or 'below_threshold'")
    best_candidate: str | None = Field(default=None, description="Closest match found, if any")
    score: float | None = Field(default=None, description="Score of the best candidate, if any")


class UnmatchedEntity(BaseModel):
    """An entity that could not be matched after all 6 passes."""

    source_name: str = Field(description="Name as found in the source dataset")
    source: str = Field(description="Source dataset identifier")
    match_attempts: list[MatchAttempt] = Field(default_factory=list, description="Record of each pass attempted")
    resolution: str = Field(default="unmatched_gap_logged", description="Resolution status")


class RejectedMatch(BaseModel):
    """A match that was rejected (below threshold or on exclusion list)."""

    source_name: str = Field(description="Name as found in the source dataset")
    source: str = Field(description="Source dataset identifier")
    rejected_match: str = Field(description="Name of the rejected match candidate")
    match_pass: int = Field(description="Pass number where the match was rejected")
    score: float = Field(description="Similarity score of the rejected match")
    reason: str = Field(description="Rejection reason: 'below_threshold' or 'exclusion_list'")


class EntityMatchLog(BaseModel):
    """
    Complete entity match log. Written to entity_matches.json.
    From entity-resolution-protocol.md section 5.
    """

    matches: list[EntityMatch] = Field(default_factory=list, description="Successfully matched entities")
    unmatched: list[UnmatchedEntity] = Field(default_factory=list, description="Entities that could not be matched")
    rejected: list[RejectedMatch] = Field(default_factory=list, description="Matches rejected by threshold or rules")


class EntityCacheEntry(BaseModel):
    """
    Single entry in the PERMANENT entity resolution cache.
    From entity-resolution-protocol.md section 7.
    """

    canonical: str = Field(description="Canonical subject name")
    match_pass: int = Field(description="Pass number that confirmed this match")
    match_type: str = Field(description="Match method that confirmed this entry")
    confidence: float = Field(ge=0.0, le=1.0, description="Match confidence score (0.0-1.0)")
    entity_type: str = Field(default="subject", description="Entity type (currently always 'subject')")
    first_seen_run: str = Field(description="Run ID where this entry was first created")
    last_confirmed_run: str = Field(description="Run ID where this entry was last confirmed")
    confirmation_count: int = Field(default=1, description="Number of runs that confirmed this match")


class UnmatchedCacheEntry(BaseModel):
    """An unmatched entity persisted in the cache."""

    name: str = Field(description="Unmatched entity name")
    context: str = Field(default="", description="Source context where the name appeared")
    first_seen_run: str = Field(description="Run ID where this entry was first seen")


class EntityCacheConfigSnapshot(BaseModel):
    """Snapshot of entity_aliases config for per-entry invalidation diff."""

    canonical_to_variants: dict[str, list[str]] = Field(
        default_factory=dict, description="Canonical name to known variant names"
    )
    short_name_guard: list[str] = Field(
        default_factory=list, description="Short names requiring exact match (no fuzzy)"
    )
    exclusions: list[str] = Field(default_factory=list, description="Names excluded from entity resolution")
    parent_child: dict[str, list[str]] = Field(
        default_factory=dict, description="Parent company to subsidiary name mappings"
    )


class EntityCache(BaseModel):
    """
    PERMANENT tier entity resolution cache.
    Written to _dd/entity_resolution_cache.json.
    From entity-resolution-protocol.md section 7.
    """

    version: int = Field(default=1, description="Cache format version")
    last_updated: str = Field(description="ISO-8601 timestamp of last update")
    last_updated_by: str = Field(default="forensic-dd", description="Skill that last updated the cache")
    last_updated_run_id: str = Field(description="Run ID of the last update")
    config_hash: str = Field(description="SHA-256 hash of the entity_aliases config section")
    prior_config_snapshot: EntityCacheConfigSnapshot = Field(
        default_factory=EntityCacheConfigSnapshot, description="Config snapshot for invalidation diffing"
    )
    entries: dict[str, EntityCacheEntry] = Field(
        default_factory=dict, description="Resolved entities keyed by variant name"
    )
    unmatched: list[UnmatchedCacheEntry] = Field(default_factory=list, description="Entities that remain unmatched")
