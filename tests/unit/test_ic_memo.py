"""Tests for IC memo generation (Issue #190)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.reporting.computed_metrics import ReportComputedData
from dd_agents.reporting.ic_memo import _FORBIDDEN_PHRASES, memo_to_html, render_ic_memo

if TYPE_CHECKING:
    from pathlib import Path


def _computed() -> ReportComputedData:
    return ReportComputedData(
        subjects_analyzed=1,
        total_findings=42,
        total_gaps=3,
        deal_risk_label="High",
        deal_risk_score=72.0,
        verdict={
            "signal": "Conditional Go",
            "rationale": "Material change-of-control exposure concentrated in one customer.",
            "contributing_factors": ["30.1% revenue at risk", "Auto-terminate on CoC"],
        },
        executive_synthesis={
            "key_takeaways": [{"text": "Meridian Freight is 30.1% of ARR and auto-terminates on change of control."}]
        },
        wolf_pack=[
            {
                "severity": "P0",
                "_subject": "Northwind",
                "title": "CoC auto-termination",
                "citations": [{"exact_quote": "MSA terminates on change of control", "location": "§12.3"}],
            }
        ],
        recommendations=[{"action": "Obtain consent waiver from Meridian", "owner": "Legal", "timeline": "Pre-close"}],
    )


_DEAL = {"buyer": {"name": "Summit"}, "target": {"name": "Northwind"}, "deal": {"type": "acquisition"}}


class TestRenderIcMemo:
    def test_assembles_all_sections(self) -> None:
        md = render_ic_memo(_computed(), _DEAL)
        assert "# Investment Committee Memo" in md
        assert "Recommendation (Go / No-Go)" in md
        assert "Conditional Go" in md
        assert "Key Takeaways" in md
        assert "Top Risks" in md
        assert "Recommendations" in md
        assert "Appendix" in md

    def test_top_risk_includes_cited_evidence(self) -> None:
        md = render_ic_memo(_computed(), _DEAL)
        assert "CoC auto-termination" in md
        assert "MSA terminates on change of control" in md  # the verbatim quote
        assert "§12.3" in md

    def test_recommendation_table_has_owner_and_timeline(self) -> None:
        md = render_ic_memo(_computed(), _DEAL)
        assert "Obtain consent waiver from Meridian" in md
        assert "Legal" in md
        assert "Pre-close" in md

    def test_deterministic(self) -> None:
        assert render_ic_memo(_computed(), _DEAL) == render_ic_memo(_computed(), _DEAL)

    def test_guardrail_phrases_absent(self) -> None:
        md = render_ic_memo(_computed(), _DEAL).lower()
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase not in md, f"forbidden positioning phrase leaked: {phrase!r}"

    def test_thin_deal_omits_empty_sections(self) -> None:
        # No takeaways / recs / risks → those sections are omitted, no crash.
        md = render_ic_memo(ReportComputedData(deal_risk_label="Clean"), None)
        assert "# Investment Committee Memo" in md
        assert "Key Takeaways" not in md  # omitted when empty
        assert "No P0/P1 risks were identified." in md


class TestMemoToHtml:
    def test_self_contained_html(self) -> None:
        html = memo_to_html(render_ic_memo(_computed(), _DEAL))
        assert html.startswith("<!DOCTYPE html>")
        assert "<h1>" in html and "<table" in html and "<blockquote>" in html
        # No raw markdown pipes leaked into the body as text.
        assert "| Severity |" not in html

    def test_escapes_html_in_content(self) -> None:
        c = _computed()
        c.wolf_pack[0]["title"] = "<script>alert(1)</script>"
        html = memo_to_html(render_ic_memo(c, _DEAL))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestMemoCli:
    def test_memo_command_end_to_end(self, tmp_path: Path) -> None:
        import json

        from click.testing import CliRunner

        from dd_agents.cli import main

        # Minimal completed-run layout: <run>/findings/merged/<subject>.json
        run = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_x"
        merged = run / "findings" / "merged"
        merged.mkdir(parents=True)
        (merged / "northwind.json").write_text(
            json.dumps(
                {
                    "subject": "Northwind",
                    "findings": [
                        {
                            "title": "CoC auto-termination",
                            "severity": "P0",
                            "description": "Customer MSA terminates on change of control.",
                            "citations": [{"exact_quote": "terminates on change of control", "location": "§12.3"}],
                        }
                    ],
                    "gaps": [],
                }
            )
        )
        result = CliRunner().invoke(main, ["memo", "--report", str(run)])
        assert result.exit_code == 0, result.output
        md = run / "report" / "ic_memo.md"
        html = run / "report" / "ic_memo.html"
        assert md.exists() and html.exists()
        assert "# Investment Committee Memo" in md.read_text()

    def test_memo_discovers_deal_config_up_the_tree(self, tmp_path: Path) -> None:
        import json

        from click.testing import CliRunner

        from dd_agents.cli import main

        # deal-config.json at the project root; run nested several levels below.
        (tmp_path / "deal-config.json").write_text(
            json.dumps({"buyer": {"name": "Summit"}, "target": {"name": "Northwind"}, "deal": {"type": "acquisition"}})
        )
        run = tmp_path / "data_room" / "_dd" / "forensic-dd" / "runs" / "run_x"
        merged = run / "findings" / "merged"
        merged.mkdir(parents=True)
        (merged / "n.json").write_text(json.dumps({"subject": "Northwind", "findings": [], "gaps": []}))

        result = CliRunner().invoke(main, ["memo", "--report", str(run)])
        assert result.exit_code == 0, result.output
        # Header populated from the discovered config (not silently dropped).
        md = (run / "report" / "ic_memo.md").read_text()
        assert "**Target:** Northwind" in md
        assert "**Acquirer:** Summit" in md

    def test_memo_command_errors_without_findings(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from dd_agents.cli import main

        run = tmp_path / "run_empty"
        (run / "findings" / "merged").mkdir(parents=True)
        result = CliRunner().invoke(main, ["memo", "--report", str(run)])
        assert result.exit_code == 1
        assert "No Merged Findings" in result.output
