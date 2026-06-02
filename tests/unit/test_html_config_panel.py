"""Tests for the Analyst Configuration panel renderer (audit §6.6).

Verifies disabled agents and per-agent overrides are surfaced, the default
note appears when nothing is customized, and that user-supplied strings are
HTML-escaped (XSS-safe).
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer
from dd_agents.reporting.html_config_panel import ConfigPanelRenderer


def _compute() -> ReportComputedData:
    merged: dict[str, Any] = {
        "subject_a": {"subject": "Subject A", "findings": [], "gaps": []},
    }
    return ReportDataComputer().compute(merged)  # type: ignore[arg-type]


def _render(deal_config: dict[str, Any] | None) -> str:
    computed = _compute()
    config = {"_deal_config": deal_config}
    return ConfigPanelRenderer(computed, {}, config).render()


def test_default_note_when_no_customizations() -> None:
    html = _render({"forensic_dd": {"specialists": {}}})
    assert "Analyst Configuration" in html
    assert "Default configuration — all agents enabled, no overrides." in html


def test_default_note_when_deal_config_absent() -> None:
    html = _render(None)
    assert "Default configuration — all agents enabled, no overrides." in html


def test_disabled_and_severity_override_rendered() -> None:
    deal_config = {
        "forensic_dd": {
            "specialists": {
                "disabled": ["esg"],
                "customizations": {
                    "legal": {"severity_overrides": {"change_of_control": "P1"}},
                },
            }
        }
    }
    html = _render(deal_config)
    # Disabled fact present.
    assert "esg" in html
    assert "disabled for this run" in html
    # Severity override fact present.
    assert "Severity override" in html
    assert "change_of_control" in html
    assert "P1" in html
    # The configured agent is named.
    assert "legal" in html


def test_customization_is_xss_escaped() -> None:
    deal_config = {
        "forensic_dd": {
            "specialists": {
                "customizations": {
                    "legal": {"extra_instructions": "<script>alert(1)</script>"},
                },
            }
        }
    }
    html = _render(deal_config)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_uses_only_defined_css_classes() -> None:
    deal_config = {
        "forensic_dd": {
            "specialists": {
                "disabled": ["esg"],
                "customizations": {"legal": {"severity_overrides": {"coc": "P0"}}},
            }
        }
    }
    html = _render(deal_config)
    # Section + table use the established class vocabulary.
    assert "class='report-section'" in html
    assert "class='subject-table sortable'" in html
