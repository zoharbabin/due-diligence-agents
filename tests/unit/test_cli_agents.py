"""CLI tests for the `dd-agents agents` group (§6.1/§6.4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path

_MINIMAL_CONFIG = {
    "config_version": "1.0.0",
    "buyer": {"name": "B"},
    "target": {"name": "T"},
    "deal": {"type": "acquisition", "focus_areas": ["legal"]},
}


def _write_config(path: Path) -> Path:
    path.write_text(json.dumps(_MINIMAL_CONFIG), encoding="utf-8")
    return path


def test_agents_list_exit_zero() -> None:
    result = CliRunner().invoke(main, ["agents", "list"])
    assert result.exit_code == 0
    assert "legal" in result.output


def test_agents_describe_exit_zero() -> None:
    result = CliRunner().invoke(main, ["agents", "describe", "--agent", "legal"])
    assert result.exit_code == 0
    assert "MANDATORY Citation Requirements" in result.output


def test_agents_describe_unknown_exit_nonzero() -> None:
    result = CliRunner().invoke(main, ["agents", "describe", "--agent", "nope"])
    assert result.exit_code != 0


def test_agents_describe_text_default_exit_zero() -> None:
    result = CliRunner().invoke(main, ["agents", "describe", "--agent", "legal"])
    assert result.exit_code == 0


def test_agents_describe_md_keeps_raw_markdown() -> None:
    result = CliRunner().invoke(main, ["agents", "describe", "--agent", "legal", "--format", "md"])
    assert result.exit_code == 0
    assert "MANDATORY Citation Requirements" in result.output


def test_agents_validate_clean_exit_zero(tmp_path: Path) -> None:
    (tmp_path / "dd-config" / "agents").mkdir(parents=True)
    (tmp_path / "dd-config" / "agents" / "legal.md").write_text(
        "---\nagent: legal\n---\n\n## Additional Focus Areas\n\n- assignment clauses\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["agents", "validate", str(tmp_path)])
    assert result.exit_code == 0


def test_agents_validate_bad_exit_one(tmp_path: Path) -> None:
    (tmp_path / "dd-config" / "agents").mkdir(parents=True)
    (tmp_path / "dd-config" / "agents" / "legal.md").write_text(
        "---\nagent: legal\n---\n\n## Severity Overrides\n\n- change_of_control: P9\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["agents", "validate", str(tmp_path)])
    assert result.exit_code == 1


def test_agents_preview_exit_zero(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "deal-config.json")
    result = CliRunner().invoke(main, ["agents", "preview", "--agent", "legal", "--config", str(config)])
    assert result.exit_code == 0
    assert "MANDATORY Citation Requirements" in result.output


def test_agents_preview_output_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "p.txt"
    result = CliRunner().invoke(main, ["agents", "preview", "--agent", "legal", "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    written = out.read_text(encoding="utf-8")
    assert "LEGAL SPECIALIST AGENT" in written
    assert "MANDATORY Citation Requirements" in written


def test_agents_preview_unknown_agent_exits_nonzero() -> None:
    """CLI: previewing an unknown agent surfaces an error and exits non-zero."""
    from click.testing import CliRunner

    from dd_agents.cli import main

    result = CliRunner().invoke(main, ["agents", "preview", "--agent", "nope"])
    assert result.exit_code != 0
