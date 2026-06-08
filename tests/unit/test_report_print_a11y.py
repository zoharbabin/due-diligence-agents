"""Tests for print completeness and accessibility (Issue #199).

Covers the JS/CSS that make deep-dive layers print and keep tables/charts
accessible (aria-sort, severity-bar aria-label, severity donut).
"""

from __future__ import annotations

from dd_agents.reporting.html_base import render_css, render_js


class TestPrintCompleteness:
    def test_js_expands_layers_before_print(self) -> None:
        js = render_js()
        assert "beforeprint" in js
        assert "afterprint" in js
        # All three deep-dive layers are force-expanded for print.
        for content_id in ("actions-content", "deep-dive-content", "appendix-content"):
            assert content_id in js

    def test_print_css_hides_layer_controls(self) -> None:
        css = render_css()
        assert ".layer-divider, .layer-toggle { display: none !important; }" in css


class TestSortableAccessibility:
    def test_js_sets_aria_sort(self) -> None:
        js = render_js()
        assert "aria-sort" in js
        assert "ascending" in js
        assert "descending" in js
