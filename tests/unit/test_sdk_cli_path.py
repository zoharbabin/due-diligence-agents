"""Tests for :func:`dd_agents.utils.resolve_sdk_cli_path`."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.utils import resolve_sdk_cli_path


class TestResolveSdkCliPath:
    """Unit tests for CLI path resolution."""

    def test_env_override_existing_file(self, tmp_path: Path) -> None:
        """DD_AGENTS_CLI_PATH pointing to an existing file wins."""
        fake_cli = tmp_path / "my-claude"
        fake_cli.write_text("#!/bin/sh\n")

        with patch.dict("os.environ", {"DD_AGENTS_CLI_PATH": str(fake_cli)}):
            assert resolve_sdk_cli_path() == str(fake_cli)

    def test_env_override_missing_file_falls_through(self, tmp_path: Path) -> None:
        """DD_AGENTS_CLI_PATH pointing to a missing file is ignored."""
        missing = str(tmp_path / "does-not-exist")

        with (
            patch.dict("os.environ", {"DD_AGENTS_CLI_PATH": missing}),
            patch("shutil.which", return_value=None),
        ):
            assert resolve_sdk_cli_path() is None

    def test_system_cli_used_when_no_env_var(self) -> None:
        """Falls back to system 'claude' binary on PATH."""
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("dd_agents.utils.os.environ", {"HOME": "/tmp"}),
            patch("dd_agents.utils.shutil.which", return_value="/usr/local/bin/claude"),
        ):
            assert resolve_sdk_cli_path() == "/usr/local/bin/claude"

    def test_returns_none_when_nothing_found(self) -> None:
        """Returns None when no env var and no system CLI."""
        with (
            patch.dict("os.environ", {}, clear=False),
            patch("dd_agents.utils.os.environ", {}),
            patch("dd_agents.utils.shutil.which", return_value=None),
        ):
            assert resolve_sdk_cli_path() is None

    def test_env_var_takes_priority_over_system_cli(self, tmp_path: Path) -> None:
        """Explicit env var beats system CLI discovery."""
        fake_cli = tmp_path / "custom-claude"
        fake_cli.write_text("#!/bin/sh\n")

        with (
            patch.dict("os.environ", {"DD_AGENTS_CLI_PATH": str(fake_cli)}),
            patch("dd_agents.utils.shutil.which", return_value="/usr/local/bin/claude"),
        ):
            result = resolve_sdk_cli_path()
            assert result == str(fake_cli)
