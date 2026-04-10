"""Tests for per-finding confidence calibration (Issue #143)."""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportComputedData, ReportDataComputer
from dd_agents.reporting.html_gaps import GapRenderer


def _subject(name: str, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "subject": name,
        "findings": findings or [],
        "gaps": [],
        "cross_references": [],
    }


class TestConfidenceDistribution:
    """Tests for confidence distribution in computed metrics."""

    def test_confidence_distribution_all_high(self) -> None:
        merged = {
            "a": _subject(
                "A",
                findings=[
                    {
                        "severity": "P1",
                        "title": "F1",
                        "description": "d",
                        "confidence": "high",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q"}],
                        "agent": "legal",
                    },
                    {
                        "severity": "P2",
                        "title": "F2",
                        "description": "d",
                        "confidence": "high",
                        "citations": [{"source_type": "contract", "source_path": "b.pdf", "exact_quote": "q"}],
                        "agent": "finance",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.confidence_distribution["high"] == 2
        assert result.confidence_distribution["medium"] == 0
        assert result.confidence_distribution["low"] == 0

    def test_confidence_distribution_mixed(self) -> None:
        merged = {
            "a": _subject(
                "A",
                findings=[
                    {
                        "severity": "P1",
                        "title": "F1",
                        "description": "d",
                        "confidence": "high",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q"}],
                        "agent": "legal",
                    },
                    {
                        "severity": "P2",
                        "title": "F2",
                        "description": "d",
                        "confidence": "medium",
                        "citations": [{"source_type": "contract", "source_path": "b.pdf", "exact_quote": "q"}],
                        "agent": "finance",
                    },
                    {
                        "severity": "P3",
                        "title": "F3",
                        "description": "d",
                        "confidence": "low",
                        "citations": [{"source_type": "contract", "source_path": "c.pdf", "exact_quote": "q"}],
                        "agent": "commercial",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.confidence_distribution["high"] == 1
        assert result.confidence_distribution["medium"] == 1
        assert result.confidence_distribution["low"] == 1

    def test_low_confidence_findings_collected(self) -> None:
        merged = {
            "a": _subject(
                "A",
                findings=[
                    {
                        "severity": "P1",
                        "title": "Low conf finding",
                        "description": "d",
                        "confidence": "low",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q"}],
                        "agent": "legal",
                    },
                    {
                        "severity": "P2",
                        "title": "High conf finding",
                        "description": "d",
                        "confidence": "high",
                        "citations": [{"source_type": "contract", "source_path": "b.pdf", "exact_quote": "q"}],
                        "agent": "finance",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.low_confidence_count == 1

    def test_missing_confidence_treated_as_medium(self) -> None:
        merged = {
            "a": _subject(
                "A",
                findings=[
                    {
                        "severity": "P2",
                        "title": "No conf",
                        "description": "d",
                        "citations": [{"source_type": "contract", "source_path": "a.pdf", "exact_quote": "q"}],
                        "agent": "legal",
                    },
                ],
            ),
        }
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.confidence_distribution["medium"] == 1

    def test_empty_findings_zero_distribution(self) -> None:
        merged = {"a": _subject("A")}
        computer = ReportDataComputer()
        result = computer.compute(merged)
        assert result.confidence_distribution == {"high": 0, "medium": 0, "low": 0}
        assert result.low_confidence_count == 0


class TestConfidenceBadgeInCard:
    """Tests for confidence indicator in finding cards."""

    def test_finding_card_has_confidence_dot(self) -> None:
        """Finding cards should show a confidence indicator."""
        computed = ReportComputedData()
        renderer = GapRenderer(computed, {}, {})
        card_html = renderer.render_finding_card(
            {
                "severity": "P1",
                "title": "Test finding",
                "confidence": "high",
                "agent": "legal",
            }
        )
        assert "conf-high" in card_html

    def test_finding_card_low_confidence_flagged(self) -> None:
        computed = ReportComputedData()
        renderer = GapRenderer(computed, {}, {})
        card_html = renderer.render_finding_card(
            {
                "severity": "P1",
                "title": "Uncertain finding",
                "confidence": "low",
                "agent": "legal",
            }
        )
        assert "conf-low" in card_html

    def test_finding_card_missing_confidence(self) -> None:
        """Missing confidence should not crash rendering."""
        computed = ReportComputedData()
        renderer = GapRenderer(computed, {}, {})
        card_html = renderer.render_finding_card(
            {
                "severity": "P2",
                "title": "No confidence field",
                "agent": "legal",
            }
        )
        assert "finding-card" in card_html
