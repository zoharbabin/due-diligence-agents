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
    citations: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build a minimal finding dict for HTML rendering."""
    return {
        "severity": severity,
        "title": title,
        "description": description,
        "agent": agent,
        "confidence": confidence,
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

    def test_single_customer_with_findings(self, tmp_path: Path) -> None:
        """Customer name appears in output; finding title and description are rendered."""
        merged = {
            "customer_a": {
                "customer": "Customer A",
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
        """Each severity level gets the correct color code."""
        findings = [
            _make_finding(severity="P0", title="P0 finding"),
            _make_finding(severity="P1", title="P1 finding"),
            _make_finding(severity="P2", title="P2 finding"),
            _make_finding(severity="P3", title="P3 finding"),
        ]
        merged = {
            "customer_a": {
                "customer": "Customer A",
                "findings": findings,
                "gaps": [],
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        assert "#ff4444" in content  # P0
        assert "#ff8800" in content  # P1
        assert "#ffcc00" in content  # P2
        assert "#cccccc" in content  # P3

    def test_citation_display(self, tmp_path: Path) -> None:
        """Citation exact_quote is rendered in the output."""
        citation = {
            "source_path": "file_1.pdf",
            "location": "Section 5, page 12",
            "exact_quote": "The contract shall terminate upon change of control.",
        }
        merged = {
            "customer_a": {
                "customer": "Customer A",
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
        assert "Section 5, page 12" in content
        assert "The contract shall terminate upon change of control." in content
        # The quote should be inside a div with class 'quote'
        assert "class='quote'" in content

    def test_self_contained_no_external_links(self, tmp_path: Path) -> None:
        """The output must not reference external resources via http/https src= or href=."""
        merged = {
            "customer_a": {
                "customer": "Customer A",
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
                "customer": '<script>alert("XSS")</script> & "Customer A"',
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

        # Escaped versions should be present
        assert "&lt;script&gt;" in content
        assert "&amp;" in content
        assert "&lt;b&gt;" in content
        assert "&quot;" in content

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
                "customer": "Customer A",
                "findings": [],
                "gaps": gaps,
            },
        }

        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)

        content = out.read_text(encoding="utf-8")

        # Table structure
        assert "<th>Priority</th>" in content
        assert "<th>Type</th>" in content
        assert "<th>Missing Item</th>" in content
        assert "<th>Risk</th>" in content

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
