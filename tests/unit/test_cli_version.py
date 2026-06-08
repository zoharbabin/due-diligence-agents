"""Tests for the dd-agents version command (#211 --json flag)."""

from __future__ import annotations

import json

from click.testing import CliRunner

import dd_agents
from dd_agents.cli import main


class TestVersionCommand:
    def test_human_default(self) -> None:
        result = CliRunner().invoke(main, ["version"])
        assert result.exit_code == 0
        assert f"dd-agents {dd_agents.__version__}" in result.output

    def test_json_flag(self) -> None:
        result = CliRunner().invoke(main, ["version", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == {"version": dd_agents.__version__}

    def test_json_output_is_pure_json(self) -> None:
        result = CliRunner().invoke(main, ["version", "--json"])
        assert result.exit_code == 0
        assert result.output.strip().startswith("{")
        assert "dd-agents " not in result.output
