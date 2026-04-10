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
                    "_subject_safe_name": "a",
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
                    "_subject_safe_name": "a",
                    "agent": "legal",
                    "description": "desc",
                },
            ],
        )
        result = export_findings_csv(computed)
        lines = result.strip().split("\n")
        assert len(lines) == 2  # header + 1 row

    def test_csv_injection_sanitized(self) -> None:
        from dd_agents.reporting.export import export_findings_csv

        computed = ReportComputedData(
            material_findings=[
                {
                    "title": "=CMD('calc')",
                    "severity": "P1",
                    "category": "+malicious",
                    "_domain": "legal",
                    "_subject_safe_name": "@evil",
                    "agent": "legal",
                    "description": "-formula injection",
                },
            ],
        )
        result = export_findings_csv(computed)
        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert row["title"].startswith("\t=")
        assert row["category"].startswith("\t+")
        assert row["entity"].startswith("\t@")
        assert row["description"].startswith("\t-")

    def test_csv_injection_pipe_and_percent(self) -> None:
        from dd_agents.reporting.export import _sanitize_csv_field

        assert _sanitize_csv_field("|pipe command") == "\t|pipe command"
        assert _sanitize_csv_field("%macro") == "\t%macro"
        assert _sanitize_csv_field("safe text") == "safe text"
        assert _sanitize_csv_field("") == ""


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

    def test_provenance_stamped_during_merge(self) -> None:
        """Merge pipeline should stamp provenance on each finding's metadata."""
        from dd_agents.reporting.merge import FindingMerger

        merger = FindingMerger(run_id="test-run", timestamp="2026-01-01T00:00:00Z")
        agent_outputs = {
            "legal": {
                "subject": "Test Corp",
                "findings": [
                    {
                        "severity": "P1",
                        "title": "CoC clause",
                        "description": "Change of control detected",
                        "category": "coc",
                        "citations": [
                            {
                                "source_path": "contract.pdf",
                                "source_type": "file",
                                "exact_quote": "Upon change of control...",
                                "location": "Section 5",
                            }
                        ],
                    },
                ],
            },
        }
        result = merger.merge_subject(agent_outputs, "Test Corp", "test_corp")
        assert len(result.findings) == 1
        meta = result.findings[0].metadata
        assert "provenance" in meta
        prov = meta["provenance"]
        assert prov["agent_name"] == "legal"
        assert prov["merge_action"] == "kept"
        assert prov["citation_verified"] is True
        assert "legal" in prov["contributing_agents"]
