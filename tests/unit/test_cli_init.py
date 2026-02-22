"""Tests for the dd-agents init command and cli_init module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main
from dd_agents.cli_init import (
    DEFAULT_FOCUS_AREAS,
    build_config_dict,
    prompt_deal_type,
    scan_data_room,
)
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
    (dr / "overview.pdf").write_text("content")

    return dr


def _create_empty_data_room(tmp_path: Path) -> Path:
    """Create an empty data room directory."""
    dr = tmp_path / "empty_room"
    dr.mkdir()
    return dr


# =========================================================================
# scan_data_room tests
# =========================================================================


class TestScanDataRoom:
    """Tests for scan_data_room."""

    def test_populated_room(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = scan_data_room(dr)

        assert len(result["groups"]) == 2
        assert "GroupA" in result["groups"]
        assert "GroupB" in result["groups"]
        assert len(result["customer_names"]) == 3
        assert result["file_count"] == 5

    def test_empty_room(self, tmp_path: Path) -> None:
        dr = _create_empty_data_room(tmp_path)
        result = scan_data_room(dr)

        assert result["groups"] == []
        assert result["customer_names"] == []
        assert result["file_count"] == 0

    def test_group_detection(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = scan_data_room(dr)

        groups = result["groups"]
        assert groups == ["GroupA", "GroupB"]

    def test_customer_detection(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        result = scan_data_room(dr)

        names = result["customer_names"]
        assert "Acme_Corp" in names
        assert "Beta_Inc" in names
        assert "Gamma_LLC" in names


# =========================================================================
# build_config_dict tests
# =========================================================================


class TestBuildConfigDict:
    """Tests for build_config_dict."""

    def test_minimal(self) -> None:
        config = build_config_dict(
            buyer="TestBuyer",
            target="TestTarget",
            deal_type="acquisition",
            focus_areas=["ip_ownership"],
        )
        assert config["buyer"]["name"] == "TestBuyer"
        assert config["target"]["name"] == "TestTarget"
        assert config["deal"]["type"] == "acquisition"
        assert config["deal"]["focus_areas"] == ["ip_ownership"]
        assert config["config_version"] == "1.0.0"

    def test_with_variants(self) -> None:
        config = build_config_dict(
            buyer="Buyer",
            target="Target",
            deal_type="merger",
            focus_areas=["ip_ownership"],
            name_variants=["Target Inc.", "Target Ltd."],
        )
        variants = config["target"]["entity_name_variants_for_contract_matching"]
        assert "Target Inc." in variants
        assert "Target Ltd." in variants

    def test_with_customers(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        scan_result = scan_data_room(dr)

        config = build_config_dict(
            buyer="Buyer",
            target="Target",
            deal_type="acquisition",
            focus_areas=["ip_ownership"],
            scan_result=scan_result,
        )
        # Customers with underscores get clean name variants
        aliases = config.get("entity_aliases", {}).get("canonical_to_variants", {})
        assert "Acme Corp" in aliases
        assert "Acme_Corp" in aliases["Acme Corp"]

    def test_with_data_room_path(self) -> None:
        config = build_config_dict(
            buyer="Buyer",
            target="Target",
            deal_type="acquisition",
            focus_areas=["ip_ownership"],
            data_room_path="/tmp/my_room",
        )
        assert config["data_room"]["path"] == "/tmp/my_room"

    def test_all_deal_types_validate(self) -> None:
        deal_types = [
            "acquisition",
            "merger",
            "divestiture",
            "investment",
            "joint_venture",
            "other",
        ]
        for dt in deal_types:
            config = build_config_dict(
                buyer="Buyer",
                target="Target",
                deal_type=dt,
                focus_areas=["ip_ownership"],
            )
            result = validate_deal_config(config)
            assert result.deal.type.value == dt


# =========================================================================
# CLI non-interactive tests
# =========================================================================


class TestCliNonInteractive:
    """Tests for dd-agents init --non-interactive."""

    def test_generates_valid_config(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "TestBuyer",
                "--target",
                "TestTarget",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert output.exists()

        config = json.loads(output.read_text())
        validated = validate_deal_config(config)
        assert validated.buyer.name == "TestBuyer"
        assert validated.target.name == "TestTarget"

    def test_missing_buyer_fails(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--target",
                "TestTarget",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code != 0

    def test_missing_data_room_fails(self, tmp_path: Path) -> None:
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--buyer",
                "TestBuyer",
                "--target",
                "TestTarget",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code != 0

    def test_nonexistent_room_fails(self, tmp_path: Path) -> None:
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(tmp_path / "nope"),
                "--buyer",
                "TestBuyer",
                "--target",
                "TestTarget",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code != 0

    def test_default_focus_areas(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["deal"]["focus_areas"] == DEFAULT_FOCUS_AREAS[:4]

    def test_custom_focus_areas(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--focus-areas",
                "ip_ownership,liability_caps",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["deal"]["focus_areas"] == ["ip_ownership", "liability_caps"]

    def test_force_overwrites(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        output.write_text("{}")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--force",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["buyer"]["name"] == "Buyer"

    def test_name_variants_included(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--name-variants",
                "Target Inc.,Target Ltd.",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        variants = config["target"]["entity_name_variants_for_contract_matching"]
        assert "Target Inc." in variants
        assert "Target Ltd." in variants

    def test_empty_room_works(self, tmp_path: Path) -> None:
        dr = _create_empty_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["buyer"]["name"] == "Buyer"

    def test_generated_config_passes_validation(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Acme Holdings",
                "--target",
                "NovaBridge Solutions",
                "--deal-type",
                "merger",
                "--focus-areas",
                "change_of_control_clauses,ip_ownership,revenue_recognition",
                "--name-variants",
                "NovaBridge,NovaBridge Inc.",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output

        config = json.loads(output.read_text())
        validated = validate_deal_config(config)
        assert validated.buyer.name == "Acme Holdings"
        assert validated.target.name == "NovaBridge Solutions"
        assert validated.deal.type.value == "merger"

    def test_output_includes_next_steps(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Next steps" in result.output
        assert "dd-agents validate" in result.output
        assert "dd-agents run" in result.output

    def test_scan_summary_in_output(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Data Room Scan" in result.output

    def test_deal_type_choices(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--deal-type",
                "divestiture",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["deal"]["type"] == "divestiture"

    def test_non_interactive_no_force_existing_file_fails(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"
        output.write_text("{}")

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code != 0
        # Original content should be unchanged
        assert output.read_text() == "{}"

    def test_missing_target_fails(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "TestBuyer",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code != 0


# =========================================================================
# CLI interactive tests
# =========================================================================


class TestCliInteractive:
    """Tests for dd-agents init in interactive mode."""

    def test_interactive_produces_valid_config(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        # Simulate interactive input:
        # 1. data room path
        # 2. buyer name
        # 3. target name
        # 4. deal type (press enter for default)
        # 5. focus areas (press enter for default)
        # 6. name variants (press enter to skip)
        user_input = f"{dr}\nMyBuyer\nMyTarget\n\n\n\n"

        result = runner.invoke(
            main,
            ["init", "--output", str(output), "--force"],
            input=user_input,
        )
        assert result.exit_code == 0, result.output
        assert output.exists()

        config = json.loads(output.read_text())
        validated = validate_deal_config(config)
        assert validated.buyer.name == "MyBuyer"
        assert validated.target.name == "MyTarget"

    def test_interactive_invalid_deal_type_reprompts(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        # "buyout" is invalid, then "merger" is valid
        user_input = f"{dr}\nBuyer\nTarget\nbuyout\nmerger\n\n\n"

        result = runner.invoke(
            main,
            ["init", "--output", str(output), "--force"],
            input=user_input,
        )
        assert result.exit_code == 0, result.output
        config = json.loads(output.read_text())
        assert config["deal"]["type"] == "merger"

    def test_interactive_name_variants_explanation_shown(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        user_input = f"{dr}\nBuyer\nAcme Co\n\n\n\n"

        result = runner.invoke(
            main,
            ["init", "--output", str(output), "--force"],
            input=user_input,
        )
        assert result.exit_code == 0, result.output
        assert "different names in contracts" in result.output


# =========================================================================
# UX / display tests
# =========================================================================


class TestUXDisplay:
    """Tests for user-facing display improvements."""

    def test_empty_room_shows_folder_structure_hint(self, tmp_path: Path) -> None:
        dr = _create_empty_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "data_room/GroupName/CustomerName" in result.output

    def test_populated_room_no_folder_hint(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "init",
                "--non-interactive",
                "--data-room",
                str(dr),
                "--buyer",
                "Buyer",
                "--target",
                "Target",
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "GroupName/CustomerName" not in result.output

    def test_focus_areas_show_readable_labels(self, tmp_path: Path) -> None:
        dr = _create_data_room(tmp_path)
        output = tmp_path / "out.json"

        runner = CliRunner()
        user_input = f"{dr}\nBuyer\nTarget\n\n\n\n"

        result = runner.invoke(
            main,
            ["init", "--output", str(output), "--force"],
            input=user_input,
        )
        assert result.exit_code == 0, result.output
        # Human-readable labels should appear instead of raw identifiers
        assert "Change of control clauses" in result.output

    def test_prompt_deal_type_default(self, monkeypatch: object) -> None:
        from io import StringIO

        from rich.console import Console

        monkeypatch.setattr("builtins.input", lambda _prompt: "")  # type: ignore[arg-type]
        result = prompt_deal_type(Console(file=StringIO()))
        assert result == "acquisition"

    def test_prompt_deal_type_valid(self, monkeypatch: object) -> None:
        from io import StringIO

        from rich.console import Console

        monkeypatch.setattr("builtins.input", lambda _prompt: "merger")  # type: ignore[arg-type]
        result = prompt_deal_type(Console(file=StringIO()))
        assert result == "merger"

    def test_prompt_deal_type_invalid_then_valid(self, monkeypatch: object) -> None:
        from io import StringIO

        from rich.console import Console

        responses = iter(["buyout", "divestiture"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))  # type: ignore[arg-type]
        result = prompt_deal_type(Console(file=StringIO()))
        assert result == "divestiture"
