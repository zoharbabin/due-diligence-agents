"""Unit tests for Phase 1 report rendering fixes.

Covers:
- Category normalization (freeform -> canonical)
- Wolf pack P0-only filtering and similarity dedup
- Cross-reference field mapping to CrossReference model
- Gap table column additions (why_needed, request_to_company, agent)
- Executive summary renderer (Go/No-Go, heatmap, top 5 deal breakers)
- Report diff renderer (new/resolved/changed findings)
- Quality audit check rendering
- Terminology: "Subject" -> "Entity" throughout
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html import HTMLReportGenerator

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    severity: str = "P2",
    title: str = "Test finding",
    description: str = "A test finding description",
    agent: str = "legal",
    confidence: str = "high",
    category: str = "uncategorized",
    citations: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build a minimal finding dict for HTML rendering."""
    return {
        "severity": severity,
        "title": title,
        "description": description,
        "agent": agent,
        "confidence": confidence,
        "category": category,
        "citations": citations or [],
    }


def _make_gap(
    priority: str = "P1",
    gap_type: str = "Missing_Doc",
    missing_item: str = "MSA",
    risk_if_missing: str = "Incomplete analysis",
    why_needed: str = "Required for legal review",
    request_to_company: str = "Please provide the executed MSA",
    agent: str = "legal",
    evidence: str = "Referenced in SOW but not found in data room",
) -> dict[str, str]:
    """Build a minimal gap dict for HTML rendering."""
    return {
        "priority": priority,
        "gap_type": gap_type,
        "missing_item": missing_item,
        "risk_if_missing": risk_if_missing,
        "why_needed": why_needed,
        "request_to_company": request_to_company,
        "agent": agent,
        "evidence": evidence,
    }


def _make_merged_data_with_model_xrefs() -> dict[str, Any]:
    """Build merged data using CrossReference model field names."""
    return {
        "subject_a": {
            "subject": "Subject A",
            "findings": [_make_finding(severity="P1", title="Revenue mismatch", agent="finance")],
            "gaps": [],
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "$1,000,000",
                    "contract_source": {"file": "msa.pdf", "page": 3, "quote": "Annual fee of $1M"},
                    "reference_value": "$950,000",
                    "reference_source": {"file": "financials.xlsx", "tab": "Summary", "quote": "$950K"},
                    "match_status": "mismatch",
                    "variance": "-5.0%",
                },
                {
                    "data_point": "Payment Terms",
                    "contract_value": "Net 30",
                    "contract_source": {"file": "msa.pdf", "page": 5, "quote": "Net 30 days"},
                    "reference_value": "Net 30",
                    "reference_source": {"file": "invoice.pdf", "page": 1, "quote": "Net 30"},
                    "match_status": "match",
                },
            ],
        },
    }


# ===========================================================================
# Step A: Category normalization
# ===========================================================================


class TestCategoryNormalization:
    """Tests for canonical category mapping in computed_metrics."""

    def test_normalize_category_legal_mapping(self) -> None:
        """Freeform legal categories are mapped to canonical categories."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(category="change_of_control_clauses", agent="legal"),
                    _make_finding(category="termination_provisions_and_exit_clauses", agent="legal"),
                    _make_finding(category="ip_assignment_and_ownership", agent="legal"),
                    _make_finding(category="intellectual_property_issues", agent="legal"),
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        data = computer.compute(merged)

        # Both change_of_control and termination should map to canonical categories
        legal_cats = list(data.category_groups.get("legal", {}).keys())
        # Should have fewer categories due to normalization
        assert len(legal_cats) <= 3  # change_of_control, ip, and possibly termination

    def test_normalize_category_unknown_passthrough(self) -> None:
        """Categories that don't match any canonical pattern pass through as-is."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(category="very_unusual_unique_category_xyz", agent="legal"),
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        data = computer.compute(merged)

        legal_cats = list(data.category_groups.get("legal", {}).keys())
        # Unmapped category preserved (possibly under "Other")
        all_cats = " ".join(legal_cats)
        assert "very_unusual_unique_category_xyz" in all_cats or "other" in all_cats.lower()


# ===========================================================================
# Step B: Wolf pack overhaul
# ===========================================================================


class TestWolfPackOverhaul:
    """Tests for wolf_pack_p0 filtering and similarity dedup."""

    def test_wolf_pack_p0_only(self) -> None:
        """wolf_pack_p0 contains only P0 findings."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(severity="P0", title="Critical issue"),
                    _make_finding(severity="P1", title="High issue"),
                    _make_finding(severity="P2", title="Medium issue"),
                ],
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        data = computer.compute(merged)

        assert len(data.wolf_pack_p0) == 1
        assert data.wolf_pack_p0[0]["severity"] == "P0"

    def test_wolf_pack_p0_cap_15(self) -> None:
        """wolf_pack_p0 is capped at 15 findings."""
        findings = [_make_finding(severity="P0", title=f"Critical issue {i}") for i in range(20)]
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": findings,
                "gaps": [],
            },
        }
        computer = ReportDataComputer()
        data = computer.compute(merged)

        assert len(data.wolf_pack_p0) == 15

    def test_similar_finding_dedup(self, tmp_path: Path) -> None:
        """Findings with >0.7 title similarity are grouped with 'N similar' badge."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(severity="P0", title="Change of control clause terminates agreement"),
                    _make_finding(severity="P0", title="Change of control clause terminates contract"),
                    _make_finding(severity="P0", title="Change of control triggers termination right"),
                    _make_finding(severity="P0", title="Completely different IP assignment issue"),
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Should show "similar" badge for grouped findings
        assert "similar" in content.lower()
        # The dedup section should have fewer cards than total P0 findings
        # At least the 3 similar change-of-control findings should be grouped
        wolf_section_start = content.find("id='sec-wolf-pack'")
        wolf_section_end = content.find("</section>", wolf_section_start)
        wolf_html = content[wolf_section_start:wolf_section_end]
        # Should not have 4 separate wolf-card entries for the 3 similar findings
        assert wolf_html.count("wolf-card") < 4


# ===========================================================================
# Step D: Cross-reference field mapping
# ===========================================================================


class TestCrossRefFieldMapping:
    """Tests for cross-reference model field → renderer mapping."""

    def test_cross_ref_field_mapping(self, tmp_path: Path) -> None:
        """CrossReference model fields (data_point, contract_value, etc.) render correctly."""
        merged = _make_merged_data_with_model_xrefs()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # data_point should appear as the Field column
        assert "Annual Revenue" in content
        assert "Payment Terms" in content

        # contract_value and reference_value should appear
        assert "$1,000,000" in content
        assert "$950,000" in content
        assert "Net 30" in content

        # match_status should drive Yes/No
        assert "mismatch" in content.lower() or "No" in content

    def test_cross_ref_summary_stats(self, tmp_path: Path) -> None:
        """Cross-reference summary stats (match_rate) are displayed."""
        merged = _make_merged_data_with_model_xrefs()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Summary stats should be rendered
        assert "Match Rate" in content or "match rate" in content.lower() or "50%" in content


# ===========================================================================
# Step E: Gap table all columns
# ===========================================================================


class TestGapTableColumns:
    """Tests for enhanced gap table with additional columns."""

    def test_gap_table_all_columns(self, tmp_path: Path) -> None:
        """Gap table renders why_needed, request_to_company, and agent columns."""
        merged: dict[str, Any] = {
            "subject_a": {
                "subject": "Subject A",
                "findings": [],
                "gaps": [
                    _make_gap(
                        why_needed="Required for legal review",
                        request_to_company="Please provide the executed MSA",
                        agent="legal",
                    ),
                ],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # New column headers should be present
        assert "Why Needed</th>" in content
        assert "Request</th>" in content or "Request to Company</th>" in content
        assert "Agent</th>" in content

        # Data values should be rendered
        assert "Required for legal review" in content
        assert "Please provide the executed MSA" in content


# ===========================================================================
# Step F: Executive summary
# ===========================================================================


class TestExecutiveSummary:
    """Tests for the executive summary renderer."""

    def test_executive_summary_risk_signal(self, tmp_path: Path) -> None:
        """deal_risk_score maps to a Go/No-Go signal label."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(severity="P0", title="Critical deal issue"),
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Executive summary section should exist
        assert "id='sec-executive'" in content or "Executive Summary" in content

        # Single P0 → High → Proceed with Caution (softened thresholds, Issue #113)
        assert "Proceed with Caution" in content

    def test_executive_summary_heatmap(self, tmp_path: Path) -> None:
        """Executive summary renders a domain x severity data visualization."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [
                    _make_finding(severity="P0", agent="legal"),
                    _make_finding(severity="P1", agent="finance"),
                    _make_finding(severity="P2", agent="commercial"),
                    _make_finding(severity="P3", agent="producttech"),
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Executive section should contain risk heatmap data
        exec_section = content[content.find("Executive") :] if "Executive" in content else content
        assert "Legal" in exec_section
        assert "Finance" in exec_section


# ===========================================================================
# Step G: Report diff
# ===========================================================================


class TestDiffRenderer:
    """Tests for the report diff renderer."""

    def test_diff_renderer_new_findings(self, tmp_path: Path) -> None:
        """New findings from report_diff.json are rendered in a diff section."""
        # Create report_diff.json in a simulated run_dir
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)

        diff_data = {
            "current_run_id": "run_002",
            "prior_run_id": "run_001",
            "summary": {"new_findings": 2, "resolved_findings": 1, "changed_severity": 0},
            "changes": [
                {
                    "change_type": "new_finding",
                    "subject": "Subject A",
                    "finding_summary": "New compliance issue found",
                },
                {
                    "change_type": "new_finding",
                    "subject": "Subject B",
                    "finding_summary": "New IP risk identified",
                },
                {
                    "change_type": "resolved_finding",
                    "subject": "Subject A",
                    "finding_summary": "Prior revenue issue resolved",
                },
            ],
        }
        (report_dir / "report_diff.json").write_text(json.dumps(diff_data))

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            {"c1": {"subject": "C1", "findings": [], "gaps": []}},
            out,
            run_dir=run_dir,
        )

        content = out.read_text(encoding="utf-8")

        # Diff section should render
        assert "Run-over-Run" in content or "Changes" in content or "Diff" in content
        assert "New compliance issue found" in content
        assert "New IP risk identified" in content
        assert "Prior revenue issue resolved" in content

    def test_diff_renderer_no_diff(self, tmp_path: Path) -> None:
        """When no diff data exists, the diff section is gracefully skipped."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            {"c1": {"subject": "C1", "findings": [], "gaps": []}},
            out,
        )

        content = out.read_text(encoding="utf-8")

        # No diff section when no diff data
        assert "Run-over-Run" not in content


# ===========================================================================
# Step H: Quality audit checks
# ===========================================================================


class TestQualityAuditChecks:
    """Tests for audit.json check rendering."""

    def test_quality_audit_checks(self, tmp_path: Path) -> None:
        """Audit checks from audit.json are rendered with pass/fail status."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)

        audit_data = {
            "checks": [
                {"name": "All findings have citations", "status": "pass", "detail": "100% citation coverage"},
                {"name": "No duplicate finding IDs", "status": "pass", "detail": "All IDs unique"},
                {"name": "Cross-ref match rate above 80%", "status": "fail", "detail": "Match rate: 65%"},
            ],
        }
        (report_dir / "audit.json").write_text(json.dumps(audit_data))

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            {"c1": {"subject": "C1", "findings": [], "gaps": []}},
            out,
            run_metadata={"quality_scores": {"agent_scores": {"legal": {"score": 90, "details": "Good"}}}},
            run_dir=run_dir,
        )

        content = out.read_text(encoding="utf-8")

        # Audit check names rendered
        assert "All findings have citations" in content
        assert "No duplicate finding IDs" in content
        assert "Cross-ref match rate above 80%" in content

        # Pass/fail indicators
        assert "pass" in content.lower()
        assert "fail" in content.lower()
        assert "Match rate: 65%" in content


# ===========================================================================
# Step C: Terminology
# ===========================================================================


class TestTerminology:
    """Tests for Subject -> Entity terminology change."""

    def test_terminology_entity_not_customer(self, tmp_path: Path) -> None:
        """Report uses 'Entity' instead of 'Subject' in section headers and metric labels."""
        merged: dict[str, Any] = {
            "cust_a": {
                "subject": "Subject A",
                "findings": [_make_finding()],
                "gaps": [_make_gap()],
                "governance_resolution_pct": 85.0,
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Metric card should say "Entities" not "Customers"
        assert "Entities" in content
        # The section heading should say "Entity Detail" not "Subject Detail"
        assert "Entity Detail" in content

        # "Subject" label in metric cards and navigation should be gone
        # (but actual subject names like "Subject A" remain in data)
        # Check the nav bar
        assert "href='#sec-subjects'" not in content or "Entities" in content

        # Finding card meta should say "Source:" not "Subject:"
        # Check for the specific meta label
        assert "Source:" in content


# ===========================================================================
# Category normalization — all domains & edge cases
# ===========================================================================


class TestCategoryNormalizationExtended:
    """Extended tests for _normalize_category covering all domains and edge cases."""

    def test_keyword_overlap_longest_match_wins(self) -> None:
        """When 'revenue' and 'revenue_concentrat' both match, the longer keyword wins."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        # "revenue_concentration" contains both "revenue" (len 7) and "concentrat" (len 10)
        # "concentrat" is longer, so Concentration Risk should win
        result = _normalize_category("revenue_concentration", "finance")
        assert result == "Concentration Risk"

    def test_keyword_overlap_renewal_risk(self) -> None:
        """'renewal_risk' should match 'renewal_risk' not just 'renewal'."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        result = _normalize_category("renewal_risk", "commercial")
        assert result == "Contract Portfolio"

    def test_normalize_finance_domain(self) -> None:
        """Finance domain categories are normalized correctly."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("cash_flow_issues", "finance") == "Cash Flow & Liquidity"
        assert _normalize_category("tax_compliance", "finance") == "Tax"
        assert _normalize_category("ebitda_margin_decline", "finance") == "Profitability & Margins"

    def test_normalize_commercial_domain(self) -> None:
        """Commercial domain categories are normalized correctly."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("customer_concentration_risk", "commercial") == "Customer Concentration"
        assert _normalize_category("market_positioning", "commercial") == "Market Position"
        assert _normalize_category("pipeline_weakness", "commercial") == "Sales Pipeline"

    def test_normalize_producttech_domain(self) -> None:
        """ProductTech domain categories are normalized correctly."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("technical_debt_issues", "producttech") == "Technical Debt"
        assert _normalize_category("security_vulnerability", "producttech") == "Security"
        assert _normalize_category("architecture_scalability", "producttech") == "Architecture & Scalability"

    def test_normalize_unknown_domain_passthrough(self) -> None:
        """Unknown domain returns the category unchanged."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("some_category", "unknown_domain") == "some_category"

    def test_normalize_empty_category(self) -> None:
        """Empty category string is returned unchanged."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("", "legal") == ""

    def test_normalize_case_insensitive(self) -> None:
        """Normalization is case-insensitive."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("CHANGE_OF_CONTROL", "legal") == "Change of Control"
        assert _normalize_category("Change_Of_Control", "legal") == "Change of Control"

    def test_normalize_spaces_converted(self) -> None:
        """Spaces in input are converted to underscores for matching."""
        from dd_agents.reporting.computed_metrics import _normalize_category

        assert _normalize_category("change of control", "legal") == "Change of Control"


# ===========================================================================
# Wolf pack extended tests
# ===========================================================================


class TestWolfPackExtended:
    """Extended tests for wolf_pack_p0 edge cases."""

    def test_wolf_pack_p0_zero_findings(self) -> None:
        """wolf_pack_p0 is empty when there are no P0 findings."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P1"), _make_finding(severity="P2")],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert len(data.wolf_pack_p0) == 0

    def test_wolf_pack_p0_exactly_15(self) -> None:
        """wolf_pack_p0 returns exactly 15 when there are exactly 15 P0 findings."""
        findings = [_make_finding(severity="P0", title=f"Issue {i}") for i in range(15)]
        merged: dict[str, Any] = {"c": {"subject": "C", "findings": findings, "gaps": []}}
        data = ReportDataComputer().compute(merged)
        assert len(data.wolf_pack_p0) == 15

    def test_wolf_pack_p0_excludes_p1(self) -> None:
        """wolf_pack_p0 contains strictly P0, no P1 findings."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [
                    _make_finding(severity="P0", title="Critical"),
                    _make_finding(severity="P1", title="High"),
                    _make_finding(severity="P1", title="Another high"),
                ],
                "gaps": [],
            },
        }
        data = ReportDataComputer().compute(merged)
        assert len(data.wolf_pack_p0) == 1
        for f in data.wolf_pack_p0:
            assert f["severity"] == "P0"


# ===========================================================================
# Dedup edge cases
# ===========================================================================


class TestDedupSimilarFindings:
    """Tests for _dedup_similar_findings edge cases."""

    def test_dedup_empty_input(self) -> None:
        """Empty input returns empty list."""
        from dd_agents.reporting.html_dashboard import _dedup_similar_findings

        assert _dedup_similar_findings([]) == []

    def test_dedup_single_finding(self) -> None:
        """Single finding returns one group with zero similar."""
        from dd_agents.reporting.html_dashboard import _dedup_similar_findings

        findings = [{"title": "Some finding", "severity": "P0"}]
        groups = _dedup_similar_findings(findings)
        assert len(groups) == 1
        assert groups[0][0] == findings[0]
        assert groups[0][1] == []

    def test_dedup_completely_different(self) -> None:
        """Completely different titles produce separate groups."""
        from dd_agents.reporting.html_dashboard import _dedup_similar_findings

        findings = [
            {"title": "Change of control clause found", "severity": "P0"},
            {"title": "IP assignment missing entirely", "severity": "P0"},
            {"title": "Tax nexus compliance failure", "severity": "P0"},
        ]
        groups = _dedup_similar_findings(findings)
        assert len(groups) == 3  # Each is its own group

    def test_dedup_identical_titles(self) -> None:
        """Identical titles are grouped together."""
        from dd_agents.reporting.html_dashboard import _dedup_similar_findings

        findings = [
            {"title": "Exact same title", "severity": "P0"},
            {"title": "Exact same title", "severity": "P0"},
            {"title": "Exact same title", "severity": "P0"},
        ]
        groups = _dedup_similar_findings(findings)
        assert len(groups) == 1
        assert len(groups[0][1]) == 2  # 2 similar to primary

    def test_dedup_empty_titles(self) -> None:
        """Empty titles don't crash; they get grouped as identical (1.0 ratio)."""
        from dd_agents.reporting.html_dashboard import _dedup_similar_findings

        findings = [
            {"title": "", "severity": "P0"},
            {"title": "", "severity": "P0"},
        ]
        groups = _dedup_similar_findings(findings)
        assert len(groups) == 1


# ===========================================================================
# Cross-reference 3-way match status
# ===========================================================================


class TestCrossRef3WayStatus:
    """Tests for the 3-way match status (Yes/No/Unverified)."""

    def test_xref_unverified_status(self, tmp_path: Path) -> None:
        """Cross-references with 'unverified' or 'partial' status show as Unverified."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [
                    {
                        "data_point": "ARR",
                        "contract_value": "100K",
                        "reference_value": "100K",
                        "match_status": "unverified",
                    },
                    {"data_point": "HC", "contract_value": "50", "reference_value": "45", "match_status": "partial"},
                ],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")

        # Should display "Unverified" not "Yes" or "No"
        assert "Unverified" in content
        assert "xref-unverified" in content

    def test_xref_empty_status_not_match(self, tmp_path: Path) -> None:
        """Empty match_status should NOT be treated as a match."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [],
                "gaps": [],
                "cross_references": [
                    {"data_point": "ARR", "match_status": ""},
                ],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")

        # Empty status should show as Unverified, not as Yes
        assert "xref-match" not in content or "xref-unverified" in content


# ===========================================================================
# Executive summary — all risk labels
# ===========================================================================


class TestExecutiveSummaryExtended:
    """Extended tests for all Go/No-Go signal mappings."""

    def test_go_no_go_critical(self, tmp_path: Path) -> None:
        """Critical risk (3+ P0) shows No-Go."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0", title=f"Issue {i}") for i in range(3)],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        assert "No-Go" in out.read_text(encoding="utf-8")

    def test_go_no_go_single_p0_proceed_with_caution(self, tmp_path: Path) -> None:
        """Single P0 (softened) shows Proceed with Caution, not No-Go."""
        merged: dict[str, Any] = {"c": {"subject": "C", "findings": [_make_finding(severity="P0")], "gaps": []}}
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        assert "Proceed with Caution" in out.read_text(encoding="utf-8")

    def test_go_no_go_high(self, tmp_path: Path) -> None:
        """High risk shows Proceed with Caution."""
        findings = [_make_finding(severity="P1") for _ in range(3)]
        merged: dict[str, Any] = {"c": {"subject": "C", "findings": findings, "gaps": []}}
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        assert "Proceed with Caution" in out.read_text(encoding="utf-8")

    def test_go_no_go_medium(self, tmp_path: Path) -> None:
        """Medium risk shows Conditional Go."""
        merged: dict[str, Any] = {"c": {"subject": "C", "findings": [_make_finding(severity="P1")], "gaps": []}}
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        assert "Conditional Go" in out.read_text(encoding="utf-8")

    def test_go_no_go_clean(self, tmp_path: Path) -> None:
        """Clean risk shows Go."""
        merged: dict[str, Any] = {"c": {"subject": "C", "findings": [], "gaps": []}}
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        # Go should appear in executive summary
        assert ">Go<" in content or "Go</div>" in content

    def test_concentration_hhi_thresholds(self) -> None:
        """Concentration risk levels match HHI thresholds."""
        from dd_agents.reporting.computed_metrics import ReportComputedData
        from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer

        # High: HHI > 2500
        data = ReportComputedData(concentration_hhi=3000.0)
        r = ExecutiveSummaryRenderer(data, {})
        html_out = r._render_concentration()
        assert "High" in html_out

        # Moderate: 1500 < HHI <= 2500
        data = ReportComputedData(concentration_hhi=2000.0)
        r = ExecutiveSummaryRenderer(data, {})
        html_out = r._render_concentration()
        assert "Moderate" in html_out

        # Low: HHI <= 1500
        data = ReportComputedData(concentration_hhi=1000.0)
        r = ExecutiveSummaryRenderer(data, {})
        html_out = r._render_concentration()
        assert "Low" in html_out

        # Zero: no section
        data = ReportComputedData(concentration_hhi=0.0)
        r = ExecutiveSummaryRenderer(data, {})
        html_out = r._render_concentration()
        assert html_out == ""


# ===========================================================================
# Diff renderer edge cases
# ===========================================================================


class TestDiffRendererExtended:
    """Extended tests for diff renderer error handling."""

    def test_diff_malformed_json(self, tmp_path: Path) -> None:
        """Malformed report_diff.json is handled gracefully (no crash)."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "report_diff.json").write_text("{invalid json!!")

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        # Should not crash; diff section should be absent
        assert "Run-over-Run" not in content

    def test_diff_missing_summary_keys(self, tmp_path: Path) -> None:
        """Missing summary keys default to 0."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "report_diff.json").write_text(json.dumps({"summary": {}, "changes": []}))

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        assert "Run-over-Run" in content
        assert ">0</div>" in content

    def test_diff_severity_change_table(self, tmp_path: Path) -> None:
        """Severity change table shows Prior and Current columns."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        diff_data = {
            "summary": {"new": 0, "resolved": 0, "changed_severity": 1},
            "changes": [
                {
                    "change_type": "changed_severity",
                    "subject": "C",
                    "finding_summary": "Issue upgraded",
                    "prior_severity": "P2",
                    "current_severity": "P1",
                },
            ],
        }
        (report_dir / "report_diff.json").write_text(json.dumps(diff_data))

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        assert "Severity Changes" in content
        assert "Prior</th>" in content
        assert "Current</th>" in content
        assert "Issue upgraded" in content


# ===========================================================================
# Quality audit checks edge cases
# ===========================================================================


class TestQualityAuditExtended:
    """Extended tests for audit.json error paths."""

    def test_audit_malformed_json(self, tmp_path: Path) -> None:
        """Malformed audit.json is handled gracefully."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "audit.json").write_text("not valid json")

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        assert "QA Audit Checks" not in content  # Section skipped

    def test_audit_empty_checks(self, tmp_path: Path) -> None:
        """Empty checks array returns no audit section."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "audit.json").write_text(json.dumps({"checks": []}))

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        assert "QA Audit Checks" not in content

    def test_audit_non_standard_status(self, tmp_path: Path) -> None:
        """Non-pass/fail status gets vb-unchecked class."""
        run_dir = tmp_path / "run_dir"
        report_dir = run_dir / "report"
        report_dir.mkdir(parents=True)
        (report_dir / "audit.json").write_text(
            json.dumps({"checks": [{"name": "Test check", "status": "warn", "detail": "Warning"}]})
        )

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({"c": {"subject": "C", "findings": [], "gaps": []}}, out, run_dir=run_dir)
        content = out.read_text(encoding="utf-8")
        assert "vb-unchecked" in content


# ===========================================================================
# Focus area normalization
# ===========================================================================


class TestFocusAreaNormalization:
    """Tests for _normalize_for_match in html_strategy.py."""

    def test_normalize_ampersand_removal(self) -> None:
        """Ampersands are stripped for matching."""
        from dd_agents.reporting.html_strategy import _normalize_for_match

        assert _normalize_for_match("IP & Ownership") == "ip_ownership"
        assert _normalize_for_match("Termination & Exit") == "termination_exit"

    def test_normalize_spaces_to_underscores(self) -> None:
        """Spaces are converted to underscores."""
        from dd_agents.reporting.html_strategy import _normalize_for_match

        assert _normalize_for_match("Change of Control") == "change_of_control"
        assert _normalize_for_match("Revenue Recognition") == "revenue_recognition"

    def test_normalize_double_underscores_collapsed(self) -> None:
        """Double underscores from ampersand removal are collapsed."""
        from dd_agents.reporting.html_strategy import _normalize_for_match

        # "IP & Ownership" → "ip___ownership" → "ip_ownership"
        result = _normalize_for_match("IP & Ownership")
        assert "__" not in result

    def test_normalize_leading_trailing_stripped(self) -> None:
        """Leading/trailing underscores are stripped."""
        from dd_agents.reporting.html_strategy import _normalize_for_match

        assert _normalize_for_match("_test_") == "test"
        assert _normalize_for_match("& test") == "test"

    def test_focus_area_matching_with_canonical_ip(self, tmp_path: Path) -> None:
        """Focus area 'ip_ownership' matches canonical category 'IP & Ownership'."""
        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0", agent="legal", category="ip_assignment_and_ownership")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out, deal_config={"buyer_strategy": {"focus_areas": ["ip_ownership"]}})
        content = out.read_text(encoding="utf-8")
        assert "Findings in Buyer Focus Areas" in content


# ===========================================================================
# Nav bar completeness
# ===========================================================================


class TestNavBarCompleteness:
    """Tests for navigation bar section links."""

    def test_nav_bar_has_executive_link(self, tmp_path: Path) -> None:
        """Nav bar includes link to Executive Summary section."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)
        content = out.read_text(encoding="utf-8")
        assert "href='#sec-executive'" in content

    def test_nav_bar_has_reconciliation_link(self, tmp_path: Path) -> None:
        """Nav bar includes link to Data Reconciliation section."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)
        content = out.read_text(encoding="utf-8")
        assert "href='#sec-xref'" in content

    def test_nav_bar_has_risk_link(self, tmp_path: Path) -> None:
        """Nav bar includes link to Risk section."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)
        content = out.read_text(encoding="utf-8")
        assert "href='#sec-heatmap'" in content
