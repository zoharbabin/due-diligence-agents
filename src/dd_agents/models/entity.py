"""Pydantic models for entity resolution: matches, cache entries, and match logs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EntityMatch(BaseModel):
    """
    A confirmed entity match. From entity-resolution-protocol.md section 5.
    """

    source_name: str  # Name as found in source
    source: str  # "database", "directory", "reference_file"
    matched_name: str  # Name as found in target
    target: str  # "directory", "database", "reference_file"
    match_pass: int  # 1-6 (which pass matched)
    match_method: str  # "preprocessing", "exact", "alias_lookup",
    # "fuzzy", "tfidf", "parent_child"
    confidence: float = Field(ge=0.0, le=1.0)
    canonical_name: str  # Resolved canonical name


class MatchAttempt(BaseModel):
    """Record of a single match pass attempt for an unmatched entity."""

    model_config = ConfigDict(populate_by_name=True)

    pass_num: int = Field(alias="pass")  # "pass" alias is safe; see AgentScore note
    method: str
    result: str  # "no_match", "below_threshold"
    best_candidate: str | None = None
    score: float | None = None


class UnmatchedEntity(BaseModel):
    """An entity that could not be matched after all 6 passes."""

    source_name: str
    source: str
    match_attempts: list[MatchAttempt] = Field(default_factory=list)
    resolution: str = "unmatched_gap_logged"


class RejectedMatch(BaseModel):
    """A match that was rejected (below threshold or on exclusion list)."""

    source_name: str
    source: str
    rejected_match: str
    match_pass: int
    score: float
    reason: str  # "below_threshold", "exclusion_list"


class EntityMatchLog(BaseModel):
    """
    Complete entity match log. Written to entity_matches.json.
    From entity-resolution-protocol.md section 5.
    """

    matches: list[EntityMatch] = Field(default_factory=list)
    unmatched: list[UnmatchedEntity] = Field(default_factory=list)
    rejected: list[RejectedMatch] = Field(default_factory=list)


class EntityCacheEntry(BaseModel):
    """
    Single entry in the PERMANENT entity resolution cache.
    From entity-resolution-protocol.md section 7.
    """

    canonical: str
    match_pass: int
    match_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    entity_type: str = "customer"
    first_seen_run: str
    last_confirmed_run: str
    confirmation_count: int = 1


class UnmatchedCacheEntry(BaseModel):
    """An unmatched entity persisted in the cache."""

    name: str
    context: str = ""
    first_seen_run: str


class EntityCacheConfigSnapshot(BaseModel):
    """Snapshot of entity_aliases config for per-entry invalidation diff."""

    canonical_to_variants: dict[str, list[str]] = Field(default_factory=dict)
    short_name_guard: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    parent_child: dict[str, list[str]] = Field(default_factory=dict)


class EntityCache(BaseModel):
    """
    PERMANENT tier entity resolution cache.
    Written to _dd/entity_resolution_cache.json.
    From entity-resolution-protocol.md section 7.
    """

    version: int = 1
    last_updated: str  # ISO-8601
    last_updated_by: str = "forensic-dd"
    last_updated_run_id: str
    config_hash: str  # SHA-256 of entity_aliases section
    prior_config_snapshot: EntityCacheConfigSnapshot = Field(default_factory=EntityCacheConfigSnapshot)
    entries: dict[str, EntityCacheEntry] = Field(default_factory=dict)
    unmatched: list[UnmatchedCacheEntry] = Field(default_factory=list)
