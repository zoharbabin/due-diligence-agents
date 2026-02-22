"""Unit tests for the reporting module.

Covers:
- FindingMerger: merge, dedup, severity escalation, ID generation, governance merge
- ReportDiffBuilder: detect new/resolved/changed findings between runs
- ExcelReportGenerator: schema-driven workbook generation, sheets, formatting
- ContractDateReconciler: classify customers by contract status
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from dd_agents.models.reporting import ReportSchema
from dd_agents.reporting.contract_dates import (
    STATUS_ACTIVE_AUTO_RENEWAL,
    STATUS_ACTIVE_DB_STALE,
    STATUS_EXPIRED_CONFIRMED,
    STATUS_EXPIRED_NO_CONTRACTS,
    STATUS_LIKELY_ACTIVE,
    ContractDateReconciler,
)
from dd_agents.reporting.diff import ReportDiffBuilder
from dd_agents.reporting.excel import ExcelReportGenerator, compute_overall_risk
from dd_agents.reporting.merge import FindingMerger

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    category: str = "change_of_control",
    source_path: str = "contract.pdf",
    location: str = "Section 5",
    exact_quote: str = "Sample quote",
    title: str = "Test finding",
    description: str = "A test finding",
    confidence: str = "high",
) -> dict:
    """Build a minimal agent-output finding dict."""
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "citations": [
            {
                "source_type": "file",
                "source_path": source_path,
                "location": location,
                "exact_quote": exact_quote,
            }
        ],
        "confidence": confidence,
    }


def _make_gap(
    customer: str = "Acme Corp",
    priority: str = "P1",
    gap_type: str = "Missing_Doc",
    missing_item: str = "MSA",
) -> dict:
    return {
        "customer": customer,
        "priority": priority,
        "gap_type": gap_type,
        "missing_item": missing_item,
        "why_needed": "Required for risk assessment",
        "risk_if_missing": "Incomplete analysis",
        "request_to_company": "Please provide the document",
        "evidence": "Referenced in SOW",
        "detection_method": "cross_reference",
    }


@pytest.fixture()
def report_schema_model() -> ReportSchema:
    """Load the real report_schema.json from config/."""
    schema_path = Path(__file__).parent.parent.parent / "config" / "report_schema.json"
    raw = json.loads(schema_path.read_text())
    return ReportSchema.model_validate(raw)


# ===========================================================================
# FindingMerger tests
# ===========================================================================


class TestFindingMerger:
    """Test the FindingMerger class."""

    def test_merge_two_agents_for_one_customer(self) -> None:
        """Merge findings from legal and finance for a single customer."""
        legal_output = {
            "customer": "Acme Corp",
            "customer_safe_name": "acme_corp",
            "findings": [
                _make_finding(severity="P1", source_path="msa.pdf", location="Section 3"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        finance_output = {
            "customer": "Acme Corp",
            "customer_safe_name": "acme_corp",
            "findings": [
                _make_finding(severity="P2", source_path="sow.pdf", location="Section 1"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }

        merger = FindingMerger(run_id="test_run", timestamp="2025-01-01T00:00:00Z")
        result = merger.merge_customer(
            agent_outputs={"legal": legal_output, "finance": finance_output},
            customer_name="Acme Corp",
            customer_safe_name="acme_corp",
        )

        assert result.customer == "Acme Corp"
        assert result.customer_safe_name == "acme_corp"
        assert len(result.findings) == 2

    def test_dedup_by_match_key_keeps_highest_severity(self) -> None:
        """Two findings with same source_path + location should dedup; highest severity wins."""
        legal_output = {
            "customer": "Acme Corp",
            "findings": [
                _make_finding(severity="P2", source_path="msa.pdf", location="Section 5"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        finance_output = {
            "customer": "Acme Corp",
            "findings": [
                _make_finding(severity="P1", source_path="msa.pdf", location="Section 5"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }

        merger = FindingMerger(run_id="test_run", timestamp="2025-01-01T00:00:00Z")
        result = merger.merge_customer(
            agent_outputs={"legal": legal_output, "finance": finance_output},
            customer_name="Acme Corp",
        )

        # Should be deduped to 1 finding
        assert len(result.findings) == 1
        assert result.findings[0].severity == "P1"

    def test_dedup_longest_exact_quote_on_tie(self) -> None:
        """When severity is equal, the finding with the longest exact_quote wins."""
        short_quote = _make_finding(
            severity="P1",
            source_path="msa.pdf",
            location="Section 5",
            exact_quote="Short",
        )
        long_quote = _make_finding(
            severity="P1",
            source_path="msa.pdf",
            location="Section 5",
            exact_quote="This is a much longer quote that should be preferred",
        )

        legal_output = {
            "customer": "Acme Corp",
            "findings": [short_quote],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        finance_output = {
            "customer": "Acme Corp",
            "findings": [long_quote],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        result = merger.merge_customer(
            agent_outputs={"legal": legal_output, "finance": finance_output},
            customer_name="Acme Corp",
        )

        assert len(result.findings) == 1
        # The winner should have the longer quote
        assert "much longer" in result.findings[0].citations[0].exact_quote

    def test_finding_id_generation(self) -> None:
        """Auto-generated IDs follow the pattern forensic-dd_{agent}_{safe_name}_{seq}."""
        agent_output = {
            "customer": "Acme Corp",
            "findings": [
                _make_finding(source_path="a.pdf", location="S1"),
                _make_finding(source_path="b.pdf", location="S2"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        result = merger.merge_customer(
            agent_outputs={"legal": agent_output},
            customer_name="Acme Corp",
            customer_safe_name="acme_corp",
        )

        assert len(result.findings) == 2
        assert result.findings[0].id == "forensic-dd_legal_acme_corp_0001"
        assert result.findings[1].id == "forensic-dd_legal_acme_corp_0002"

    def test_governance_merge_legal_primary(self) -> None:
        """Legal governance is primary; other agents add supplementary edges."""
        legal_output = {
            "customer": "Acme Corp",
            "findings": [],
            "governance_graph": {
                "edges": [
                    {"from_file": "sow.pdf", "to_file": "msa.pdf", "relationship": "governs"},
                ]
            },
            "cross_references": [],
        }
        finance_output = {
            "customer": "Acme Corp",
            "findings": [],
            "governance_graph": {
                "edges": [
                    # Same edge as legal -- should not duplicate
                    {"from_file": "sow.pdf", "to_file": "msa.pdf", "relationship": "governs"},
                    # New edge legal missed
                    {"from_file": "po.pdf", "to_file": "sow.pdf", "relationship": "references"},
                ]
            },
            "cross_references": [],
        }

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        result = merger.merge_customer(
            agent_outputs={"legal": legal_output, "finance": finance_output},
            customer_name="Acme Corp",
        )

        # 1 from legal + 1 new from finance (duplicate suppressed)
        assert len(result.governance_graph.edges) == 2

    def test_merge_all_from_directory(self, tmp_path: Path) -> None:
        """merge_all discovers and merges all customer files."""
        findings_dir = tmp_path / "findings"
        legal_dir = findings_dir / "legal"
        legal_dir.mkdir(parents=True)

        legal_output = {
            "customer": "Beta Inc",
            "customer_safe_name": "beta_inc",
            "findings": [
                _make_finding(source_path="beta_msa.pdf", location="S1"),
            ],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        (legal_dir / "beta_inc.json").write_text(json.dumps(legal_output))

        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")
        results = merger.merge_all(findings_dir)

        assert "beta_inc" in results
        assert len(results["beta_inc"].findings) == 1

    def test_write_merged(self, tmp_path: Path) -> None:
        """write_merged writes per-customer JSON files."""
        merger = FindingMerger(run_id="test", timestamp="2025-01-01T00:00:00Z")

        agent_output = {
            "customer": "Acme Corp",
            "findings": [_make_finding(source_path="a.pdf", location="S1")],
            "governance_graph": {"edges": []},
            "cross_references": [],
        }
        merged = {
            "acme_corp": merger.merge_customer(
                {"legal": agent_output},
                customer_name="Acme Corp",
                customer_safe_name="acme_corp",
            ),
        }

        out_dir = tmp_path / "merged"
        merger.write_merged(merged, out_dir)

        assert (out_dir / "acme_corp.json").exists()
        data = json.loads((out_dir / "acme_corp.json").read_text())
        assert data["customer"] == "Acme Corp"


# ===========================================================================
# ReportDiffBuilder tests
# ===========================================================================


class TestReportDiffBuilder:
    """Test the ReportDiffBuilder class."""

    @staticmethod
    def _setup_run_dir(
        base: Path,
        findings: dict[str, list[dict]],
        gaps: dict[str, list[dict]] | None = None,
    ) -> Path:
        """Create a findings directory tree for one run."""
        merged_dir = base / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)
        gaps_dir = merged_dir / "gaps"
        gaps_dir.mkdir(parents=True, exist_ok=True)

        for csn, f_list in findings.items():
            data = {"customer": csn, "findings": f_list}
            (merged_dir / f"{csn}.json").write_text(json.dumps(data))

        if gaps:
            for csn, g_list in gaps.items():
                (gaps_dir / f"{csn}.json").write_text(json.dumps({"gaps": g_list}))

        return base

    def test_detect_new_finding(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={"acme": []},
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={
                "acme": [
                    _make_finding(category="risk", source_path="msa.pdf", title="New risk"),
                ],
            },
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.new_findings == 1
        assert any(c.change_type == "new_finding" for c in diff.changes)

    def test_detect_resolved_finding(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={
                "acme": [
                    _make_finding(category="risk", source_path="msa.pdf", title="Old risk"),
                ],
            },
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={"acme": []},
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.resolved_findings == 1
        assert any(c.change_type == "resolved_finding" for c in diff.changes)

    def test_detect_changed_severity(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={
                "acme": [
                    _make_finding(
                        severity="P2",
                        category="risk",
                        source_path="msa.pdf",
                        title="Escalated",
                    ),
                ],
            },
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={
                "acme": [
                    _make_finding(
                        severity="P0",
                        category="risk",
                        source_path="msa.pdf",
                        title="Escalated",
                    ),
                ],
            },
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.changed_severity == 1
        change = next(c for c in diff.changes if c.change_type == "changed_severity")
        assert change.prior_severity == "P2"
        assert change.current_severity == "P0"

    def test_detect_new_and_removed_customer(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={"acme": [], "removed_co": []},
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={"acme": [], "new_co": []},
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.new_customers == 1
        assert diff.summary.removed_customers == 1

    def test_detect_new_gap(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={"acme": []},
            gaps={"acme": []},
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={"acme": []},
            gaps={
                "acme": [_make_gap(customer="acme", missing_item="SOW")],
            },
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.new_gaps == 1

    def test_detect_resolved_gap(self, tmp_path: Path) -> None:
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={"acme": []},
            gaps={"acme": [_make_gap(customer="acme", missing_item="SOW")]},
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={"acme": []},
            gaps={"acme": []},
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(current, prior)

        assert diff.summary.resolved_gaps == 1

    def test_write_diff(self, tmp_path: Path) -> None:
        """write_diff serializes the diff to JSON."""
        prior = self._setup_run_dir(
            tmp_path / "prior",
            findings={"acme": []},
        )
        current = self._setup_run_dir(
            tmp_path / "current",
            findings={"acme": []},
        )

        builder = ReportDiffBuilder()
        diff = builder.build_diff(
            current,
            prior,
            current_run_id="run_002",
            prior_run_id="run_001",
        )

        out = tmp_path / "report_diff.json"
        builder.write_diff(diff, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["current_run_id"] == "run_002"
        assert data["prior_run_id"] == "run_001"


# ===========================================================================
# ExcelReportGenerator tests
# ===========================================================================


class TestExcelReportGenerator:
    """Test the ExcelReportGenerator class."""

    def test_generate_workbook_from_schema(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """Generate a workbook from the real report_schema.json and verify structure."""
        # Build minimal merged data
        merged = {
            "acme_corp": {
                "customer": "Acme Corp",
                "customer_safe_name": "acme_corp",
                "findings": [
                    {
                        "id": "forensic-dd_legal_acme_corp_0001",
                        "severity": "P0",
                        "category": "change_of_control",
                        "title": "CoC clause",
                        "description": "Termination on change of control",
                        "citations": [
                            {
                                "source_type": "file",
                                "source_path": "msa.pdf",
                                "location": "Section 12",
                                "exact_quote": "terminate upon change of control",
                            }
                        ],
                        "confidence": "high",
                        "agent": "legal",
                        "analysis_unit": "Acme Corp",
                    },
                    {
                        "id": "forensic-dd_finance_acme_corp_0001",
                        "severity": "P2",
                        "category": "pricing",
                        "title": "Below market rate",
                        "description": "Pricing is 30% below market",
                        "citations": [
                            {
                                "source_type": "file",
                                "source_path": "sow.pdf",
                                "location": "Schedule A",
                                "exact_quote": "Total price: $100,000",
                            }
                        ],
                        "confidence": "medium",
                        "agent": "finance",
                        "analysis_unit": "Acme Corp",
                    },
                ],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.75,
                "files_analyzed": 5,
            },
        }

        deal_config: dict = {}  # No special conditions
        out_path = tmp_path / "report.xlsx"

        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path, deal_config)

        assert out_path.exists()

        # Verify with openpyxl
        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))

        # Count always-active sheets (10 sheets)
        always_active = [s for s in report_schema_model.sheets if s.activation_condition == "always"]
        for sheet_def in always_active:
            assert sheet_def.name in wb.sheetnames, f"Missing always-active sheet: {sheet_def.name}"

        # Conditional sheets should NOT be present when conditions are not met
        assert "Quality_Audit" not in wb.sheetnames
        assert "_Metadata" not in wb.sheetnames

    def test_sheet_column_headers_match_schema(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """Column headers in each sheet match the schema definition."""
        merged = {
            "acme": {
                "customer": "Acme",
                "findings": [],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.0,
            },
        }

        out_path = tmp_path / "report.xlsx"
        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path)

        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))

        for sheet_def in report_schema_model.sheets:
            if sheet_def.name not in wb.sheetnames:
                continue
            ws = wb[sheet_def.name]
            # Read header row
            headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
            # Filter columns without judge activation
            expected = [
                col.name
                for col in sheet_def.columns
                if col.activation_condition is None or col.activation_condition == "always"
            ]
            assert headers == expected, f"Sheet {sheet_def.name}: headers {headers} != expected {expected}"

    def test_severity_conditional_formatting(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """P0 findings in the Wolf_Pack sheet should have red background."""
        merged = {
            "acme": {
                "customer": "Acme",
                "findings": [
                    {
                        "id": "forensic-dd_legal_acme_0001",
                        "severity": "P0",
                        "category": "test",
                        "title": "Critical",
                        "description": "Very bad",
                        "citations": [
                            {
                                "source_type": "file",
                                "source_path": "msa.pdf",
                                "location": "S1",
                                "exact_quote": "quote here",
                            }
                        ],
                        "confidence": "high",
                        "agent": "legal",
                        "analysis_unit": "Acme",
                    },
                ],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.0,
            },
        }

        out_path = tmp_path / "report.xlsx"
        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path)

        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))
        ws = wb["Wolf_Pack"]

        # Find the severity column
        sev_col = None
        for c in range(1, ws.max_column + 1):
            if ws.cell(row=1, column=c).value == "Severity":
                sev_col = c
                break

        assert sev_col is not None
        # Row 2 should have severity P0 with red fill
        sev_cell = ws.cell(row=2, column=sev_col)
        assert sev_cell.value == "P0"
        assert sev_cell.fill.start_color.rgb is not None
        # The fill should be FF0000 (with possible alpha prefix)
        assert "FF0000" in sev_cell.fill.start_color.rgb

    def test_conditional_sheets_activated(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """When deal_config activates conditional sheets, they appear."""
        merged = {
            "acme": {
                "customer": "Acme",
                "findings": [],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.0,
            },
        }
        deal_config = {
            "judge": {"enabled": True},
            "reporting": {
                "include_metadata_sheet": True,
                "include_diff_sheet": True,
            },
            "source_of_truth": {
                "customer_database": {"path": "customers.csv"},
            },
        }

        out_path = tmp_path / "report.xlsx"
        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path, deal_config)

        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))

        assert "Quality_Audit" in wb.sheetnames
        assert "_Metadata" in wb.sheetnames
        assert "Run_Diff" in wb.sheetnames
        assert "Contract_Date_Reconciliation" in wb.sheetnames

    def test_freeze_panes_and_auto_filter(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """Verify freeze panes and auto-filter are applied."""
        merged = {
            "acme": {
                "customer": "Acme",
                "findings": [
                    {
                        "id": "forensic-dd_legal_acme_0001",
                        "severity": "P2",
                        "category": "test",
                        "title": "Finding",
                        "description": "Desc",
                        "citations": [
                            {
                                "source_type": "file",
                                "source_path": "msa.pdf",
                                "location": "S1",
                                "exact_quote": "q",
                            }
                        ],
                        "confidence": "high",
                        "agent": "legal",
                        "analysis_unit": "Acme",
                    },
                ],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.0,
            },
        }

        out_path = tmp_path / "report.xlsx"
        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path)

        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))
        ws = wb["Summary"]

        # Freeze panes at A2 (row 1 frozen)
        assert ws.freeze_panes == "A2"
        # Auto-filter should be set
        assert ws.auto_filter.ref is not None

    def test_summary_formulas(
        self,
        tmp_path: Path,
        report_schema_model: ReportSchema,
    ) -> None:
        """Summary row should contain computed totals."""
        merged = {
            "acme": {
                "customer": "Acme",
                "findings": [
                    {
                        "id": "f1",
                        "severity": "P0",
                        "category": "test",
                        "title": "F1",
                        "description": "D",
                        "citations": [
                            {"source_type": "file", "source_path": "a.pdf", "location": "S1", "exact_quote": "q"}
                        ],
                        "confidence": "high",
                        "agent": "legal",
                        "analysis_unit": "Acme",
                    },
                ],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 1.0,
                "files_analyzed": 3,
            },
            "beta": {
                "customer": "Beta",
                "findings": [
                    {
                        "id": "f2",
                        "severity": "P1",
                        "category": "test",
                        "title": "F2",
                        "description": "D",
                        "citations": [
                            {"source_type": "file", "source_path": "b.pdf", "location": "S1", "exact_quote": "q"}
                        ],
                        "confidence": "high",
                        "agent": "finance",
                        "analysis_unit": "Beta",
                    },
                ],
                "gaps": [],
                "cross_references": [],
                "governance_graph": {"edges": []},
                "governance_resolved_pct": 0.5,
                "files_analyzed": 2,
            },
        }

        out_path = tmp_path / "report.xlsx"
        gen = ExcelReportGenerator()
        gen.generate(merged, report_schema_model, out_path)

        from openpyxl import load_workbook

        wb = load_workbook(str(out_path))
        ws = wb["Summary"]

        # Find the TOTAL row (last data row + 1)
        total_row = ws.max_row
        # Column 1 should say "TOTAL"
        assert ws.cell(row=total_row, column=1).value == "TOTAL"

        # total_findings column (column 7 in always-active)
        # P0 count col is 3, total_findings is 7
        total_findings_val = ws.cell(row=total_row, column=7).value
        assert total_findings_val == 2  # 1 from acme + 1 from beta


# ===========================================================================
# compute_overall_risk tests
# ===========================================================================


class TestComputeOverallRisk:
    """Test the risk rating algorithm."""

    def test_critical_on_p0_finding(self) -> None:
        findings = [{"severity": "P0", "category": "risk"}]
        assert compute_overall_risk(findings, []) == "Critical"

    def test_critical_on_p0_gap(self) -> None:
        findings: list[dict] = []
        gaps = [{"priority": "P0"}]
        assert compute_overall_risk(findings, gaps) == "Critical"

    def test_high_on_p1(self) -> None:
        findings = [{"severity": "P1", "category": "risk"}]
        assert compute_overall_risk(findings, []) == "High"

    def test_medium_on_p2(self) -> None:
        findings = [{"severity": "P2", "category": "risk"}]
        assert compute_overall_risk(findings, []) == "Medium"

    def test_low_on_p3_only(self) -> None:
        findings = [{"severity": "P3", "category": "risk"}]
        assert compute_overall_risk(findings, []) == "Low"

    def test_clean_when_empty(self) -> None:
        assert compute_overall_risk([], []) == "Clean"

    def test_clean_ignores_domain_reviewed(self) -> None:
        findings = [{"severity": "P3", "category": "domain_reviewed_no_issues"}]
        assert compute_overall_risk(findings, []) == "Clean"


# ===========================================================================
# ContractDateReconciler tests
# ===========================================================================


class TestContractDateReconciler:
    """Test the ContractDateReconciler class."""

    def test_active_contract_not_expired(self) -> None:
        """Database end date in the future => Active-Database Stale."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 1, 15))
        db = [
            {"customer": "Acme", "contract_end_date": "2026-06-30", "arr": 500000},
        ]
        result = reconciler.reconcile(db, findings={})

        assert len(result.entries) == 1
        assert result.entries[0].status == STATUS_ACTIVE_DB_STALE

    def test_expired_with_auto_renewal(self) -> None:
        """Expired per DB but auto-renewal clause found => Active-Auto-Renewal."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [
            {"customer": "Beta", "contract_end_date": "2024-12-31", "arr": 200000},
        ]
        findings = {
            "Beta": [
                {
                    "title": "Auto-renewal clause in MSA",
                    "description": "Contract contains auto-renewal provision",
                    "category": "term",
                    "citations": [
                        {"source_type": "file", "source_path": "msa.pdf", "location": "S8"},
                    ],
                },
            ],
        }
        result = reconciler.reconcile(db, findings)

        assert len(result.entries) == 1
        assert result.entries[0].status == STATUS_ACTIVE_AUTO_RENEWAL

    def test_expired_no_contracts(self) -> None:
        """Expired and no contract documents at all => Expired-No Contracts."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [
            {"customer": "Ghost", "contract_end_date": "2024-06-30", "arr": 0},
        ]
        result = reconciler.reconcile(db, findings={})

        assert len(result.entries) == 1
        assert result.entries[0].status == STATUS_EXPIRED_NO_CONTRACTS

    def test_expired_confirmed(self) -> None:
        """Expired, ARR=0, contracts exist but no renewal evidence => Expired-Confirmed."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [
            {"customer": "OldCo", "contract_end_date": "2023-12-31", "arr": 0},
        ]
        # Findings exist but with no renewal keywords
        findings = {
            "OldCo": [
                {
                    "title": "Termination clause present",
                    "description": "Section 10 allows termination",
                    "category": "termination",
                    "citations": [],
                },
            ],
        }
        result = reconciler.reconcile(db, findings)

        assert len(result.entries) == 1
        assert result.entries[0].status == STATUS_EXPIRED_CONFIRMED

    def test_likely_active_with_arr(self) -> None:
        """Expired per DB, ARR > 0, no renewal evidence => Likely Active."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [
            {"customer": "MaybeCo", "contract_end_date": "2024-06-30", "arr": 100000},
        ]
        # Findings exist but no renewal keywords
        findings = {
            "MaybeCo": [
                {
                    "title": "Standard clause",
                    "description": "Nothing special",
                    "category": "general",
                    "citations": [],
                },
            ],
        }
        result = reconciler.reconcile(db, findings)

        assert len(result.entries) == 1
        assert result.entries[0].status == STATUS_LIKELY_ACTIVE

    def test_arr_totals(self) -> None:
        """Verify total_reclassified_arr and total_expired_arr are computed correctly."""
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [
            {"customer": "Active1", "contract_end_date": "2026-12-31", "arr": 300000},
            {"customer": "Expired1", "contract_end_date": "2023-01-01", "arr": 0},
        ]
        result = reconciler.reconcile(db, findings={})

        assert result.total_reclassified_arr == 300000.0
        assert result.total_expired_arr == 0.0

    def test_write_reconciliation(self, tmp_path: Path) -> None:
        reconciler = ContractDateReconciler(reference_date=date(2025, 3, 1))
        db = [{"customer": "Test", "contract_end_date": "2026-01-01", "arr": 100}]
        result = reconciler.reconcile(db, findings={}, run_id="test_run")

        out = tmp_path / "recon.json"
        reconciler.write_reconciliation(result, out)

        assert out.exists()
        data = json.loads(out.read_text())
        assert data["run_id"] == "test_run"
        assert len(data["entries"]) == 1
