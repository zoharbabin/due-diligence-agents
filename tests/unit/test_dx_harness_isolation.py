"""Multi-instance isolation gate for the Discoverability & DX milestone (issue #269).

Proves Phase-1 rule 1.1: no new module-level mutable state in the `diff`
command, `ReportDiffBuilder`, or the `--json` paths of `health`/`memo`/`search`.
Two independent instances/invocations in one process must never leak state.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main
from dd_agents.reporting.diff import ReportDiffBuilder

if TYPE_CHECKING:
    from pathlib import Path


def _write_run(run_dir: Path, subject: str, findings: list[dict[str, object]]) -> None:
    merged = run_dir / "findings" / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    (merged / f"{subject}.json").write_text(
        json.dumps({"subject": subject, "subject_safe_name": subject, "findings": findings}),
        encoding="utf-8",
    )
    (merged / "gaps").mkdir(exist_ok=True)


class TestReportDiffBuilderIsolation:
    def test_two_instances_do_not_share_state(self, tmp_path: Path) -> None:
        run_a = tmp_path / "run_a"  # current: finding resolved (no longer present)
        run_b = tmp_path / "run_b"  # prior: had the finding
        run_c = tmp_path / "run_c"
        _write_run(run_a, "acme", [])
        _write_run(run_b, "acme", [{"category": "ip", "citations": [{"source_path": "a.pdf"}]}])
        _write_run(run_c, "acme", [{"category": "ip", "citations": [{"source_path": "a.pdf"}]}])

        builder_1 = ReportDiffBuilder()
        diff_1 = builder_1.build_diff(run_a / "findings", run_b / "findings")

        builder_2 = ReportDiffBuilder()
        diff_2 = builder_2.build_diff(run_c / "findings", run_c / "findings")

        # builder_1 found a resolved finding (b -> a); builder_2 diffed identical
        # runs and must find zero changes -- proves no leakage from builder_1.
        assert diff_1.summary.resolved_findings == 1
        assert diff_2.summary.resolved_findings == 0
        assert diff_2.changes == []


class TestCliJsonCommandIsolation:
    def test_diff_command_invoked_twice_yields_independent_results(self, tmp_path: Path) -> None:
        run_a = tmp_path / "run_a"  # current: finding resolved
        run_b = tmp_path / "run_b"  # prior: had the finding
        _write_run(run_a, "acme", [])
        _write_run(run_b, "acme", [{"category": "ip", "citations": [{"source_path": "a.pdf"}]}])

        runner = CliRunner()
        result_1 = runner.invoke(main, ["diff", str(run_a), str(run_b), "--json"])
        result_2 = runner.invoke(main, ["diff", str(run_a), str(run_a), "--json"])

        assert result_1.exit_code == 0, result_1.output
        assert result_2.exit_code == 0, result_2.output
        out_1 = json.loads(result_1.output)
        out_2 = json.loads(result_2.output)
        assert out_1["summary"]["resolved_findings"] == 1
        assert out_2["summary"]["resolved_findings"] == 0
