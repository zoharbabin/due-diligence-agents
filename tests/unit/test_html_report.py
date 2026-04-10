"""Unit tests for the HTML report generator.

Covers:
- Empty data rendering
- Single customer with findings
- Severity color coding (P0-P3)
- Citation display with exact_quote
- Self-contained output (no external links)
- HTML escaping of special characters
- File output to specified path
- Gaps table rendering
- Wolf pack (deal-breaker) rendering
- Domain heatmap (4 domains)
- Category grouping within domains
- Cross-reference mismatch highlighting
- Gap analysis section
- Governance metrics bars
- Search/filter DOM elements
- Backwards compatibility (old call signature)
- Graceful degradation (no run_metadata, no deal_config)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
) -> dict[str, str]:
    """Build a minimal gap dict for HTML rendering."""
    return {
        "priority": priority,
        "gap_type": gap_type,
        "missing_item": missing_item,
        "risk_if_missing": risk_if_missing,
    }


def _make_merged_data_rich() -> dict[str, object]:
    """Build a rich merged_data dict that exercises most report features."""
    return {
        "customer_a": {
            "subject": "Customer A",
            "findings": [
                _make_finding(
                    severity="P0",
                    title="Change of control terminates contract",
                    agent="legal",
                    category="change_of_control_clauses",
                    citations=[
                        {
                            "source_path": "file_1.pdf",
                            "location": "Section 12",
                            "exact_quote": "Upon change of control, this agreement shall terminate.",
                        }
                    ],
                ),
                _make_finding(
                    severity="P1",
                    title="Revenue recognition mismatch",
                    agent="finance",
                    category="revenue_recognition",
                ),
                _make_finding(
                    severity="P2",
                    title="Customer concentration risk",
                    agent="commercial",
                    category="customer_concentration",
                ),
                _make_finding(
                    severity="P3",
                    title="Minor code style issues",
                    agent="producttech",
                    category="technical_debt",
                ),
            ],
            "gaps": [
                _make_gap(priority="P0", missing_item="NDA"),
                _make_gap(priority="P2", gap_type="Stale_Doc", missing_item="SOW"),
            ],
            "governance_resolution_pct": 85.5,
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "100000",
                    "reference_value": "100000",
                    "match_status": "match",
                },
                {
                    "data_point": "Employee Count",
                    "contract_value": "50",
                    "reference_value": "45",
                    "match_status": "mismatch",
                },
            ],
        },
        "customer_b": {
            "subject": "Customer B",
            "findings": [
                _make_finding(
                    severity="P1",
                    title="IP assignment clause missing",
                    agent="legal",
                    category="ip_ownership",
                ),
            ],
            "gaps": [],
            "governance_resolution_pct": 95.0,
        },
    }


# ===========================================================================
# Test class
# ===========================================================================


class TestHTMLReportGenerator:
    """Tests for HTMLReportGenerator."""

    def test_empty_data_generates_valid_html(self, tmp_path: Path) -> None:
        """An empty merged_data dict produces valid HTML with 0 customers and 0 findings."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out, title="Empty Report")

        content = out.read_text(encoding="utf-8")

        # Valid HTML structure
        assert "<!DOCTYPE html>" in content
        assert "<html lang='en'>" in content
        assert "</html>" in content
        assert "<title>Empty Report</title>" in content

        # Dashboard shows zero counts
        assert ">0</div>" in content  # At least one stat card with value 0

    def test_single_subject_with_findings(self, tmp_path: Path) -> None:
        """Subject name appears in output; finding title and description are rendered."""
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": [
                    _make_finding(
                        severity="P1",
                        title="Change of control clause",
                        description="Termination on acquisition",
                    ),
                ],
                "gaps": [],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "Customer A" in content
        assert "Change of control clause" in content
        assert "Termination on acquisition" in content
        # Dashboard should show 1 customer and 1 finding
        assert ">1</div>" in content

    def test_severity_colors(self, tmp_path: Path) -> None:
        """Each severity level gets the correct color code (updated palette)."""
        findings = [
            _make_finding(severity="P0", title="P0 finding"),
            _make_finding(severity="P1", title="P1 finding"),
            _make_finding(severity="P2", title="P2 finding"),
            _make_finding(severity="P3", title="P3 finding"),
        ]
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": findings,
                "gaps": [],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "#dc3545" in content  # P0
        assert "#fd7e14" in content  # P1
        assert "#ffc107" in content  # P2
        assert "#6c757d" in content  # P3

    def test_citation_display(self, tmp_path: Path) -> None:
        """Citation exact_quote is rendered in the output."""
        citation = {
            "source_path": "file_1.pdf",
            "location": "Section 5, page 12",
            "exact_quote": "The contract shall terminate upon change of control.",
        }
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": [
                    _make_finding(
                        title="CoC clause",
                        citations=[citation],
                    ),
                ],
                "gaps": [],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "file_1.pdf" in content
        assert "The contract shall terminate upon change of control." in content
        assert "class='quote'" in content or "class=&" in content  # quote class present

    def test_self_contained_no_external_links(self, tmp_path: Path) -> None:
        """The output must not reference external resources via http/https src= or href=."""
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": [_make_finding()],
                "gaps": [_make_gap()],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # No external resource references
        assert 'src="http' not in content
        assert "src='http" not in content
        assert 'href="http' not in content
        assert "href='http" not in content
        # Also check without quotes (just in case)
        assert "src=http" not in content

    def test_html_escaping(self, tmp_path: Path) -> None:
        """Special characters in customer names and titles are HTML-escaped."""
        merged = {
            "customer_a": {
                "subject": '<script>alert("XSS")</script> & "Customer A"',
                "findings": [
                    _make_finding(
                        title='Finding with <b>bold</b> & "quotes"',
                        description="Description with <img src=x> tag",
                    ),
                ],
                "gaps": [],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Raw HTML tags must NOT appear unescaped
        assert '<script>alert("XSS")</script>' not in content
        assert "<b>bold</b>" not in content
        assert "<img src=x>" not in content

        # Escaped versions of finding title/description should be present
        assert "&amp;" in content  # from finding title '& "quotes"'
        assert "&lt;b&gt;" in content  # from finding title '<b>bold</b>'
        # Subject name resolved from SSN ("customer_a" → "Customer A") — XSS string
        # never enters the output, which is stronger than escaping.
        assert "Customer A" in content

    def test_file_output(self, tmp_path: Path) -> None:
        """The generator writes to the specified output path, creating parent dirs."""
        gen = HTMLReportGenerator()
        out = tmp_path / "sub" / "dir" / "report.html"

        # Parent directories do not exist yet
        assert not out.parent.exists()

        gen.generate({}, out, run_id="run_001", title="Test Report")

        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Test Report" in content
        assert "run_001" in content

    def test_gaps_table(self, tmp_path: Path) -> None:
        """Gap data is rendered in a table with priority, type, missing_item, and risk columns."""
        gaps = [
            _make_gap(priority="P0", gap_type="Missing_Doc", missing_item="NDA", risk_if_missing="Legal exposure"),
            _make_gap(priority="P2", gap_type="Stale_Doc", missing_item="SOW", risk_if_missing="Outdated terms"),
        ]
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": [],
                "gaps": gaps,
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Table structure (th elements have scope='col' for WCAG)
        assert "Priority</th>" in content
        assert "Type</th>" in content
        assert "Missing Item</th>" in content
        assert "Risk</th>" in content

        # Gap data in rows
        assert "P0" in content
        assert "Missing_Doc" in content
        assert "NDA" in content
        assert "Legal exposure" in content
        assert "P2" in content
        assert "Stale_Doc" in content
        assert "SOW" in content
        assert "Outdated terms" in content

        # The table should be sortable
        assert "class='sortable'" in content

        # Dashboard should show gap count of 2
        assert ">2</div>" in content

    # -----------------------------------------------------------------------
    # New tests for executive report features
    # -----------------------------------------------------------------------

    def test_wolf_pack_rendering(self, tmp_path: Path) -> None:
        """P0 findings appear as wolf-cards; P1 appear in key-risks summary table."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Wolf pack section exists
        assert "id='sec-wolf-pack'" in content
        assert "Deal Breakers" in content

        # P0 finding present in wolf pack as wolf-card
        assert "Change of control terminates contract" in content
        assert "wolf-card" in content

        # P1 findings present in key-risks summary table (not as wolf-cards)
        assert "Revenue recognition mismatch" in content
        assert "IP assignment clause missing" in content
        assert "key-risks-table" in content

        # Wolf-cards are only P0 (P1 moved to summary table)
        assert content.count("class='wolf-card'") == 1

    def test_domain_heatmap_shows_four_domains(self, tmp_path: Path) -> None:
        """The heatmap grid shows all 4 domains (Legal, Finance, Commercial, Product & Tech)."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "id='sec-heatmap'" in content
        assert "Domain Risk Heatmap" in content
        assert "heatmap-cell" in content

        # All 4 domains present
        assert "Legal" in content
        assert "Finance" in content
        assert "Commercial" in content
        assert "Product &amp; Tech" in content

        # There should be 4 heatmap cells
        assert content.count("class='heatmap-cell'") == 4

    def test_category_grouping_within_domains(self, tmp_path: Path) -> None:
        """Findings are grouped by category within each domain section."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Domain sections exist
        assert "id='sec-domain-legal'" in content
        assert "id='sec-domain-finance'" in content
        assert "id='sec-domain-commercial'" in content
        assert "id='sec-domain-producttech'" in content

        # Category groups are rendered (canonical category names after normalization)
        assert "category-group" in content
        assert "Change of Control" in content
        assert "Revenue Recognition" in content
        assert "Customer Concentration" in content
        assert "Technical Debt" in content

    def test_cross_reference_mismatch_highlighting(self, tmp_path: Path) -> None:
        """Cross-reference mismatches are highlighted with xref-mismatch class."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Cross-reference table exists in customer section
        assert "Cross-Reference Reconciliation" in content

        # Mismatch row highlighted
        assert "xref-mismatch" in content
        # Match row has different class
        assert "xref-match" in content

        # The mismatched field data is present
        assert "Employee Count" in content
        assert ">50<" in content or "50</td>" in content
        assert ">45<" in content or "45</td>" in content

    def test_gap_analysis_section(self, tmp_path: Path) -> None:
        """Gap analysis section shows priority distribution and sortable table."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "id='sec-gaps'" in content
        assert "Missing or Incomplete Data" in content

        # Priority distribution rendered
        assert "By Priority" in content
        assert "By Type" in content

        # Sortable table with entity column (scope='col' for WCAG)
        assert "Entity</th>" in content

    def test_governance_metrics_bars(self, tmp_path: Path) -> None:
        """Governance resolution section shows per-customer progress bars."""
        merged = _make_merged_data_rich()
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "id='sec-governance'" in content
        assert "Governance Resolution" in content
        assert "gov-bar" in content

        # Customer A at 85.5% (yellow zone)
        assert "86%" in content or "85%" in content  # Rounded

        # Customer B at 95% (green zone)
        assert "95%" in content

    def test_backwards_compatibility_old_signature(self, tmp_path: Path) -> None:
        """Calling generate() with only the original params still works (no run_metadata/deal_config)."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"

        # Old-style call without run_metadata or deal_config
        gen.generate(
            {"customer_a": {"subject": "Customer A", "findings": [_make_finding()], "gaps": []}},
            out,
            run_id="run_old",
            title="Legacy Report",
        )

        content = out.read_text(encoding="utf-8")
        assert "Legacy Report" in content
        assert "run_old" in content
        assert "Customer A" in content
        # Wolf pack section exists even without P0/P1
        assert "Deal Breakers" in content
        assert "No P0 or P1 findings" in content

    def test_graceful_degradation_no_metadata(self, tmp_path: Path) -> None:
        """Report generates cleanly when run_metadata and deal_config are None."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            _make_merged_data_rich(),  # type: ignore[arg-type]
            out,
            run_metadata=None,
            deal_config=None,
        )

        content = out.read_text(encoding="utf-8")

        # Report is valid HTML
        assert "<!DOCTYPE html>" in content
        assert "</html>" in content

        # All major sections rendered
        assert "Deal Breakers" in content
        assert "Domain Risk Heatmap" in content
        assert "Missing or Incomplete Data" in content
        assert "Governance Resolution" in content

        # No quality section body when no metadata (sidebar nav link is always present)
        assert "id='sec-quality'" not in content

    def test_deal_header_with_config(self, tmp_path: Path) -> None:
        """Deal header shows buyer, target, and deal type from deal_config."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        deal_config = {
            "buyer": {"name": "Apex Holdings"},
            "target": {"name": "WidgetCo"},
            "deal": {"type": "acquisition"},
        }
        gen.generate(
            {"c1": {"subject": "C1", "findings": [], "gaps": []}},
            out,
            deal_config=deal_config,
        )

        content = out.read_text(encoding="utf-8")
        assert "Apex Holdings" in content
        assert "WidgetCo" in content
        assert "acquisition" in content
        assert "Overall Risk:" in content

    def test_quality_scores_rendered(self, tmp_path: Path) -> None:
        """Quality audit section shows agent scores from run_metadata."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        run_metadata = {
            "quality_scores": {
                "agent_scores": {
                    "legal": {"score": 92, "details": "Strong citations"},
                    "finance": {"score": 88, "details": "Minor gaps"},
                },
            },
        }
        gen.generate(
            {"c1": {"subject": "C1", "findings": [], "gaps": []}},
            out,
            run_metadata=run_metadata,
        )

        content = out.read_text(encoding="utf-8")
        assert "Quality Audit" in content
        assert "92" in content
        assert "Strong citations" in content
        assert "88" in content

    def test_sidebar_navigation(self, tmp_path: Path) -> None:
        """Sidebar navigation with section anchors is rendered."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)

        content = out.read_text(encoding="utf-8")
        assert "class='sidebar'" in content
        assert "href='#sec-heatmap'" in content
        assert "href='#sec-gaps'" in content
        assert "href='#sec-subjects'" in content

    def test_print_mode_css(self, tmp_path: Path) -> None:
        """Print media query is present to expand all sections and hide nav."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)

        content = out.read_text(encoding="utf-8")
        assert "@media print" in content
        assert "display: block !important" in content

    def test_responsive_css(self, tmp_path: Path) -> None:
        """Responsive breakpoints are present for tablet and mobile."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate({}, out)

        content = out.read_text(encoding="utf-8")
        assert "@media (max-width: 900px)" in content
        assert "@media (max-width: 600px)" in content

    def test_wolf_pack_empty_when_no_critical(self, tmp_path: Path) -> None:
        """Wolf pack shows empty message when no P0 or P1 findings exist."""
        merged = {
            "customer_a": {
                "subject": "Customer A",
                "findings": [
                    _make_finding(severity="P2", title="Minor issue"),
                    _make_finding(severity="P3", title="Info only"),
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")
        assert "No P0 or P1 findings" in content

    def test_overall_risk_rating_high_single_p0(self, tmp_path: Path) -> None:
        """Single P0 → High risk (softened from Critical, Issue #113)."""
        merged = {
            "c": {
                "subject": "C",
                "findings": [_make_finding(severity="P0")],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")
        assert "Overall Risk: High" in content

    def test_overall_risk_rating_clean(self, tmp_path: Path) -> None:
        """Overall risk is Clean when no findings at all."""
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(
            {"c": {"subject": "C", "findings": [], "gaps": []}},
            out,
        )

        content = out.read_text(encoding="utf-8")
        assert "Overall Risk: Clean" in content
