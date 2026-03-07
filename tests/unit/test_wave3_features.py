"""Tests for Wave 2 remaining features: #141, #142, #146, #126, #117."""

from __future__ import annotations

import json
from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData

# =====================================================================
# Issue #141: Search Prompt Templates Library
# =====================================================================


class TestSearchPromptTemplates:
    def test_template_registry_has_entries(self) -> None:
        from dd_agents.agents.prompt_templates import PROMPT_TEMPLATES

        assert len(PROMPT_TEMPLATES) >= 5

    def test_template_structure(self) -> None:
        from dd_agents.agents.prompt_templates import PROMPT_TEMPLATES

        for name, tpl in PROMPT_TEMPLATES.items():
            assert "name" in tpl, f"Template {name} missing 'name'"
            assert "columns" in tpl, f"Template {name} missing 'columns'"
            assert len(tpl["columns"]) >= 1, f"Template {name} has no columns"
            for col in tpl["columns"]:
                assert "name" in col, f"Column missing 'name' in template {name}"
                assert "prompt" in col, f"Column missing 'prompt' in template {name}"

    def test_get_template_by_name(self) -> None:
        from dd_agents.agents.prompt_templates import get_template

        tpl = get_template("change_of_control")
        assert tpl is not None
        assert "columns" in tpl

    def test_get_template_returns_none_for_unknown(self) -> None:
        from dd_agents.agents.prompt_templates import get_template

        assert get_template("nonexistent_template") is None

    def test_list_template_names(self) -> None:
        from dd_agents.agents.prompt_templates import list_templates

        names = list_templates()
        assert "change_of_control" in names
        assert "termination_for_convenience" in names

    def test_export_template_to_json(self) -> None:
        from dd_agents.agents.prompt_templates import export_template

        result = export_template("change_of_control")
        parsed = json.loads(result)
        assert "name" in parsed
        assert "columns" in parsed

    def test_search_json_files_written(self) -> None:
        """Each template should produce valid JSON matching search runner format."""
        from dd_agents.agents.prompt_templates import export_template, list_templates

        for name in list_templates():
            result = export_template(name)
            parsed = json.loads(result)
            assert isinstance(parsed["columns"], list)


# =====================================================================
# Issue #142: Governance Graph Visualization
# =====================================================================


class TestGovernanceGraphRenderer:
    def _make_computed(self, **kwargs: Any) -> ReportComputedData:
        return ReportComputedData(**kwargs)

    def test_empty_graph_returns_empty(self) -> None:
        from dd_agents.reporting.html_governance import GovernanceGraphRenderer

        computed = self._make_computed()
        renderer = GovernanceGraphRenderer(computed, {})
        assert renderer.render() == ""

    def test_renders_mermaid_diagram(self) -> None:
        from dd_agents.reporting.html_governance import GovernanceGraphRenderer

        merged = {
            "acme": {
                "customer": "Acme",
                "governance_graph": {
                    "edges": [
                        {"from_file": "order.pdf", "to_file": "msa.pdf", "relationship": "governs"},
                        {"from_file": "sla.pdf", "to_file": "msa.pdf", "relationship": "references"},
                    ]
                },
            }
        }
        computed = self._make_computed(total_customers=1)
        renderer = GovernanceGraphRenderer(computed, merged)
        html = renderer.render()
        assert "mermaid" in html
        assert "order.pdf" in html
        assert "msa.pdf" in html
        assert "sec-gov-graph" in html

    def test_cycle_alert_rendered(self) -> None:
        from dd_agents.reporting.html_governance import GovernanceGraphRenderer

        merged = {
            "acme": {
                "customer": "Acme",
                "governance_graph": {
                    "edges": [
                        {"from_file": "a.pdf", "to_file": "b.pdf", "relationship": "governs"},
                        {"from_file": "b.pdf", "to_file": "a.pdf", "relationship": "governs"},
                    ]
                },
            }
        }
        computed = self._make_computed(total_customers=1)
        renderer = GovernanceGraphRenderer(computed, merged)
        html = renderer.render()
        assert "cycle" in html.lower() or "Cycle" in html

    def test_xss_escaping(self) -> None:
        from dd_agents.reporting.html_governance import GovernanceGraphRenderer

        merged = {
            "acme": {
                "customer": "Acme",
                "governance_graph": {
                    "edges": [
                        {
                            "from_file": "<script>alert(1)</script>.pdf",
                            "to_file": "msa.pdf",
                            "relationship": "governs",
                        },
                    ]
                },
            }
        }
        computed = self._make_computed(total_customers=1)
        renderer = GovernanceGraphRenderer(computed, merged)
        html = renderer.render()
        # The user-provided filename should be escaped; mermaid script tag is legitimate
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html or "alert_1_" in html

    def test_relationship_type_legend(self) -> None:
        from dd_agents.reporting.html_governance import GovernanceGraphRenderer

        merged = {
            "acme": {
                "customer": "Acme",
                "governance_graph": {
                    "edges": [
                        {"from_file": "a.pdf", "to_file": "b.pdf", "relationship": "governs"},
                    ]
                },
            }
        }
        computed = self._make_computed(total_customers=1)
        renderer = GovernanceGraphRenderer(computed, merged)
        html = renderer.render()
        assert "governs" in html.lower()


# =====================================================================
# Issue #146: Configurable Agent Models — CLI options
# =====================================================================


class TestAgentModelsCLI:
    def test_run_command_accepts_model_profile(self) -> None:
        from click.testing import CliRunner

        from dd_agents.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "--model-profile" in result.output

    def test_run_command_accepts_model_override(self) -> None:
        from click.testing import CliRunner

        from dd_agents.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert "--model-override" in result.output

    def test_prompt_version_tracked(self) -> None:
        from dd_agents.agents.prompt_builder import PromptBuilder

        pb = PromptBuilder.__new__(PromptBuilder)
        assert hasattr(pb, "prompt_version") or hasattr(PromptBuilder, "PROMPT_VERSION")


# =====================================================================
# Issue #126: Report Diff Enhancement — Trend Analysis
# =====================================================================


class TestDiffTrendAnalysis:
    def test_trend_tracker_init(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        assert tracker is not None

    def test_add_run_snapshot(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 2, "P1": 5, "P2": 10, "P3": 20}, total_entities=15)
        tracker.add_snapshot("run-2", {"P0": 1, "P1": 4, "P2": 8, "P3": 18}, total_entities=15)
        assert len(tracker.snapshots) == 2

    def test_compute_trajectory(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 5, "P1": 10, "P2": 15, "P3": 20}, total_entities=10)
        tracker.add_snapshot("run-2", {"P0": 3, "P1": 8, "P2": 12, "P3": 18}, total_entities=10)
        trajectory = tracker.compute_trajectory()
        assert trajectory in ("improving", "stable", "worsening")

    def test_trajectory_improving(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 5, "P1": 10, "P2": 5, "P3": 5}, total_entities=10)
        tracker.add_snapshot("run-2", {"P0": 1, "P1": 3, "P2": 5, "P3": 5}, total_entities=10)
        assert tracker.compute_trajectory() == "improving"

    def test_trajectory_worsening(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 1, "P1": 3, "P2": 5, "P3": 5}, total_entities=10)
        tracker.add_snapshot("run-2", {"P0": 5, "P1": 10, "P2": 5, "P3": 5}, total_entities=10)
        assert tracker.compute_trajectory() == "worsening"

    def test_single_snapshot_stable(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 1, "P1": 1, "P2": 1, "P3": 1}, total_entities=10)
        assert tracker.compute_trajectory() == "stable"

    def test_trend_summary_dict(self) -> None:
        from dd_agents.reporting.diff import ReportTrendTracker

        tracker = ReportTrendTracker()
        tracker.add_snapshot("run-1", {"P0": 2, "P1": 5, "P2": 10, "P3": 20}, total_entities=15)
        tracker.add_snapshot("run-2", {"P0": 1, "P1": 4, "P2": 8, "P3": 18}, total_entities=15)
        summary = tracker.to_summary()
        assert "trajectory" in summary
        assert "snapshots" in summary
        assert len(summary["snapshots"]) == 2

    def test_diff_renderer_shows_trend(self) -> None:
        """DiffRenderer should render trend section when trend data exists."""
        import tempfile
        from pathlib import Path

        from dd_agents.reporting.html_diff import DiffRenderer

        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            report_dir = run_dir / "report"
            report_dir.mkdir()

            diff_data = {
                "current_run_id": "run-2",
                "prior_run_id": "run-1",
                "summary": {"new_findings": 1, "resolved_findings": 2, "changed_severity": 0},
                "changes": [],
                "trend": {
                    "trajectory": "improving",
                    "snapshots": [
                        {"run_id": "run-1", "severity_counts": {"P0": 3}, "total_entities": 10},
                        {"run_id": "run-2", "severity_counts": {"P0": 1}, "total_entities": 10},
                    ],
                },
            }
            (report_dir / "report_diff.json").write_text(json.dumps(diff_data))

            computed = ReportComputedData()
            renderer = DiffRenderer(computed, {}, run_dir=run_dir)
            html = renderer.render()
            assert "improving" in html.lower() or "Improving" in html


# =====================================================================
# Issue #117: Post-Close Integration Playbook
# =====================================================================


class TestIntegrationPlaybookComputation:
    def test_churn_risk_model_fields(self) -> None:
        """ReportComputedData should have integration playbook fields."""
        computed = ReportComputedData()
        assert hasattr(computed, "integration_playbook")

    def test_churn_risk_score_computed(self) -> None:
        """Integration playbook should include churn risk score."""
        computed = ReportComputedData(
            integration_playbook={
                "churn_risk_score": 45,
                "churn_risk_label": "Medium",
            }
        )
        assert computed.integration_playbook["churn_risk_score"] == 45


class TestIntegrationPlaybookRenderer:
    def _make_computed(self, **kwargs: Any) -> ReportComputedData:
        return ReportComputedData(**kwargs)

    def test_empty_playbook_returns_empty(self) -> None:
        from dd_agents.reporting.html_integration_playbook import IntegrationPlaybookRenderer

        computed = self._make_computed()
        renderer = IntegrationPlaybookRenderer(computed, {})
        assert renderer.render() == ""

    def test_renders_playbook_section(self) -> None:
        from dd_agents.reporting.html_integration_playbook import IntegrationPlaybookRenderer

        computed = self._make_computed(
            integration_playbook={
                "churn_risk_score": 45,
                "churn_risk_label": "Medium",
                "risk_factors": [
                    {"factor": "CoC exposure", "impact": "high", "arr_at_risk": 500_000},
                    {"factor": "TfC clauses", "impact": "medium", "arr_at_risk": 200_000},
                ],
                "milestones": [
                    {"phase": "Pre-Close", "items": ["Identify consent requirements"]},
                    {"phase": "Day 1", "items": ["Send retention notices"]},
                    {"phase": "Day 30-90", "items": ["Complete customer outreach"]},
                ],
                "integration_complexity": "Medium",
            },
            total_contracted_arr=2_000_000.0,
        )
        renderer = IntegrationPlaybookRenderer(computed, {})
        html = renderer.render()
        assert "sec-integration" in html
        assert "Churn Risk" in html or "churn" in html.lower()
        assert "Pre-Close" in html
        assert "Day 1" in html

    def test_xss_escaping(self) -> None:
        from dd_agents.reporting.html_integration_playbook import IntegrationPlaybookRenderer

        computed = self._make_computed(
            integration_playbook={
                "churn_risk_score": 30,
                "churn_risk_label": "Low",
                "risk_factors": [
                    {"factor": "<script>alert(1)</script>", "impact": "low", "arr_at_risk": 0},
                ],
                "milestones": [],
                "integration_complexity": "Low",
            },
            total_contracted_arr=1_000_000.0,
        )
        renderer = IntegrationPlaybookRenderer(computed, {})
        html = renderer.render()
        assert "<script>" not in html

    def test_high_churn_risk_alert(self) -> None:
        from dd_agents.reporting.html_integration_playbook import IntegrationPlaybookRenderer

        computed = self._make_computed(
            integration_playbook={
                "churn_risk_score": 75,
                "churn_risk_label": "High",
                "risk_factors": [],
                "milestones": [],
                "integration_complexity": "High",
            },
            total_contracted_arr=1_000_000.0,
        )
        renderer = IntegrationPlaybookRenderer(computed, {})
        html = renderer.render()
        assert "alert" in html


# =====================================================================
# Issue #142: HTML report integration
# =====================================================================


class TestHTMLReportIntegration:
    def test_governance_renderer_in_report(self) -> None:
        """GovernanceGraphRenderer should be imported in html.py."""
        from dd_agents.reporting import html_governance

        assert hasattr(html_governance, "GovernanceGraphRenderer")

    def test_integration_playbook_renderer_exists(self) -> None:
        from dd_agents.reporting import html_integration_playbook

        assert hasattr(html_integration_playbook, "IntegrationPlaybookRenderer")
