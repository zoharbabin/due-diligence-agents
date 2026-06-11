"""Tests for --json parity (Issue #241) + the cost reader / assess pre-flight (#246)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def _valid_config(tmp_path: Path) -> Path:
    cfg = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer"},
        "target": {"name": "Target"},
        "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
    }
    p = tmp_path / "deal-config.json"
    p.write_text(json.dumps(cfg))
    return p


class TestValidateJson:
    def test_valid_emits_json(self, tmp_path: Path) -> None:
        r = CliRunner().invoke(main, ["validate", str(_valid_config(tmp_path)), "--json"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["valid"] is True
        assert out["target"] == "Target"

    def test_invalid_emits_errors_json_and_exit_1(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"config_version": "1.0.0"}))  # missing buyer/target/deal
        r = CliRunner().invoke(main, ["validate", str(bad), "--json"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["valid"] is False
        assert len(out["errors"]) >= 1
        assert "loc" in out["errors"][0]

    def test_missing_file_emits_json(self, tmp_path: Path) -> None:
        r = CliRunner().invoke(main, ["validate", str(tmp_path / "nope.json"), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["valid"] is False


class TestAssessJson:
    def _data_room(self, tmp_path: Path) -> Path:
        dr = tmp_path / "dr"
        (dr / "Acme").mkdir(parents=True)
        (dr / "Acme" / "msa.pdf").write_text("contract text " * 50)
        (dr / "Acme" / "more.pdf").write_text("more text " * 50)
        (dr / "Acme" / "third.pdf").write_text("third " * 50)
        (dr / "Acme" / "fourth.pdf").write_text("fourth " * 50)
        (dr / "Acme" / "fifth.pdf").write_text("fifth " * 50)
        return dr

    def test_assess_emits_json_report(self, tmp_path: Path) -> None:
        r = CliRunner().invoke(main, ["assess", str(self._data_room(tmp_path)), "--json"])
        assert r.exit_code == 0, r.output
        out = json.loads(r.output)
        assert "overall_score" in out
        assert "vdr_convention" in out

    def test_assess_formula_preflight_flags_bad_model(self, tmp_path: Path) -> None:
        from openpyxl import Workbook

        dr = self._data_room(tmp_path)
        wb = Workbook()
        ws = wb.active
        ws.title = "Model"
        ws["B2"] = "=A2*1.1"
        ws["B3"] = "=A3*1.1"
        ws["B4"] = "=A4*1.1"
        ws["B5"] = "=1234"  # hardcoded override
        wb.save(dr / "Acme" / "model.xlsx")
        wb.close()

        r = CliRunner().invoke(main, ["assess", str(dr), "--json"])
        assert r.exit_code == 0, r.output
        out = json.loads(r.output)
        assert out.get("formula_audit", {}).get("total_issues", 0) >= 1
        # File path is data-room-relative (no local-path leak).
        issues = out["formula_audit"]["issues"]
        assert all(not str(i["file"]).startswith("/") for i in issues)


class TestCostCommand:
    def _run_dir(self, tmp_path: Path, summary: dict) -> Path:  # type: ignore[type-arg]
        rd = tmp_path / "run"
        rd.mkdir()
        (rd / "cost_summary.json").write_text(json.dumps(summary))
        return rd

    _SUMMARY = {
        "total_cost": 1.2345,
        "total_tokens": 50000,
        "budget_limit_usd": None,
        "by_agent": {"legal": 0.5, "finance": 0.7345},
        "by_step": {"16_spawn": 1.2345},
        "by_model": {"claude-sonnet-4-6": {"cost": 1.2345, "estimated": False}},
        "by_provider": {"(run default)": {"cost": 1.2345, "base_url": None}},
    }

    def test_cost_json(self, tmp_path: Path) -> None:
        rd = self._run_dir(tmp_path, self._SUMMARY)
        r = CliRunner().invoke(main, ["cost", str(rd), "--json"])
        assert r.exit_code == 0, r.output
        out = json.loads(r.output)
        assert out["total_cost"] == 1.2345
        assert "by_provider" in out

    def test_cost_rich_output(self, tmp_path: Path) -> None:
        rd = self._run_dir(tmp_path, self._SUMMARY)
        r = CliRunner().invoke(main, ["cost", str(rd)])
        assert r.exit_code == 0, r.output
        assert "By Provider" in r.output
        assert "By Model" in r.output

    def test_cost_missing_summary_exits_1(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        r = CliRunner().invoke(main, ["cost", str(empty), "--json"])
        assert r.exit_code == 1
        assert "error" in json.loads(r.output)

    def test_cost_parent_dir_picks_newest_run(self, tmp_path: Path) -> None:
        # Audit fix: a parent dir must resolve to the NEWEST run, not the oldest.
        runs = tmp_path / "runs"
        for name, cost_val in (("run_20260101_010000_a", 1.0), ("run_20260615_120000_c", 9.0)):
            rd = runs / name
            rd.mkdir(parents=True)
            (rd / "cost_summary.json").write_text(json.dumps({**self._SUMMARY, "total_cost": cost_val}))
        r = CliRunner().invoke(main, ["cost", str(runs), "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["total_cost"] == 9.0  # newest, not oldest (1.0)

    def test_cost_rich_shows_step_and_routing(self, tmp_path: Path) -> None:
        summary = {**self._SUMMARY, "routing": {"provider": "bedrock", "base_url": None, "models_used": ["m"]}}
        rd = self._run_dir(tmp_path, summary)
        r = CliRunner().invoke(main, ["cost", str(rd)])
        assert "By Step" in r.output
        assert "Routing:" in r.output
