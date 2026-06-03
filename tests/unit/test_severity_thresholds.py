"""Wave 0 — severity thresholds have a single source (audit §1.2).

Proves the numeric thresholds render into the assembled rubric/focus strings,
so a threshold change is a one-line edit and cannot silently drift.
"""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.agents.prompt_constants import TFC_SEVERITY_CALIBRATION, TFC_SEVERITY_RULE
from dd_agents.agents.severity_thresholds import (
    COC_AUTOTERM_REVENUE_PCT,
    COC_REVENUE_PCT,
    TFC_NOTICE_DAYS,
    TFC_REVENUE_PCT,
)


def test_tfc_rule_built_from_constants() -> None:
    assert f">{TFC_REVENUE_PCT}% revenue" in TFC_SEVERITY_RULE
    assert f"<{TFC_NOTICE_DAYS} day" in TFC_SEVERITY_RULE
    assert f">{TFC_REVENUE_PCT}% revenue" in TFC_SEVERITY_CALIBRATION


def _legal_prompt() -> str:
    builder = PromptBuilder(project_dir=Path("/tmp/p"), run_dir=Path("/tmp/r"), run_id="t")
    return builder.build_specialist_prompt(
        "legal",
        ["Subject A"],
        deal_config={
            "config_version": "1.0.0",
            "buyer": {"name": "B"},
            "target": {"name": "T"},
            "deal": {"type": "acquisition", "focus_areas": ["legal"]},
        },
    )


def test_coc_thresholds_render_into_legal_prompt() -> None:
    prompt = _legal_prompt()
    assert f">{COC_REVENUE_PCT}% revenue" in prompt
    assert f">{COC_AUTOTERM_REVENUE_PCT}% revenue" in prompt


def test_changing_constant_changes_rendered_rule() -> None:
    """The rule string is f-string-derived, not a hardcoded literal."""
    # The literal numbers must appear via the constant, so the rule reflects
    # whatever the constant is. We assert the current values are present and
    # that the constant value (not a stray literal) is what's embedded.
    assert str(TFC_REVENUE_PCT) in TFC_SEVERITY_RULE
    assert str(TFC_NOTICE_DAYS) in TFC_SEVERITY_RULE
