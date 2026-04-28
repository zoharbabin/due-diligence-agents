"""Tests for constants module."""

from __future__ import annotations

from dd_agents.utils.constants import (
    ALL_SPECIALIST_AGENTS,
    BATCH_START_INDEX,
    DD_DIR,
    EXCLUDE_PATTERNS,
    FUZZY_THRESHOLD_LONG,
    FUZZY_THRESHOLD_MEDIUM,
    SEVERITY_ORDER,
    SHORT_NAME_MAX_LEN,
    SKILL_DIR,
    SKILL_NAME,
    SUPPORTED_EXTENSIONS,
    TFIDF_THRESHOLD,
    TIER_FRESH,
    TIER_PERMANENT,
    TIER_VERSIONED,
)


class TestConstants:
    def test_tier_names_exist(self) -> None:
        assert TIER_PERMANENT == "PERMANENT"
        assert TIER_VERSIONED == "VERSIONED"
        assert TIER_FRESH == "FRESH"

    def test_skill_dir_contains_dd_dir(self) -> None:
        assert SKILL_DIR.startswith(DD_DIR)
        assert SKILL_NAME in SKILL_DIR

    def test_five_specialist_agents(self) -> None:
        assert len(ALL_SPECIALIST_AGENTS) == 5
        assert "legal" in ALL_SPECIALIST_AGENTS
        assert "finance" in ALL_SPECIALIST_AGENTS
        assert "commercial" in ALL_SPECIALIST_AGENTS
        assert "producttech" in ALL_SPECIALIST_AGENTS
        assert "cybersecurity" in ALL_SPECIALIST_AGENTS

    def test_severity_order(self) -> None:
        assert SEVERITY_ORDER["P0"] < SEVERITY_ORDER["P1"]
        assert SEVERITY_ORDER["P1"] < SEVERITY_ORDER["P2"]
        assert SEVERITY_ORDER["P2"] < SEVERITY_ORDER["P3"]

    def test_batch_start_index_is_one(self) -> None:
        assert BATCH_START_INDEX == 1

    def test_exclude_patterns_not_empty(self) -> None:
        assert len(EXCLUDE_PATTERNS) > 0
        assert ".DS_Store" in EXCLUDE_PATTERNS

    def test_supported_extensions_include_common(self) -> None:
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".xlsx" in SUPPORTED_EXTENSIONS

    def test_fuzzy_thresholds(self) -> None:
        assert FUZZY_THRESHOLD_LONG < FUZZY_THRESHOLD_MEDIUM
        assert SHORT_NAME_MAX_LEN == 5
        assert 0.0 < TFIDF_THRESHOLD < 1.0
