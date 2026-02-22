"""Unit tests for the search CLI command."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from click.testing import CliRunner

from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def _write_prompts_file(tmp_path: Path) -> Path:
    """Write a valid prompts file and return its path."""
    prompts = {
        "name": "Test",
        "columns": [
            {"name": "Q1", "prompt": "A valid prompt that is long enough to pass model validation."},
        ],
    }
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(prompts))
    return path


class TestSearchCLI:
    """Tests for the 'search' Click command."""

    def test_search_command_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "search" in result.output

    def test_missing_prompts_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        data_room = tmp_path / "dr"
        data_room.mkdir()

        result = runner.invoke(main, ["search", str(tmp_path / "missing.json"), "--data-room", str(data_room)])
        assert result.exit_code != 0

    def test_invalid_concurrency(self, tmp_path: Path) -> None:
        runner = CliRunner()
        prompts_path = _write_prompts_file(tmp_path)
        data_room = tmp_path / "dr"
        data_room.mkdir()

        result = runner.invoke(
            main, ["search", str(prompts_path), "--data-room", str(data_room), "--concurrency", "50"]
        )
        assert result.exit_code != 0

    def test_nonexistent_data_room(self, tmp_path: Path) -> None:
        runner = CliRunner()
        prompts_path = _write_prompts_file(tmp_path)

        result = runner.invoke(main, ["search", str(prompts_path), "--data-room", str(tmp_path / "nope")])
        assert result.exit_code != 0

    def test_valid_invocation_reaches_runner(self, tmp_path: Path) -> None:
        """A valid invocation should reach SearchRunner.run (mocked)."""
        runner = CliRunner()
        prompts_path = _write_prompts_file(tmp_path)
        data_room = tmp_path / "dr"
        data_room.mkdir()

        with patch("dd_agents.search.runner.SearchRunner.run") as mock_run:
            result = runner.invoke(main, ["search", str(prompts_path), "--data-room", str(data_room)])

        # The command should call SearchRunner.run.
        assert mock_run.called
        assert result.exit_code == 0
