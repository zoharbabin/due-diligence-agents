"""Unit tests for severity rubric in specialist prompts.

Covers:
- Severity calibration section is included in specialist prompts
- Deal type awareness (acquisition, divestiture)
- Intercompany guidance for acquisitions
- P0 criteria are concrete
- Common false positives guidance
- Deal type variation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from dd_agents.agents.prompt_builder import AgentType, PromptBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer(name: str = "Customer A") -> Any:
    """Build a minimal CustomerEntry-like object."""
    m = MagicMock()
    m.name = name
    m.safe_name = name.lower().replace(" ", "_")
    m.path = f"/data/{m.safe_name}"
    m.files = ["file_1.pdf"]
    m.file_count = 1
    return m


def _make_deal_config(deal_type: str = "acquisition") -> dict[str, Any]:
    """Build a minimal deal_config dict."""
    return {
        "buyer": {"name": "Apex Holdings"},
        "target": {"name": "WidgetCo", "subsidiaries": ["Sub A"]},
        "deal": {"type": deal_type, "focus_areas": ["legal", "finance"]},
    }


def _build_prompt(deal_type: str = "acquisition", agent_name: str = "legal") -> str:
    """Build a specialist prompt with the given deal type."""
    builder = PromptBuilder(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="test_run",
    )
    return builder.build_specialist_prompt(
        agent_name=agent_name,
        customers=[_make_customer()],
        deal_config=_make_deal_config(deal_type),
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestSeverityRubric:
    """Tests for severity rubric in specialist prompts."""

    def test_rubric_included_in_specialist_prompt(self) -> None:
        """Severity calibration section appears in the specialist prompt."""
        prompt = _build_prompt()
        assert "SEVERITY CALIBRATION" in prompt or "Severity Calibration" in prompt

    def test_rubric_mentions_deal_type(self) -> None:
        """Deal type from config appears in the rubric."""
        prompt = _build_prompt(deal_type="acquisition")
        assert "acquisition" in prompt.lower()

    def test_rubric_mentions_intercompany_for_acquisition(self) -> None:
        """Intercompany guidance is present for acquisitions."""
        prompt = _build_prompt(deal_type="acquisition")
        assert "intercompany" in prompt.lower()

    def test_rubric_mentions_p0_criteria(self) -> None:
        """P0 criteria are concrete and present in the rubric."""
        prompt = _build_prompt()
        assert "P0" in prompt
        # Should mention deal-stopper or deal-breaker concept
        assert "deal" in prompt.lower() and ("stopper" in prompt.lower() or "breaker" in prompt.lower())

    def test_rubric_mentions_false_positives(self) -> None:
        """Common false positive guidance is present."""
        prompt = _build_prompt(deal_type="acquisition")
        # Should mention at least one common false positive
        lower = prompt.lower()
        assert any(fp in lower for fp in ["false positive", "commonly over-flagged", "do not flag as p0"])

    def test_rubric_varies_by_deal_type(self) -> None:
        """Acquisition vs divestiture produce different rubric text."""
        acq_prompt = _build_prompt(deal_type="acquisition")
        div_prompt = _build_prompt(deal_type="divestiture")
        # Both should have the rubric
        assert "SEVERITY CALIBRATION" in acq_prompt or "Severity Calibration" in acq_prompt
        assert "SEVERITY CALIBRATION" in div_prompt or "Severity Calibration" in div_prompt
        # But the content should differ (intercompany guidance only for acquisition)
        assert acq_prompt != div_prompt

    def test_rubric_present_for_all_specialists(self) -> None:
        """Every specialist agent type gets the severity rubric."""
        for agent_name in ("legal", "finance", "commercial", "producttech"):
            prompt = _build_prompt(agent_name=agent_name)
            assert "SEVERITY CALIBRATION" in prompt or "Severity Calibration" in prompt, (
                f"Rubric missing for {agent_name}"
            )

    def test_domain_specific_calibration_in_focus(self) -> None:
        """Domain-specific severity calibration appears in SPECIALIST_FOCUS."""
        from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS

        # Each domain should have some severity guidance
        for agent_type in (AgentType.LEGAL, AgentType.FINANCE, AgentType.COMMERCIAL, AgentType.PRODUCTTECH):
            focus = SPECIALIST_FOCUS[agent_type]
            assert "P0" in focus or "P1" in focus or "P2" in focus, (
                f"No severity calibration in SPECIALIST_FOCUS for {agent_type}"
            )

    def test_competitor_only_coc_in_rubric(self) -> None:
        """Competitor-only CoC guidance present in legal severity rubric."""
        from dd_agents.agents.prompt_builder import SPECIALIST_FOCUS

        legal_focus = SPECIALIST_FOCUS[AgentType.LEGAL]
        assert "competitor" in legal_focus.lower()

    def test_tfc_calibration_in_rubric(self) -> None:
        """TfC as valuation concern appears in severity rubric, never as P0."""
        prompt = _build_prompt()
        lower = prompt.lower()
        assert "tfc" in lower or "termination for convenience" in lower
        # TfC should be described as valuation concern
        assert "valuation" in lower or "revenue quality" in lower
        # Verify TfC is explicitly stated as never P0
        assert "never" in lower and "p0" in lower

    def test_specialist_system_prompt_has_calibration(self) -> None:
        """Each specialist system prompt includes severity calibration."""
        from dd_agents.agents.specialists import (
            CommercialAgent,
            FinanceAgent,
            LegalAgent,
            ProductTechAgent,
        )

        for agent_cls in (LegalAgent, FinanceAgent, CommercialAgent, ProductTechAgent):
            agent = agent_cls(
                project_dir=Path("/tmp"),
                run_dir=Path("/tmp"),
                run_id="test",
            )
            sp = agent.get_system_prompt()
            assert "calibrate" in sp.lower() or "P0" in sp, (
                f"No severity calibration in system prompt for {agent_cls.__name__}"
            )
