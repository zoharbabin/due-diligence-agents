"""Tests for narrative generation models and renderer integration."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dd_agents.models.narrative import (
    DealContextNarrative,
    DomainNarrative,
    FindingNarrative,
    NarrativeOutput,
    NarrativeRecommendation,
    OpenQuestion,
)


class TestNarrativeOutput:
    """Test NarrativeOutput model validation and defaults."""

    def test_empty_construction(self) -> None:
        """NarrativeOutput should construct with all defaults."""
        output = NarrativeOutput()
        assert output.deal_context.summary == ""
        assert output.domain_summaries == []
        assert output.finding_narratives == []
        assert output.recommendations == []
        assert output.open_questions == []
        assert output.config_guidance == ""

    def test_full_construction(self) -> None:
        """NarrativeOutput should construct with all fields populated."""
        output = NarrativeOutput(
            deal_context=DealContextNarrative(
                summary="BuyerCo acquiring TargetCo for growth.",
                buyer_thesis_alignment="Findings align with growth thesis concerns.",
            ),
            domain_summaries=[
                DomainNarrative(
                    domain="legal",
                    headline="3 CoC clauses threaten 54% of ARR",
                    narrative="The legal analysis reveals significant change-of-control risk.",
                    open_questions=["Who drafted the original MSA?"],
                ),
            ],
            finding_narratives=[
                FindingNarrative(
                    finding_title="CoC terminates contract",
                    entity="Acme Corp",
                    severity="P0",
                    so_what="This contract auto-terminates on close.",
                    criteria="Standard M&A practice is consent, not auto-terminate.",
                    impact="$2.1M ARR at risk of immediate loss.",
                    recommended_action="Negotiate consent waiver pre-close.",
                ),
            ],
            recommendations=[
                NarrativeRecommendation(
                    action="Negotiate CoC consent waiver with Acme Corp",
                    rationale="$2.1M ARR terminates automatically without consent.",
                    finding_refs=["CoC terminates contract"],
                    owner="M&A Counsel",
                    urgency="pre-close",
                    estimated_effort="2-3 days",
                ),
            ],
            open_questions=[
                OpenQuestion(
                    question="What is the actual ARR for Acme Corp contract?",
                    category="data_gap",
                    related_domains=["finance", "legal"],
                    priority="high",
                ),
            ],
            config_guidance="Add buyer_strategy.thesis to get deal-specific recommendations.",
        )
        assert output.deal_context.summary == "BuyerCo acquiring TargetCo for growth."
        assert len(output.domain_summaries) == 1
        assert output.domain_summaries[0].domain == "legal"
        assert len(output.finding_narratives) == 1
        assert output.finding_narratives[0].severity == "P0"
        assert len(output.recommendations) == 1
        assert output.recommendations[0].urgency == "pre-close"
        assert len(output.open_questions) == 1
        assert output.open_questions[0].category == "data_gap"

    def test_model_validate_from_dict(self) -> None:
        """Should validate from a raw dict (simulating LLM JSON output)."""
        raw: dict[str, Any] = {
            "deal_context": {"summary": "Deal summary here."},
            "domain_summaries": [{"domain": "finance", "headline": "Revenue is concentrated."}],
            "recommendations": [{"action": "Diversify revenue sources", "owner": "CFO"}],
            "open_questions": [{"question": "Is the ARR figure audited?", "category": "needs_auditor"}],
        }
        output = NarrativeOutput.model_validate(raw)
        assert output.deal_context.summary == "Deal summary here."
        assert output.domain_summaries[0].domain == "finance"
        assert output.recommendations[0].owner == "CFO"
        assert output.open_questions[0].category == "needs_auditor"

    def test_partial_output_is_valid(self) -> None:
        """Partial LLM output (missing fields) should validate with defaults."""
        raw: dict[str, Any] = {
            "deal_context": {"summary": "Partial output."},
        }
        output = NarrativeOutput.model_validate(raw)
        assert output.deal_context.summary == "Partial output."
        assert output.domain_summaries == []
        assert output.recommendations == []

    def test_json_schema_generation(self) -> None:
        """Schema should be generated for structured output prompting."""
        schema = NarrativeOutput.model_json_schema()
        assert "properties" in schema
        assert "deal_context" in schema["properties"]
        assert "recommendations" in schema["properties"]
        assert "open_questions" in schema["properties"]

    def test_model_dump_roundtrip(self) -> None:
        """model_dump -> model_validate roundtrip should preserve data."""
        original = NarrativeOutput(
            deal_context=DealContextNarrative(summary="Test."),
            recommendations=[NarrativeRecommendation(action="Do X", owner="Legal")],
        )
        dumped = original.model_dump()
        restored = NarrativeOutput.model_validate(dumped)
        assert restored.deal_context.summary == "Test."
        assert restored.recommendations[0].action == "Do X"


class TestDomainNarrative:
    """Test DomainNarrative model."""

    def test_domain_required(self) -> None:
        """domain field is required."""
        with pytest.raises(ValidationError):
            DomainNarrative()  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        narr = DomainNarrative(domain="legal")
        assert narr.headline == ""
        assert narr.narrative == ""
        assert narr.open_questions == []


class TestFindingNarrative:
    """Test FindingNarrative model."""

    def test_finding_title_required(self) -> None:
        with pytest.raises(ValidationError):
            FindingNarrative()  # type: ignore[call-arg]

    def test_all_fields(self) -> None:
        fn = FindingNarrative(
            finding_title="Test",
            entity="Entity",
            severity="P0",
            so_what="Matters because...",
            criteria="Standard is...",
            impact="$1M at risk",
            recommended_action="Fix it",
        )
        assert fn.finding_title == "Test"
        assert fn.impact == "$1M at risk"


class TestNarrativeRecommendation:
    """Test NarrativeRecommendation model."""

    def test_action_required(self) -> None:
        with pytest.raises(ValidationError):
            NarrativeRecommendation()  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        rec = NarrativeRecommendation(action="Do something")
        assert rec.urgency == "pre-close"
        assert rec.owner == ""
        assert rec.finding_refs == []


class TestOpenQuestion:
    """Test OpenQuestion model."""

    def test_question_required(self) -> None:
        with pytest.raises(ValidationError):
            OpenQuestion()  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        q = OpenQuestion(question="What about X?")
        assert q.category == "data_gap"
        assert q.priority == "medium"
        assert q.related_domains == []


class TestNarrativeAgentPrompt:
    """Test narrative agent prompt building."""

    def test_prompt_includes_schema(self) -> None:
        from dd_agents.agents.narrative_generation import _build_narrative_prompt

        state: dict[str, Any] = {
            "deal_config": {
                "buyer": {"name": "BuyerCo"},
                "target": {"name": "TargetCo"},
                "deal_info": {"type": "acquisition", "focus_areas": ["legal"]},
            },
            "p0_findings": [{"title": "Critical Issue", "entity": "Entity A", "description": "Bad thing."}],
            "p1_findings": [],
            "findings_summary": {
                "total_subjects": 5,
                "total_findings": 10,
                "severity_distribution": {"P0": 1, "P1": 3, "P2": 4, "P3": 2},
            },
        }
        prompt = _build_narrative_prompt(state)
        assert "BuyerCo" in prompt
        assert "TargetCo" in prompt
        assert "Critical Issue" in prompt
        assert "NarrativeOutput" in prompt or "properties" in prompt

    def test_prompt_with_buyer_strategy(self) -> None:
        from dd_agents.agents.narrative_generation import _build_narrative_prompt

        state: dict[str, Any] = {
            "deal_config": {
                "buyer": {"name": "BuyerCo"},
                "target": {"name": "TargetCo"},
                "deal_info": {"type": "acquisition", "focus_areas": ["legal"]},
                "buyer_strategy": {
                    "thesis": "Growth through acquisition",
                    "key_synergies": ["cross-sell"],
                    "risk_tolerance": "moderate",
                },
            },
            "p0_findings": [],
            "p1_findings": [],
            "findings_summary": {"total_subjects": 1, "total_findings": 0, "severity_distribution": {}},
        }
        prompt = _build_narrative_prompt(state)
        assert "Growth through acquisition" in prompt
        assert "cross-sell" in prompt
        assert "moderate" in prompt

    def test_prompt_minimal_config(self) -> None:
        from dd_agents.agents.narrative_generation import _build_narrative_prompt

        state: dict[str, Any] = {
            "deal_config": None,
            "p0_findings": [],
            "p1_findings": [],
            "findings_summary": {},
        }
        prompt = _build_narrative_prompt(state)
        assert "No buyer_strategy" in prompt or "buyer_thesis_alignment empty" in prompt


class TestExecutiveRendererNarrativeIntegration:
    """Test executive renderer uses narrative data."""

    def _make_computed(self, narrative: dict[str, Any] | None = None) -> Any:
        from dd_agents.reporting.computed_metrics import ReportComputedData

        return ReportComputedData(
            total_findings=5,
            total_subjects=2,
            material_count=5,
            material_by_severity={"P0": 1, "P1": 2, "P2": 1, "P3": 1},
            deal_risk_score=65.0,
            deal_risk_label="High",
            domain_severity={"legal": {"P0": 1, "P1": 1, "P2": 0, "P3": 0}},
            domain_risk_labels={"legal": "High"},
            executive_takeaways=[{"text": "Key risk in legal domain", "severity": "critical", "domains": "Legal"}],
            narrative=narrative,
        )

    def test_config_guidance_shows_without_buyer_strategy(self) -> None:
        from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer

        computed = self._make_computed()
        config: dict[str, Any] = {"_deal_config": {"buyer": {"name": "B"}, "target": {"name": "T"}}}
        r = ExecutiveSummaryRenderer(computed, {}, config)
        html = r.render()
        assert "Enhance this report" in html

    def test_config_guidance_hidden_with_buyer_strategy(self) -> None:
        from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer

        computed = self._make_computed()
        config: dict[str, Any] = {
            "_deal_config": {
                "buyer": {"name": "B"},
                "target": {"name": "T"},
                "buyer_strategy": {"thesis": "Growth"},
            }
        }
        r = ExecutiveSummaryRenderer(computed, {}, config)
        html = r.render()
        assert "Enhance this report" not in html

    def test_open_items_rendered_with_narrative(self) -> None:
        from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer

        narrative: dict[str, Any] = {
            "open_questions": [
                {"question": "What is X?", "category": "data_gap", "priority": "high"},
                {"question": "Need counsel on Y", "category": "needs_counsel", "priority": "medium"},
            ]
        }
        computed = self._make_computed(narrative=narrative)
        config: dict[str, Any] = {"_deal_config": {"buyer": {"name": "B"}, "target": {"name": "T"}}}
        r = ExecutiveSummaryRenderer(computed, {}, config)
        html = r.render()
        assert "Open Items" in html
        assert "Needs More Data" in html
        assert "Needs Counsel" in html

    def test_deal_header_rendered(self) -> None:
        from dd_agents.reporting.html_executive import ExecutiveSummaryRenderer

        computed = self._make_computed()
        config: dict[str, Any] = {
            "_deal_config": {
                "buyer": {"name": "Acme Corp"},
                "target": {"name": "Widget Inc"},
                "deal_info": {"type": "acquisition"},
            }
        }
        r = ExecutiveSummaryRenderer(computed, {}, config)
        html = r.render()
        assert "Acme Corp" in html
        assert "Widget Inc" in html
        assert "Acquisition" in html


class TestActionItemsNarrativeIntegration:
    """Test action items renderer prefers narrative recommendations."""

    def _make_computed(self, narrative: dict[str, Any] | None = None) -> Any:
        from dd_agents.reporting.computed_metrics import ReportComputedData

        return ReportComputedData(
            material_findings=[
                {
                    "title": "Test finding",
                    "severity": "P0",
                    "description": "Test",
                    "agent": "legal",
                    "category": "change_of_control",
                }
            ],
            narrative=narrative,
        )

    def test_uses_narrative_when_available(self) -> None:
        from dd_agents.reporting.html_action_items import ActionItemsRenderer

        narrative: dict[str, Any] = {
            "recommendations": [
                {
                    "action": "Negotiate consent waiver",
                    "rationale": "Contract auto-terminates on close",
                    "finding_refs": ["CoC terminates contract"],
                    "owner": "M&A Counsel",
                    "urgency": "pre-close",
                    "estimated_effort": "2-3 days",
                },
            ]
        }
        computed = self._make_computed(narrative=narrative)
        r = ActionItemsRenderer(computed, {})
        html = r.render()
        assert "Negotiate consent waiver" in html
        assert "M&amp;A Counsel" in html
        assert "Contract auto-terminates on close" in html

    def test_falls_back_to_templates_without_narrative(self) -> None:
        from dd_agents.reporting.computed_metrics import ReportComputedData
        from dd_agents.reporting.html_action_items import ActionItemsRenderer

        computed = ReportComputedData(
            material_findings=[
                {
                    "title": "Change of control terminates contract",
                    "severity": "P0",
                    "description": "CoC clause allows termination",
                    "agent": "legal",
                    "category": "change_of_control",
                }
            ],
            narrative=None,
        )
        r = ActionItemsRenderer(computed, {})
        html = r.render()
        # Template-matched recommendations should render
        assert "Action Items" in html
