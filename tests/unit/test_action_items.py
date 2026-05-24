"""Unit tests for Actionable Recommendations (Issue #200).

Covers:
- Template matching (keyword-based, domain-first)
- De-duplication (one recommendation per pattern_key)
- Timeline grouping (Pre-close, Post-close 30d, Post-close 90d, Long-term)
- Severity prioritization (P0 first)
- Max items limit
- Renderer HTML output (table, disclaimer, metrics strip)
- Empty state handling
- XSS prevention
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.reporting.recommendation_templates import (
    TEMPLATES,
    generate_recommendations,
    match_recommendation,
)


def _make_finding(
    severity: str = "P1",
    title: str = "Test finding",
    description: str = "A test description",
    agent: str = "legal",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "title": title,
        "description": description,
        "agent": agent,
        "category": "uncategorized",
        "citations": [],
        "_subject_safe_name": "test_entity",
    }


class TestTemplateLibrary:
    """Tests for the template library structure."""

    def test_ninety_nine_templates(self) -> None:
        """Library contains exactly 99 templates."""
        assert len(TEMPLATES) == 99

    def test_nine_domains_covered(self) -> None:
        """All 9 specialist domains have templates."""
        domains = {t.domain for t in TEMPLATES}
        expected = {"legal", "finance", "commercial", "producttech", "cybersecurity", "hr", "tax", "regulatory", "esg"}
        assert domains == expected

    def test_templates_have_required_fields(self) -> None:
        """Every template has non-empty required fields."""
        for t in TEMPLATES:
            assert t.pattern_key, f"Empty pattern_key in {t}"
            assert t.domain, f"Empty domain in {t}"
            assert t.keywords, f"Empty keywords in {t}"
            assert t.action, f"Empty action in {t}"
            assert t.owner, f"Empty owner in {t}"
            assert t.timeline, f"Empty timeline in {t}"
            assert t.effort, f"Empty effort in {t}"

    def test_pattern_keys_unique(self) -> None:
        """All pattern_keys are unique."""
        keys = [t.pattern_key for t in TEMPLATES]
        assert len(keys) == len(set(keys))

    def test_valid_timelines(self) -> None:
        """All templates use valid timeline values."""
        valid = {"Pre-close", "Post-close 30d", "Post-close 90d", "Long-term"}
        for t in TEMPLATES:
            assert t.timeline in valid, f"Invalid timeline '{t.timeline}' in {t.pattern_key}"


class TestMatchRecommendation:
    """Tests for match_recommendation function."""

    def test_matches_legal_coc(self) -> None:
        """Finding about change of control matches legal_coc template."""
        finding = _make_finding(title="Change of control restriction in contract", agent="legal")
        rec = match_recommendation(finding)
        assert rec is not None
        assert rec.pattern_key == "legal_coc"
        assert "assignment consent" in rec.action.lower() or "waiver" in rec.action.lower()

    def test_matches_finance_revenue(self) -> None:
        """Finding about revenue recognition matches finance template."""
        finding = _make_finding(title="Revenue recognition policy concerns", agent="finance")
        rec = match_recommendation(finding)
        assert rec is not None
        assert rec.domain == "finance"

    def test_no_match_returns_none(self) -> None:
        """Finding with no keyword match returns None."""
        finding = _make_finding(title="Random unrelated text xyz123", description="Nothing matching")
        rec = match_recommendation(finding)
        assert rec is None

    def test_domain_preference(self) -> None:
        """Same-domain templates preferred over cross-domain matches."""
        finding = _make_finding(title="License compliance concern", agent="producttech")
        rec = match_recommendation(finding)
        assert rec is not None
        assert rec.domain == "producttech"

    def test_matched_recommendation_fields(self) -> None:
        """MatchedRecommendation has all expected fields populated."""
        finding = _make_finding(severity="P0", title="Data breach incident detected", agent="cybersecurity")
        rec = match_recommendation(finding)
        assert rec is not None
        assert rec.finding_title == "Data breach incident detected"
        assert rec.finding_severity == "P0"
        assert rec.entity == "test_entity"
        assert rec.owner != ""
        assert rec.timeline != ""


class TestGenerateRecommendations:
    """Tests for generate_recommendations function."""

    def test_deduplication(self) -> None:
        """Same pattern_key only appears once."""
        findings = [
            _make_finding(title="Change of control clause in contract A", agent="legal"),
            _make_finding(title="Change of control clause in contract B", agent="legal"),
        ]
        recs = generate_recommendations(findings)
        pattern_keys = [r.pattern_key for r in recs]
        assert len(pattern_keys) == len(set(pattern_keys))

    def test_severity_ordering(self) -> None:
        """P0 findings generate recommendations before P2."""
        findings = [
            _make_finding(severity="P2", title="Revenue recognition concern", agent="finance"),
            _make_finding(severity="P0", title="Data breach detected", agent="cybersecurity"),
        ]
        recs = generate_recommendations(findings)
        assert len(recs) >= 2
        assert recs[0].finding_severity == "P0"

    def test_max_items_limit(self) -> None:
        """Respects max_items parameter."""
        findings = [_make_finding(title=f"Issue {i} with change of control", agent="legal") for i in range(50)]
        recs = generate_recommendations(findings, max_items=5)
        assert len(recs) <= 5

    def test_empty_findings(self) -> None:
        """No findings → empty recommendations."""
        assert generate_recommendations([]) == []

    def test_unmatched_findings_skipped(self) -> None:
        """Findings that don't match any template produce no recommendation."""
        findings = [_make_finding(title="xyz unrelated content 12345")]
        recs = generate_recommendations(findings)
        assert len(recs) == 0


class TestActionItemsRenderer:
    """Tests for ActionItemsRenderer HTML output."""

    def test_renders_with_material_findings(self, tmp_path: Path) -> None:
        """Report with material findings renders action items section."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    {
                        "severity": "P0",
                        "title": "Change of control triggers termination",
                        "description": "CoC clause allows counterparty exit",
                        "agent": "legal",
                        "category": "contract_risk",
                        "citations": [],
                    },
                    {
                        "severity": "P1",
                        "title": "Revenue recognition policy irregular",
                        "description": "Deferred revenue not properly recognized",
                        "agent": "finance",
                        "category": "revenue_quality",
                        "citations": [],
                    },
                ],
                "gaps": [],
            },
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "sec-action-items" in content
        assert "Action Items" in content
        assert "Advisory Notice" in content

    def test_disclaimer_present(self, tmp_path: Path) -> None:
        """Report includes advisory disclaimer."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    {
                        "severity": "P0",
                        "title": "IP assignment gap detected",
                        "description": "Missing IP assignment from contractors",
                        "agent": "legal",
                        "category": "ip",
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
        assert "do not constitute legal" in content

    def test_empty_no_section(self, tmp_path: Path) -> None:
        """No material findings → no action items section."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {"subject": "a", "findings": [], "gaps": []},
        }
        gen = HTMLReportGenerator()
        out = tmp_path / "report.html"
        gen.generate(merged, out)
        content = out.read_text(encoding="utf-8")
        assert "<section id='sec-action-items'" not in content

    def test_xss_in_finding_title_escaped(self, tmp_path: Path) -> None:
        """XSS payloads in finding titles are escaped in action items output."""
        from dd_agents.reporting.html import HTMLReportGenerator

        merged: dict[str, Any] = {
            "a": {
                "subject": "a",
                "findings": [
                    {
                        "severity": "P0",
                        "title": "<script>alert('xss')</script> change of control",
                        "description": "CoC clause",
                        "agent": "legal",
                        "category": "contract_risk",
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
        assert "<script>alert" not in content
        assert "&lt;script&gt;" in content


class TestMatchRecommendationEdgeCases:
    """Edge case tests for match_recommendation."""

    def test_none_finding_returns_none(self) -> None:
        """None input does not crash."""
        assert match_recommendation(None) is None

    def test_empty_dict_returns_none(self) -> None:
        """Empty dict finding returns None (no keywords match)."""
        assert match_recommendation({}) is None

    def test_same_domain_wins_tie(self) -> None:
        """Same-domain template wins over cross-domain when scores tie."""
        finding: dict[str, Any] = {
            "title": "license compliance issue",
            "description": "",
            "agent": "regulatory",
        }
        rec = match_recommendation(finding)
        assert rec is not None
        assert rec.domain == "regulatory"
