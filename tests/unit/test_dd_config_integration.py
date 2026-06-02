"""Regression: dd-config/ markdown customizations MUST reach the assembled prompt.

Audit (live E2E) found the loader was unit-tested in isolation but never wired
into ``build_specialist_prompt`` — a valid ``dd-config/agents/legal.md`` validated
clean yet had zero effect on agent behavior. These tests lock the integration so
the documented non-technical workflow stays functional.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.agents.prompt_builder import PromptBuilder, resolve_agent_customization

if TYPE_CHECKING:
    from pathlib import Path

_DEAL_CONFIG = {
    "config_version": "1.0.0",
    "buyer": {"name": "B"},
    "target": {"name": "T"},
    "deal": {"type": "acquisition", "focus_areas": ["legal"]},
}


def _write_dd_config(project_dir: Path) -> None:
    agents_dir = project_dir / "dd-config" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "legal.md").write_text(
        "---\n"
        "agent: legal\n"
        "status: enabled\n"
        "extends: saas\n"
        "---\n\n"
        "## Persona (replaces default)\n"
        "You are NiceCorp's lead M&A counsel focused on change-of-control.\n\n"
        "## Additional Focus Areas\n"
        "- open-source copyleft license exposure\n"
        "- EU data-residency commitments\n\n"
        "## Severity Overrides\n"
        "- change_of_control: P1\n",
        encoding="utf-8",
    )


def _build(project_dir: Path) -> str:
    builder = PromptBuilder(project_dir=project_dir, run_dir=project_dir, run_id="t")
    return builder.build_specialist_prompt("legal", ["Subject A"], deal_config=_DEAL_CONFIG)


def test_dd_config_persona_and_focus_reach_prompt(tmp_path: Path) -> None:
    _write_dd_config(tmp_path)
    prompt = _build(tmp_path)
    assert "NiceCorp's lead M&A counsel" in prompt  # persona override
    assert "open-source copyleft license exposure" in prompt  # custom focus area
    assert "EU data-residency commitments" in prompt
    assert "change_of_control: P1" in prompt  # severity override
    assert "SaaS" in prompt or "subscription" in prompt  # extends: saas profile content


def test_dd_config_customization_precedes_safety_floor(tmp_path: Path) -> None:
    _write_dd_config(tmp_path)
    prompt = _build(tmp_path)
    # Non-removable floor must still land AFTER user customization.
    assert prompt.index("NiceCorp's lead M&A counsel") < prompt.index("UNTRUSTED CONTENT")
    assert "NOT_FOUND" in prompt  # anti-fabrication floor present


def test_no_dd_config_dir_is_backcompat_noop(tmp_path: Path) -> None:
    """Absent dd-config/ → inline-only behavior, no customization injected."""
    prompt = _build(tmp_path)
    assert "PERSONA OVERRIDE" not in prompt
    assert "NiceCorp" not in prompt


def test_resolve_agent_customization_folds_dd_config(tmp_path: Path) -> None:
    _write_dd_config(tmp_path)
    cust = resolve_agent_customization(tmp_path, None, "legal")
    assert cust is not None
    assert cust.persona and "NiceCorp" in cust.persona
    assert "open-source copyleft license exposure" in cust.extra_focus_areas
    assert cust.severity_overrides.get("change_of_control") == "P1"


def test_malformed_dd_config_falls_back_gracefully(tmp_path: Path) -> None:
    """A broken dd-config file must not crash prompt assembly (fail-safe)."""
    agents_dir = tmp_path / "dd-config" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "legal.md").write_text("---\nnot: valid\n---\n## Unknown Heading\nx\n", encoding="utf-8")
    # Should not raise — falls back to inline (None here) and still builds.
    prompt = _build(tmp_path)
    assert "LEGAL SPECIALIST AGENT" in prompt
    assert "NOT_FOUND" in prompt  # floor intact


def test_resolve_falls_back_when_no_project_dir() -> None:
    assert resolve_agent_customization(None, None, "legal") is None


def test_citation_mandate_appears_exactly_once(tmp_path: Path) -> None:
    """Regression: the citation mandate must appear once (floor only), not 3x.

    Previously injected via (a) standalone CITATION EXAMPLES section,
    (b) trailing block in domain_robustness, and (c) the safety floor — the
    floor is now the single authoritative copy.
    """
    builder = PromptBuilder(project_dir=tmp_path, run_dir=tmp_path, run_id="t")
    prompt = builder.build_specialist_prompt("legal", ["Subject A"], deal_config=_DEAL_CONFIG)
    assert prompt.count("MANDATORY Citation Requirements") == 1
    assert prompt.count("Examples of good Legal citations") == 1
    # Domain guidance still present (not collateral-damaged by the dedup).
    assert "LEGAL-SPECIFIC EXTRACTION GUIDANCE" in prompt
    assert "SUBTYPE CLASSIFICATION" in prompt
