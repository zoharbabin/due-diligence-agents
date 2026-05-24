"""Unit tests for the client-side filter bar (Issue #196).

Covers:
- HTML structure (data-filter-* attributes, aria attributes)
- Severity chips rendered for all severities
- Domain chips rendered for all registered domains
- Counter and clear button present
- JS presence in rendered output
- CSS presence in rendered output
- Print CSS hides filter bar
- Filter bar is progressive enhancement (no JS → content still visible)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.reporting.computed_metrics import ReportComputedData
from dd_agents.reporting.html_base import get_domain_agents, render_css, render_js
from dd_agents.reporting.html_filter_bar import FILTER_BAR_CSS, FILTER_BAR_JS, FilterBarRenderer
from dd_agents.utils.constants import ALL_SEVERITIES


def _make_renderer() -> FilterBarRenderer:
    """Create a FilterBarRenderer with minimal computed data."""
    data = ReportComputedData()
    return FilterBarRenderer(data, {}, {})


class TestFilterBarHTML:
    """Tests for filter bar HTML output."""

    def test_renders_filter_bar_element(self) -> None:
        """Output contains the filter-bar container."""
        html = _make_renderer().render()
        assert "class='filter-bar'" in html

    def test_renders_severity_chips(self) -> None:
        """All severity levels have chip buttons."""
        html = _make_renderer().render()
        for sev in ALL_SEVERITIES:
            assert f"data-filter-severity='{sev}'" in html

    def test_renders_domain_chips(self) -> None:
        """All registered domain agents have chip buttons."""
        html = _make_renderer().render()
        for domain in get_domain_agents():
            assert f"data-filter-domain='{domain}'" in html

    def test_chips_have_aria_pressed(self) -> None:
        """All chips start with aria-pressed='false'."""
        html = _make_renderer().render()
        assert "aria-pressed='false'" in html
        assert "aria-pressed='true'" not in html

    def test_counter_element_present(self) -> None:
        """Filter count span with aria-live is present."""
        html = _make_renderer().render()
        assert "class='filter-count'" in html
        assert "aria-live='polite'" in html

    def test_clear_button_present(self) -> None:
        """Clear button is present and hidden by default."""
        html = _make_renderer().render()
        assert "class='filter-clear hidden'" in html

    def test_toolbar_role(self) -> None:
        """Filter bar has role='toolbar' for accessibility."""
        html = _make_renderer().render()
        assert "role='toolbar'" in html

    def test_aria_label(self) -> None:
        """Filter bar has an aria-label."""
        html = _make_renderer().render()
        assert "aria-label='Finding filters'" in html


class TestFilterBarCSS:
    """Tests for filter bar CSS integration."""

    def test_css_included_in_render_css(self) -> None:
        """render_css() includes filter bar styles."""
        css = render_css()
        assert ".filter-bar" in css
        assert ".filter-chip" in css

    def test_print_hides_filter_bar(self) -> None:
        """Print media query hides the filter bar."""
        assert "display: none !important" in FILTER_BAR_CSS
        assert "@media print" in FILTER_BAR_CSS

    def test_sticky_positioning(self) -> None:
        """Filter bar uses sticky positioning."""
        assert "position: sticky" in FILTER_BAR_CSS

    def test_z_index_below_sidebar(self) -> None:
        """Filter bar z-index is below sidebar (1000) but above content."""
        assert "z-index: 500" in FILTER_BAR_CSS


class TestFilterBarJS:
    """Tests for filter bar JavaScript integration."""

    def test_js_included_in_render_js(self) -> None:
        """render_js() includes filter bar JavaScript."""
        js = render_js()
        assert "applyFilters" in js
        assert "filter-bar" in js

    def test_js_syncs_hash(self) -> None:
        """JS handles URL hash state for shareable filters."""
        assert "syncHash" in FILTER_BAR_JS
        assert "readHash" in FILTER_BAR_JS

    def test_js_uses_aria_pressed(self) -> None:
        """JS toggles aria-pressed on chip buttons."""
        assert "aria-pressed" in FILTER_BAR_JS

    def test_js_progressive_enhancement(self) -> None:
        """JS bails early if filter bar element not found."""
        assert "if (!bar) return" in FILTER_BAR_JS


class TestFilterBarIntegration:
    """Tests for filter bar in full report generation."""

    def test_filter_bar_in_generated_report(self, tmp_path: Path) -> None:
        """Full report contains the filter bar."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "c": {
                "subject": "C",
                "findings": [
                    {
                        "severity": "P0",
                        "title": "Critical issue",
                        "description": "Desc",
                        "agent": "legal",
                        "category": "uncategorized",
                        "citations": [],
                    }
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "class='filter-bar'" in content
        assert "data-filter-severity='P0'" in content
        assert "applyFilters" in content
