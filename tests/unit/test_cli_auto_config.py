"""Unit tests for the dd-agents auto-config command and cli_auto_config module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from dd_agents.cli import main
from dd_agents.cli_auto_config import (
    DataRoomAnalyzer,
    build_reference_file_summary,
    get_tree_output,
    validate_and_fix_config,
)
from dd_agents.cli_init import DEFAULT_FOCUS_AREAS
from dd_agents.config import validate_deal_config

if TYPE_CHECKING:
    from pathlib import Path


# =========================================================================
# Helpers
# =========================================================================


def _create_data_room(tmp_path: Path) -> Path:
    """Create a minimal data room with groups and customers."""
    dr = tmp_path / "data_room"
    dr.mkdir()

    acme = dr / "GroupA" / "Acme_Corp"
    acme.mkdir(parents=True)
    (acme / "contract.pdf").write_text("content")
    (acme / "invoice.xlsx").write_text("content")

    beta = dr / "GroupA" / "Beta_Inc"
    beta.mkdir(parents=True)
    (beta / "agreement.pdf").write_text("content")

    gamma = dr / "GroupB" / "Gamma_LLC"
    gamma.mkdir(parents=True)
    (gamma / "license.docx").write_text("content")

    # Reference file at root
    (dr / "overview.pdf").write_text("reference content")
    (dr / "cap_table.xlsx").write_text("cap table data")

    return dr


def _create_empty_data_room(tmp_path: Path) -> Path:
    """Create an empty data room directory."""
    dr = tmp_path / "empty_room"
    dr.mkdir()
    return dr


def _make_scan_result(
    customer_names: list[str] | None = None,
    groups: list[str] | None = None,
    file_count: int = 5,
) -> dict:
    """Build a minimal scan_result dict for testing."""
    return {
        "groups": groups or ["GroupA", "GroupB"],
        "customers": [],
        "customer_names": customer_names or ["Acme_Corp", "Beta_Inc", "Gamma_LLC"],
        "file_count": file_count,
        "counts": None,
    }


def _make_valid_claude_response(
    buyer: str = "Apex Holdings, Inc.",
    target: str = "WidgetCo Inc.",
) -> dict:
    """Return a valid config dict as Claude would produce."""
    return {
        "config_version": "1.0.0",
        "buyer": {
            "name": buyer,
            "ticker": "APEX",
            "exchange": "NYSE",
            "notes": "Diversified technology holding company",
        },
        "target": {
            "name": target,
            "subsidiaries": ["WidgetCo Holdings LLC", "Sprocket Technologies Inc."],
            "previous_names": [
                {"name": "OldWidget", "period": "2012-2018", "notes": "Original name"},
            ],
            "acquired_entities": [
                {
                    "name": "GearHub",
                    "acquisition_date": "",
                    "deal_type": "acquisition",
                    "notes": "",
                },
            ],
            "entity_name_variants_for_contract_matching": [
                "WidgetCo Inc.",
                "WidgetCo",
                "WidgetCo Holdings LLC",
                "OldWidget",
                "Sprocket Technologies Inc.",
                "GearHub",
            ],
            "notes": "B2B widget intelligence platform",
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": [
                "change_of_control_clauses",
                "ip_ownership",
                "data_privacy_compliance",
                "auto_renewal_terms",
            ],
            "notes": "Data room contains customer contracts organized by group.",
        },
        "entity_aliases": {
            "canonical_to_variants": {
                "WidgetCo": ["WidgetCo Inc.", "WidgetCo Holdings LLC"],
            },
        },
    }


# =========================================================================
# get_tree_output tests
# =========================================================================


class TestGetTreeOutput:
    """Tests for get_tree_output."""

    def test_returns_non_empty_string(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = get_tree_output(dr)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_excludes_dd_directory(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        # Create a _dd directory that should be excluded
        (dr / "_dd").mkdir()
        (dr / "_dd" / "somefile.txt").write_text("hidden")
        result = get_tree_output(dr)
        # The _dd dir and its contents should not appear as tree entries.
        # (The root path itself may contain _dd as a substring, so check lines.)
        tree_lines = result.split("\n")
        # Filter to lines that represent tree entries (exclude the root path line)
        entry_lines = [line for line in tree_lines[1:] if line.strip()]
        for line in entry_lines:
            assert "somefile.txt" not in line, f"_dd contents should be excluded: {line}"

    def test_fallback_when_tree_binary_missing(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        with patch("dd_agents.cli_auto_config._tree_via_binary", return_value=None):
            result = get_tree_output(dr)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain some directory structure indicators
        assert "GroupA" in result

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        # Depth 1 should show top-level only
        result = get_tree_output(dr, max_depth=1)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_truncates_large_output(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        with patch("dd_agents.cli_auto_config._MAX_TREE_CHARS", 10):
            result = get_tree_output(dr)
        assert "truncated" in result


# =========================================================================
# build_reference_file_summary tests
# =========================================================================


class TestBuildReferenceFileSummary:
    """Tests for build_reference_file_summary."""

    def test_identifies_root_files(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        filenames = [r["filename"] for r in result]
        assert "overview.pdf" in filenames
        assert "cap_table.xlsx" in filenames

    def test_excludes_customer_folder_files(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        # Should only have root-level files, not files inside customer folders
        filenames = [r["filename"] for r in result]
        assert "contract.pdf" not in filenames
        assert "agreement.pdf" not in filenames

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        dr = _create_empty_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        assert result == []

    def test_returns_size_info(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = build_reference_file_summary(dr)
        for item in result:
            assert "filename" in item
            assert "size_kb" in item
            assert isinstance(item["size_kb"], int)
            assert item["size_kb"] >= 1


# =========================================================================
# DataRoomAnalyzer tests
# =========================================================================


class TestDataRoomAnalyzer:
    """Tests for DataRoomAnalyzer (mocked Claude calls)."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        mock_response = _make_valid_claude_response()

        mock_call = AsyncMock(return_value=json.dumps(mock_response))
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer.analyze(
                tree_output="fake tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
            )

        assert result["buyer"]["name"] == "Apex Holdings, Inc."
        assert result["target"]["name"] == "WidgetCo Inc."
        assert mock_call.call_count == 1

    @pytest.mark.asyncio
    async def test_system_prompt_mentions_buyer_and_target(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)

        prompt = analyzer._build_system_prompt("AcquireCo", "TargetCo")
        assert "AcquireCo" in prompt
        assert "TargetCo" in prompt

    @pytest.mark.asyncio
    async def test_user_prompt_includes_tree_and_refs(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        refs = [{"filename": "overview.pdf", "size_kb": 42}]

        prompt = analyzer._build_user_prompt(
            tree_output="my-tree-output",
            scan_result=scan_result,
            reference_files=refs,
            buyer="BuyerCo",
            target="TargetCo",
        )
        assert "my-tree-output" in prompt
        assert "overview.pdf" in prompt
        assert "BuyerCo" in prompt
        assert "TargetCo" in prompt
        assert "Acme_Corp" in prompt  # customer names

    @pytest.mark.asyncio
    async def test_user_prompt_includes_deal_type_hint(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        prompt = analyzer._build_user_prompt(
            tree_output="tree",
            scan_result=scan_result,
            reference_files=[],
            buyer="Buyer",
            target="Target",
            deal_type_hint="merger",
        )
        assert "merger" in prompt

    @pytest.mark.asyncio
    async def test_claude_error_propagates(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(side_effect=RuntimeError("Claude API error"))
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(RuntimeError, match="Claude API error"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(return_value="")
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(ValueError, match="empty response"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()

        mock_call = AsyncMock(return_value="not valid json {{{")
        with patch.object(analyzer, "_call_claude", mock_call), pytest.raises(ValueError, match="Failed to parse"):
            await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Buyer",
                target="Target",
            )

    @pytest.mark.asyncio
    async def test_markdown_fences_stripped(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        analyzer = DataRoomAnalyzer(data_room_path=dr)
        scan_result = _make_scan_result()
        mock_response = _make_valid_claude_response()

        fenced = f"```json\n{json.dumps(mock_response)}\n```"
        mock_call = AsyncMock(return_value=fenced)
        with patch.object(analyzer, "_call_claude", mock_call):
            result = await analyzer.analyze(
                tree_output="tree",
                scan_result=scan_result,
                reference_files=[],
                buyer="Apex Holdings",
                target="WidgetCo",
            )

        assert result["buyer"]["name"] == "Apex Holdings, Inc."


# =========================================================================
# validate_and_fix_config tests
# =========================================================================


class TestValidateAndFixConfig:
    """Tests for validate_and_fix_config."""

    def test_valid_config_passes_through(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["config_version"] == "1.0.0"
        assert result["buyer"]["name"] == "Apex Holdings, Inc."

    def test_missing_config_version_fixed(self) -> None:
        config = _make_valid_claude_response()
        del config["config_version"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["config_version"] == "1.0.0"

    def test_missing_focus_areas_fixed(self) -> None:
        config = _make_valid_claude_response()
        del config["deal"]["focus_areas"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["deal"]["focus_areas"] == list(DEFAULT_FOCUS_AREAS[:4])

    def test_invalid_deal_type_fixed(self) -> None:
        config = _make_valid_claude_response()
        config["deal"]["type"] = "hostile_takeover"
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        assert result["deal"]["type"] == "acquisition"

    def test_empty_buyer_raises(self) -> None:
        config = _make_valid_claude_response()
        config["buyer"]["name"] = ""
        scan_result = _make_scan_result()
        with pytest.raises(ValueError, match="buyer.name is empty"):
            validate_and_fix_config(config, scan_result)

    def test_empty_target_raises(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["name"] = ""
        scan_result = _make_scan_result()
        with pytest.raises(ValueError, match="target.name is empty"):
            validate_and_fix_config(config, scan_result)

    def test_customer_names_merged_into_entity_aliases(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result(customer_names=["Acme_Corp", "Beta_Inc"])
        result = validate_and_fix_config(config, scan_result)
        c2v = result["entity_aliases"]["canonical_to_variants"]
        assert "Acme Corp" in c2v
        assert "Acme_Corp" in c2v["Acme Corp"]

    def test_target_name_added_to_entity_variants(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["entity_name_variants_for_contract_matching"] = []
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        variants = result["target"]["entity_name_variants_for_contract_matching"]
        assert config["target"]["name"] in variants

    def test_target_name_inserted_if_missing_from_variants(self) -> None:
        config = _make_valid_claude_response()
        config["target"]["entity_name_variants_for_contract_matching"] = ["SomeOther"]
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        variants = result["target"]["entity_name_variants_for_contract_matching"]
        assert variants[0] == config["target"]["name"]

    def test_result_passes_pydantic_validation(self) -> None:
        config = _make_valid_claude_response()
        scan_result = _make_scan_result()
        result = validate_and_fix_config(config, scan_result)
        validated = validate_deal_config(result)
        assert validated.buyer.name == "Apex Holdings, Inc."
        assert validated.target.name == "WidgetCo Inc."


# =========================================================================
# CLI integration tests
# =========================================================================


class TestCliAutoConfig:
    """Tests for dd-agents auto-config CLI command."""

    def test_generates_valid_config_file(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        assert output.exists()
        config = json.loads(output.read_text())
        validated = validate_deal_config(config)
        assert validated.buyer.name == "Apex Holdings, Inc."

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert not output.exists()
        # Should print the JSON to stdout
        assert "config_version" in result.output

    def test_output_path_respected(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        custom_output = tmp_path / "subdir" / "custom.json"
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(custom_output),
                ],
            )

        assert result.exit_code == 0, result.output
        assert custom_output.exists()

    def test_force_overwrites(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        output.write_text("{}")
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--output",
                    str(output),
                    "--force",
                ],
            )

        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["buyer"]["name"] == "Apex Holdings, Inc."

    def test_buyer_and_target_appear_in_output(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        mock_response = _make_valid_claude_response()

        runner = CliRunner()
        with patch(
            "dd_agents.cli_auto_config.DataRoomAnalyzer._call_claude",
            new_callable=AsyncMock,
            return_value=json.dumps(mock_response),
        ):
            result = runner.invoke(
                main,
                [
                    "auto-config",
                    "Apex Holdings",
                    "WidgetCo",
                    "--data-room",
                    str(dr),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Apex Holdings" in result.output
        assert "WidgetCo" in result.output

    def test_nonexistent_data_room_fails(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "auto-config",
                "Buyer",
                "Target",
                "--data-room",
                str(tmp_path / "nonexistent"),
            ],
        )
        assert result.exit_code != 0

    def test_help_shows_buyer_and_target(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["auto-config", "--help"])
        assert result.exit_code == 0
        assert "BUYER" in result.output
        assert "TARGET" in result.output
        assert "acquiring company" in result.output
