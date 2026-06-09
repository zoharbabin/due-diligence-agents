"""Tests for `dd-agents run` option validation (no live pipeline)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def _minimal_config(tmp_path: Path) -> Path:
    """Write a minimal valid deal-config pointing at an empty data room."""
    dr = tmp_path / "data_room"
    dr.mkdir()
    cfg = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer Co"},
        "target": {"name": "Target Co"},
        "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
        "data_room": {"path": str(dr)},
    }
    path = tmp_path / "deal-config.json"
    path.write_text(json.dumps(cfg))
    return path


class TestResumeFromBound:
    """--resume-from must accept the full 0-38 step range (38 = SHUTDOWN)."""

    def test_rejects_above_38(self, tmp_path: Path) -> None:
        cfg = _minimal_config(tmp_path)
        result = CliRunner().invoke(main, ["run", str(cfg), "--resume-from", "39"])
        assert result.exit_code == 1
        assert "must be 0-38" in result.output

    def test_rejects_negative(self, tmp_path: Path) -> None:
        cfg = _minimal_config(tmp_path)
        result = CliRunner().invoke(main, ["run", str(cfg), "--resume-from", "-1"])
        assert result.exit_code == 1
        assert "must be 0-38" in result.output

    def test_accepts_38_in_dry_run(self, tmp_path: Path) -> None:
        """Step 38 (the final step) is a valid resume target — no range error."""
        cfg = _minimal_config(tmp_path)
        result = CliRunner().invoke(main, ["run", str(cfg), "--resume-from", "38", "--dry-run"])
        assert "must be 0-38" not in result.output
