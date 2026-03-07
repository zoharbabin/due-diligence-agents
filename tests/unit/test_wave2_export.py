"""Tests for structured data export and finding provenance."""

from __future__ import annotations

import csv
import io
import json

from dd_agents.reporting.computed_metrics import ReportComputedData


class TestFindingsJsonExport:
    def test_empty_findings(self) -> None:
        from dd_agents.reporting.export import export_findings_json

        computed = ReportComputedData()
        result = json.loads(export_findings_json(computed, {}))
        assert result["summary"]["total_findings"] == 0
        assert result["findings"] == []

    def test_findings_exported(self) -> None:
        from dd_agents.reporting.export import export_findings_json

        computed = ReportComputedData(
            material_findings=[
                {
                    "title": "CoC risk",
                    "severity": "P0",
                    "category": "coc",
                    "_domain": "legal",
                    "_customer_safe_name": "a",
                    "agent": "legal",
                },
            ],
            material_count=1,
            material_by_severity={"P0": 1, "P1": 0, "P2": 0, "P3": 0},
        )
        result = json.loads(export_findings_json(computed, {}))
        assert result["summary"]["total_findings"] == 1
        assert result["findings"][0]["severity"] == "P0"
        assert result["findings"][0]["title"] == "CoC risk"


class TestFindingsCsvExport:
    def test_csv_headers(self) -> None:
        from dd_agents.reporting.export import export_findings_csv

        computed = ReportComputedData()
        result = export_findings_csv(computed)
        reader = csv.reader(io.StringIO(result))
        headers = next(reader)
        assert "severity" in headers
        assert "title" in headers
        assert "entity" in headers

    def test_csv_rows(self) -> None:
        from dd_agents.reporting.export import export_findings_csv

        computed = ReportComputedData(
            material_findings=[
                {
                    "title": "Test",
                    "severity": "P1",
                    "category": "test",
                    "_domain": "legal",
                    "_customer_safe_name": "a",
                    "agent": "legal",
                    "description": "desc",
                },
            ],
        )
        result = export_findings_csv(computed)
        lines = result.strip().split("\n")
        assert len(lines) == 2  # header + 1 row


class TestRiskSummaryExport:
    def test_risk_summary_structure(self) -> None:
        from dd_agents.reporting.export import export_risk_summary_json

        computed = ReportComputedData(
            deal_risk_score=75.0,
            deal_risk_label="High",
            total_contracted_arr=1_000_000.0,
            risk_adjusted_arr=800_000.0,
        )
        result = json.loads(export_risk_summary_json(computed))
        assert result["deal_risk"]["score"] == 75.0
        assert result["financial"]["revenue_at_risk"] == 200_000.0


class TestFindingProvenanceModel:
    def test_provenance_model_exists(self) -> None:
        from dd_agents.models.finding import FindingProvenance

        p = FindingProvenance()
        assert p.extraction_method == "unknown"
        assert p.merge_action == "kept"
        assert p.contributing_agents == []

    def test_provenance_with_data(self) -> None:
        from dd_agents.models.finding import FindingProvenance

        p = FindingProvenance(
            extraction_method="pymupdf",
            extraction_confidence=0.95,
            agent_name="legal",
            citation_verified=True,
            merge_action="severity_escalated",
            contributing_agents=["legal", "finance"],
            recalibrated=True,
            recalibration_reason="competitor_only_coc",
        )
        assert p.extraction_confidence == 0.95
        assert len(p.contributing_agents) == 2
