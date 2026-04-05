"""Tests for dd_agents.config -- DealConfig loader and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from dd_agents.config import (
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    load_deal_config,
    validate_deal_config,
)
from dd_agents.models.config import DealConfig

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestLoadValidConfig:
    """Loading a fully-populated valid config file."""

    def test_returns_deal_config(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert isinstance(config, DealConfig)

    def test_buyer_name(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.buyer.name == "Meridian Capital Partners"

    def test_target_name(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.target.name == "NovaBridge Software"

    def test_deal_type(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.deal.type == "acquisition"

    def test_focus_areas_populated(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert len(config.deal.focus_areas) >= 1

    def test_config_version(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.config_version == "1.0.0"

    def test_entity_aliases_present(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert len(config.entity_aliases.canonical_to_variants) > 0

    def test_key_executives(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert len(config.key_executives) >= 1
        assert config.key_executives[0].name == "Executive A"

    def test_judge_config_defaults(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.judge.enabled is True
        assert config.judge.max_iteration_rounds == 2
        assert config.judge.score_threshold == 70

    def test_execution_mode(self) -> None:
        path = FIXTURES_DIR / "deal_config_valid.json"
        config = load_deal_config(path)
        assert config.execution.execution_mode == "full"


class TestLoadMinimalConfig:
    """Loading a minimal config with only required fields."""

    def test_returns_deal_config(self) -> None:
        path = FIXTURES_DIR / "deal_config_minimal.json"
        config = load_deal_config(path)
        assert isinstance(config, DealConfig)

    def test_buyer_name(self) -> None:
        path = FIXTURES_DIR / "deal_config_minimal.json"
        config = load_deal_config(path)
        assert config.buyer.name == "Apex Holdings"

    def test_target_name(self) -> None:
        path = FIXTURES_DIR / "deal_config_minimal.json"
        config = load_deal_config(path)
        assert config.target.name == "Streamline Technologies"

    def test_defaults_applied(self) -> None:
        """Optional sections should receive their default values."""
        path = FIXTURES_DIR / "deal_config_minimal.json"
        config = load_deal_config(path)
        # Defaults from DealConfig model
        assert config.judge.enabled is True
        assert config.execution.execution_mode == "full"
        assert config.reporting.include_diff_sheet is True
        assert config.entity_aliases.canonical_to_variants == {}
        assert config.key_executives == []
        assert config.target.subsidiaries == []


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


class TestInvalidConfig:
    """Loading a config that has intentional validation violations."""

    def test_raises_config_validation_error(self) -> None:
        path = FIXTURES_DIR / "deal_config_invalid.json"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_deal_config(path)
        assert exc_info.value.validation_error is not None

    def test_error_has_multiple_issues(self) -> None:
        path = FIXTURES_DIR / "deal_config_invalid.json"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_deal_config(path)
        errors = exc_info.value.validation_error.errors()
        assert len(errors) > 1, "Expected multiple validation errors"

    def test_error_message_contains_details(self) -> None:
        path = FIXTURES_DIR / "deal_config_invalid.json"
        with pytest.raises(ConfigValidationError, match="validation failed"):
            load_deal_config(path)


class TestFileNotFound:
    """Config path that does not exist."""

    def test_raises_config_file_not_found(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist.json"
        with pytest.raises(ConfigFileNotFoundError, match="not found"):
            load_deal_config(nonexistent)

    def test_error_includes_path(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "missing_config.json"
        with pytest.raises(ConfigFileNotFoundError) as exc_info:
            load_deal_config(nonexistent)
        assert "missing_config.json" in str(exc_info.value)


class TestInvalidJSON:
    """Config file exists but contains broken JSON."""

    def test_raises_config_parse_error(self, tmp_path: Path) -> None:
        bad_json = tmp_path / "broken.json"
        bad_json.write_text("{bad json: true,}", encoding="utf-8")
        with pytest.raises(ConfigParseError, match="Invalid JSON"):
            load_deal_config(bad_json)

    def test_non_object_json(self, tmp_path: Path) -> None:
        """A valid JSON array should be rejected (must be an object)."""
        array_json = tmp_path / "array.json"
        array_json.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ConfigParseError, match="JSON object"):
            load_deal_config(array_json)

    def test_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ConfigParseError):
            load_deal_config(empty)


class TestUTF8BOM:
    """UTF-8 with BOM encoding support."""

    def test_loads_utf8_bom_file(self, tmp_path: Path, valid_config_dict: dict[str, Any]) -> None:
        """A JSON file written with UTF-8 BOM should load correctly."""
        bom_file = tmp_path / "bom_config.json"
        content = json.dumps(valid_config_dict, ensure_ascii=False)
        bom_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        config = load_deal_config(bom_file)
        assert isinstance(config, DealConfig)
        assert config.buyer.name == valid_config_dict["buyer"]["name"]

    def test_bom_does_not_corrupt_data(self, tmp_path: Path, minimal_config_dict: dict[str, Any]) -> None:
        """All fields should survive BOM stripping unchanged."""
        bom_file = tmp_path / "bom_minimal.json"
        content = json.dumps(minimal_config_dict, ensure_ascii=False)
        bom_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        config = load_deal_config(bom_file)
        assert config.target.name == minimal_config_dict["target"]["name"]


# ---------------------------------------------------------------------------
# validate_deal_config (dict input)
# ---------------------------------------------------------------------------


class TestValidateDealConfig:
    """The validate_deal_config function works directly on dicts."""

    def test_valid_dict(self, valid_config_dict: dict[str, Any]) -> None:
        config = validate_deal_config(valid_config_dict)
        assert isinstance(config, DealConfig)

    def test_minimal_dict(self, minimal_config_dict: dict[str, Any]) -> None:
        config = validate_deal_config(minimal_config_dict)
        assert config.buyer.name == "Apex Holdings"

    def test_invalid_dict(self, invalid_config_dict: dict[str, Any]) -> None:
        with pytest.raises(ConfigValidationError):
            validate_deal_config(invalid_config_dict)

    def test_empty_dict(self) -> None:
        with pytest.raises(ConfigValidationError):
            validate_deal_config({})
