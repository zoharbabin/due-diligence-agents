"""Wave 4 — polish items (audit §3.4, §6.9/AD-4)."""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.prompt_builder import PromptBuilder


def _cfg(output_language: str | None = None) -> dict:
    deal: dict = {"type": "acquisition", "focus_areas": ["legal"]}
    if output_language is not None:
        deal["output_language"] = output_language
    return {
        "config_version": "1.0.0",
        "buyer": {"name": "B"},
        "target": {"name": "T"},
        "deal": deal,
    }


def _prompt(output_language: str | None = None) -> str:
    builder = PromptBuilder(project_dir=Path("/tmp/p"), run_dir=Path("/tmp/r"), run_id="t")
    return builder.build_specialist_prompt("legal", ["Subject A"], deal_config=_cfg(output_language))


def test_enrichment_budget_sums_to_one() -> None:
    from dd_agents.knowledge import prompt_enrichment as pe

    total = (
        pe._BUDGET_ENTITY_PROFILES
        + pe._BUDGET_LINEAGE
        + pe._BUDGET_CONTRADICTIONS
        + pe._BUDGET_DOC_RELATIONSHIPS
        + pe._BUDGET_PRIOR_INSIGHTS
    )
    assert abs(total - 1.0) < 1e-9


def test_output_language_default_is_byte_silent() -> None:
    """Default 'en' must not add an output-language line (back-compat)."""
    assert "Output language:" not in _prompt(None)
    assert "Output language:" not in _prompt("en")


def test_output_language_non_default_is_injected() -> None:
    prompt = _prompt("de")
    assert "Output language: write all finding prose in 'de'" in prompt
    assert "quote verbatim in the\n      original language" in prompt or "quote verbatim" in prompt


def test_output_language_config_default() -> None:
    from dd_agents.models.config import DealInfo
    from dd_agents.models.enums import DealType

    info = DealInfo(type=DealType.ACQUISITION, focus_areas=["legal"])
    assert info.output_language == "en"
