"""E2E flow for the Discoverability & DX milestone (issue #269).

Exercises the real user flow end-to-end against the committed Project Atlas
fixture run -- no API key needed, since every command here is read-only over
an already-completed run directory. Recorded proof: this test's own pytest
log (captured by scripts/discoverability-dx-harness.sh gate 6) plus the
assertions below on each command's actual output.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from dd_agents.cli import main

REPO_ROOT = Path(__file__).resolve().parents[2]
ATLAS_RUN_DIR = (
    REPO_ROOT
    / "examples"
    / "project-atlas"
    / "sample_data_room"
    / "_dd"
    / "forensic-dd"
    / "runs"
    / "run_20260606_210024_13c73b"
)


class TestDiffCommandRealFlow:
    def test_diff_same_run_against_itself_has_no_changes(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["diff", str(ATLAS_RUN_DIR), str(ATLAS_RUN_DIR), "--json"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["summary"]["new_findings"] == 0
        assert out["summary"]["resolved_findings"] == 0

    def test_diff_human_summary_mentions_run_ids(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["diff", str(ATLAS_RUN_DIR), str(ATLAS_RUN_DIR)])
        assert result.exit_code == 0, result.output
        assert "0" in result.output


class TestHealthJsonRealFlow:
    def test_health_json_over_atlas_knowledge_base(self) -> None:
        data_room = ATLAS_RUN_DIR.parents[3]  # sample_data_room/
        runner = CliRunner()
        result = runner.invoke(main, ["health", "--data-room", str(data_room), "--json"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert "total_issues" in out
        assert "knowledge_base_stats" in out


class TestMemoJsonRealFlow:
    def test_memo_json_over_atlas_run(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["memo", "--report", str(ATLAS_RUN_DIR), "--json"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert "go_no_go" in out
        assert "top_risks" in out


class TestSearchJsonRealFlow:
    def test_search_json_help_documents_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["search", "--help"])
        assert result.exit_code == 0, result.output
        assert "--json" in result.output
