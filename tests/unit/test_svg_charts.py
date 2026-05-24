"""Unit tests for SVG chart generators (Issue #199).

Covers:
- Donut chart: segments, empty data, full-circle edge case, accessibility
- Heatmap grid: cells, empty state, grid layout
- Waterfall chart: deductions, zero start, accessibility
- Timeline chart: events, single event, empty state
- All charts: role="img", aria-label, <title>, <desc>, viewBox
"""

from __future__ import annotations

from dd_agents.reporting.html_charts import (
    SEVERITY_INDICATORS,
    render_donut_chart,
    render_heatmap_grid,
    render_timeline_chart,
    render_waterfall_chart,
)
from dd_agents.utils.constants import SEVERITY_P0


class TestDonutChart:
    """Tests for render_donut_chart."""

    def test_basic_donut(self) -> None:
        """Renders SVG with segments."""
        svg = render_donut_chart({"P0": 2, "P1": 3, "P2": 5, "P3": 1})
        assert "<svg" in svg
        assert "viewBox" in svg
        assert "11" in svg  # total count

    def test_empty_segments(self) -> None:
        """All zeros returns empty string."""
        assert render_donut_chart({"P0": 0, "P1": 0, "P2": 0, "P3": 0}) == ""

    def test_single_segment_full_circle(self) -> None:
        """Single non-zero segment renders full circle."""
        svg = render_donut_chart({"P0": 5, "P1": 0, "P2": 0, "P3": 0})
        assert "<svg" in svg
        assert "circle" in svg or "path" in svg

    def test_accessibility_role(self) -> None:
        """SVG has role='img'."""
        svg = render_donut_chart({"P0": 1, "P1": 2})
        assert "role='img'" in svg

    def test_accessibility_aria_label(self) -> None:
        """SVG has aria-label."""
        svg = render_donut_chart({"P0": 1}, title="Test Distribution")
        assert "aria-label='Test Distribution'" in svg

    def test_title_element(self) -> None:
        """SVG contains <title> element."""
        svg = render_donut_chart({"P1": 3})
        assert "<title>" in svg

    def test_desc_element(self) -> None:
        """SVG contains <desc> element with data."""
        svg = render_donut_chart({"P0": 2, "P1": 1})
        assert "<desc>" in svg
        assert "P0=2" in svg

    def test_severity_colors_used(self) -> None:
        """SVG uses severity colors."""
        svg = render_donut_chart({"P0": 1, "P2": 1})
        assert "#dc3545" in svg  # P0 red
        assert "#ffc107" in svg  # P2 yellow

    def test_colorblind_indicators(self) -> None:
        """Legend includes text indicators for colorblind users."""
        svg = render_donut_chart({"P0": 1, "P1": 1, "P2": 1, "P3": 1})
        assert SEVERITY_INDICATORS[SEVERITY_P0] in svg


class TestHeatmapGrid:
    """Tests for render_heatmap_grid."""

    def test_basic_grid(self) -> None:
        """Renders SVG grid cells."""
        cells = [
            {"label": "Legal", "value": "High", "color": "#dc3545"},
            {"label": "Finance", "value": "Low", "color": "#28a745"},
        ]
        svg = render_heatmap_grid(cells)
        assert "<svg" in svg
        assert "Legal" in svg
        assert "Finance" in svg

    def test_empty_cells(self) -> None:
        """No cells returns empty string."""
        assert render_heatmap_grid([]) == ""

    def test_accessibility(self) -> None:
        """SVG has required accessibility attributes."""
        cells = [{"label": "Test", "value": "OK", "color": "#333"}]
        svg = render_heatmap_grid(cells, title="My Heatmap")
        assert "role='img'" in svg
        assert "aria-label='My Heatmap'" in svg
        assert "<title>My Heatmap</title>" in svg

    def test_viewbox_present(self) -> None:
        """SVG has viewBox for responsive scaling."""
        cells = [{"label": "A", "value": "1", "color": "#f00"}]
        svg = render_heatmap_grid(cells)
        assert "viewBox" in svg


class TestWaterfallChart:
    """Tests for render_waterfall_chart."""

    def test_basic_waterfall(self) -> None:
        """Renders waterfall with start and deductions."""
        svg = render_waterfall_chart(
            1000000,
            [{"label": "Legal risk", "amount": 200000}, {"label": "Tech debt", "amount": 100000}],
        )
        assert "<svg" in svg
        assert "1,000,000" in svg
        assert "Legal risk" in svg

    def test_zero_start_returns_empty(self) -> None:
        """Zero start value returns empty string."""
        assert render_waterfall_chart(0, [{"label": "X", "amount": 100}]) == ""

    def test_no_deductions_returns_empty(self) -> None:
        """No deductions returns empty string."""
        assert render_waterfall_chart(1000, []) == ""

    def test_adjusted_value_shown(self) -> None:
        """End bar shows adjusted value after deductions."""
        svg = render_waterfall_chart(
            500000,
            [{"label": "Risk A", "amount": 100000}],
        )
        assert "Adjusted" in svg
        assert "400,000" in svg

    def test_accessibility(self) -> None:
        """SVG has accessibility attributes."""
        svg = render_waterfall_chart(
            100000,
            [{"label": "Ded", "amount": 10000}],
            title="Impact Chart",
        )
        assert "role='img'" in svg
        assert "aria-label='Impact Chart'" in svg
        assert "<title>Impact Chart</title>" in svg


class TestTimelineChart:
    """Tests for render_timeline_chart."""

    def test_basic_timeline(self) -> None:
        """Renders timeline with events."""
        events = [
            {"label": "Contract expiry", "date": "2025-06", "severity": "P1"},
            {"label": "Lease renewal", "date": "2025-09", "severity": "P2"},
        ]
        svg = render_timeline_chart(events)
        assert "<svg" in svg
        assert "Contract expiry" in svg
        assert "2025-06" in svg

    def test_empty_events(self) -> None:
        """No events returns empty string."""
        assert render_timeline_chart([]) == ""

    def test_single_event(self) -> None:
        """Single event still renders."""
        svg = render_timeline_chart([{"label": "Deadline", "date": "2025-01"}])
        assert "<svg" in svg
        assert "Deadline" in svg

    def test_severity_colors(self) -> None:
        """Events use severity colors for dots."""
        events = [{"label": "Critical", "date": "2025-01", "severity": "P0"}]
        svg = render_timeline_chart(events)
        assert "#dc3545" in svg

    def test_accessibility(self) -> None:
        """SVG has accessibility attributes."""
        events = [{"label": "Event", "date": "2025-01"}]
        svg = render_timeline_chart(events, title="Key Dates")
        assert "role='img'" in svg
        assert "aria-label='Key Dates'" in svg
        assert "<desc>" in svg

    def test_more_than_12_events_capped(self) -> None:
        """Only 12 events rendered; viewBox height matches."""
        events = [{"label": f"Event {i}", "date": "2025-01"} for i in range(20)]
        svg = render_timeline_chart(events)
        assert "<desc>Timeline with 12 events</desc>" in svg


class TestXSSPrevention:
    """XSS prevention tests for all chart functions."""

    def test_donut_title_escaped(self) -> None:
        """Title with special chars is escaped in donut chart."""
        svg = render_donut_chart({"P0": 1}, title="It's a <test>")
        assert "<test>" not in svg
        assert "It&#x27;s a &lt;test&gt;" in svg

    def test_heatmap_color_escaped(self) -> None:
        """Malicious color value is escaped in heatmap."""
        cells = [{"label": "X", "value": "1", "color": "#f00' onload='alert(1)"}]
        svg = render_heatmap_grid(cells)
        assert "onload=" not in svg

    def test_heatmap_label_escaped(self) -> None:
        """Script in label is escaped."""
        cells = [{"label": "<script>alert(1)</script>", "value": "1", "color": "#f00"}]
        svg = render_heatmap_grid(cells)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_waterfall_label_escaped(self) -> None:
        """Script in deduction label is escaped."""
        svg = render_waterfall_chart(
            1000000,
            [{"label": "<img onerror=alert(1)>", "amount": 100000}],
        )
        assert "<img onerror=" not in svg
        assert "&lt;img" in svg

    def test_timeline_label_escaped(self) -> None:
        """Script in event label is escaped."""
        events = [{"label": "<script>xss</script>", "date": "2025-01"}]
        svg = render_timeline_chart(events)
        assert "<script>" not in svg
        assert "&lt;script&gt;" in svg

    def test_timeline_title_escaped(self) -> None:
        """Title with quotes is escaped in timeline."""
        events = [{"label": "E", "date": "2025-01"}]
        svg = render_timeline_chart(events, title='Test\'s "chart"')
        assert "Test&#x27;s" in svg

    def test_waterfall_title_escaped(self) -> None:
        """Title is escaped in waterfall."""
        svg = render_waterfall_chart(
            1000,
            [{"label": "D", "amount": 100}],
            title="<b>Chart</b>",
        )
        assert "<b>" not in svg
        assert "&lt;b&gt;" in svg


class TestEdgeCases:
    """Edge case tests for chart geometry."""

    def test_waterfall_deduction_exceeds_start(self) -> None:
        """Deduction larger than start value clamps to zero."""
        svg = render_waterfall_chart(
            100000,
            [{"label": "Huge risk", "amount": 200000}],
        )
        assert "Adjusted" in svg
        assert "$0" in svg

    def test_waterfall_zero_amount_deductions_skipped(self) -> None:
        """Deductions with zero amount are excluded."""
        svg = render_waterfall_chart(
            1000,
            [{"label": "Skip", "amount": 0}, {"label": "Keep", "amount": 100}],
        )
        assert "Keep" in svg
        assert "Skip" not in svg
        assert "1 deductions" in svg
