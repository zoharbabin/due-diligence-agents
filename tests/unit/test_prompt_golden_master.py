"""Golden-master gate for the prompt-to-markdown extraction.

These snapshots were captured from the pre-extraction code (built-in prompt prose
hardcoded in Python). As prompt prose moves into packaged markdown
(``src/dd_agents/agents/prompts/``), the *assembled* output must stay
byte-identical so that:

  * provenance hashes don't change (no checkpoint invalidation),
  * the safety floor still lands last and exactly once,
  * `dd-agents agents preview` output is unchanged.

If a change here is intentional (a deliberate prompt edit), re-capture the
snapshots with ``scripts/capture_prompt_golden.py`` and bump
``PromptBuilder.PROMPT_VERSION`` in the same PR — never silently.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import dd_agents.agents.specialists  # noqa: F401 — registers built-in specialists
from dd_agents.agents.registry import AgentRegistry

_GOLDEN = Path(__file__).resolve().parents[1] / "golden"
_SPEC_DIR = _GOLDEN / "specialist_prompts"
_MISC_DIR = _GOLDEN / "misc"
_DEAL_TYPES = ("acquisition", "asset_sale", "divestiture")


def _build(agent: str, deal_type: str) -> str:
    from dd_agents.agents.prompt_builder import PromptBuilder

    base = Path.cwd()
    builder = PromptBuilder(project_dir=base, run_dir=base, run_id="golden")
    cfg = {
        "config_version": "1.0.0",
        "buyer": {"name": "B"},
        "target": {"name": "T"},
        "deal": {"type": deal_type, "focus_areas": [agent]},
    }
    prompt = builder.build_specialist_prompt(agent, ["Subject A"], deal_config=cfg)
    # The assembled prompt embeds the absolute run directory (Path.cwd()); normalize
    # it to a stable token so the snapshot is environment-independent (local vs CI).
    return prompt.replace(str(Path.cwd()), "<ROOT>")


@pytest.mark.parametrize("agent", AgentRegistry.all_specialist_names())
@pytest.mark.parametrize("deal_type", _DEAL_TYPES)
def test_specialist_prompt_byte_identical(agent: str, deal_type: str) -> None:
    snap = _SPEC_DIR / f"{agent}__{deal_type}.txt"
    assert snap.exists(), f"missing golden snapshot {snap.name} — re-capture if this agent is new"
    assert _build(agent, deal_type) == snap.read_text(encoding="utf-8"), (
        f"assembled prompt for {agent}/{deal_type} drifted from golden master. "
        "If intentional, re-capture snapshots and bump PROMPT_VERSION."
    )


def test_provenance_persona_hashes_unchanged() -> None:
    from dd_agents.persistence.provenance import compute_persona_hashes

    expected = json.loads((_MISC_DIR / "provenance_persona_hashes.txt").read_text())
    texts = AgentRegistry.collect_persona_texts(AgentRegistry.all_specialist_names())
    assert compute_persona_hashes(texts) == expected, (
        "persona provenance hashes changed — this would invalidate existing checkpoints. "
        "Extraction must keep get_system_prompt()/safety-floor text byte-identical."
    )


def test_search_templates_unchanged() -> None:
    from dd_agents.agents.prompt_templates import PROMPT_TEMPLATES

    expected = (_MISC_DIR / "search_templates.txt").read_text(encoding="utf-8")
    assert json.dumps(PROMPT_TEMPLATES, sort_keys=True, indent=2) == expected, (
        "search PROMPT_TEMPLATES drifted from golden master."
    )


@pytest.mark.parametrize(
    "agent_name",
    ["judge", "executive_synthesis", "red_flag_scanner", "acquirer_intelligence", "narrative_generation"],
)
def test_synthesis_system_prompt_unchanged(agent_name: str) -> None:
    snap = _MISC_DIR / f"sys__{agent_name}.txt"
    assert snap.exists(), f"missing golden snapshot for {agent_name}"
    from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceAgent
    from dd_agents.agents.executive_synthesis import ExecutiveSynthesisAgent
    from dd_agents.agents.judge import JudgeAgent
    from dd_agents.agents.narrative_generation import NarrativeGenerationAgent
    from dd_agents.agents.red_flag_scanner import RedFlagScannerAgent

    by_name = {
        "judge": JudgeAgent,
        "executive_synthesis": ExecutiveSynthesisAgent,
        "red_flag_scanner": RedFlagScannerAgent,
        "acquirer_intelligence": AcquirerIntelligenceAgent,
        "narrative_generation": NarrativeGenerationAgent,
    }
    base = Path.cwd()
    cls = by_name[agent_name]
    try:
        inst = cls(project_dir=base, run_dir=base, run_id="golden")
    except TypeError:
        inst = cls()
    assert inst.get_system_prompt() == snap.read_text(encoding="utf-8"), (
        f"{agent_name} system prompt drifted from golden master."
    )
