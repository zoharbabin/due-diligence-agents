#!/usr/bin/env python3
"""Capture the prompt golden-master snapshots used by test_prompt_golden_master.

Run this ONLY when a prompt change is intentional. Re-capturing after an
unintended drift would defeat the gate. After re-capturing, bump
``PromptBuilder.PROMPT_VERSION`` in the same PR so provenance reflects the change.

Usage:
    python scripts/capture_prompt_golden.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import dd_agents.agents.specialists  # noqa: F401 — registers built-in specialists
from dd_agents.agents.acquirer_intelligence import AcquirerIntelligenceAgent
from dd_agents.agents.executive_synthesis import ExecutiveSynthesisAgent
from dd_agents.agents.judge import JudgeAgent
from dd_agents.agents.narrative_generation import NarrativeGenerationAgent
from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.agents.prompt_templates import PROMPT_TEMPLATES
from dd_agents.agents.red_flag_scanner import RedFlagScannerAgent
from dd_agents.agents.registry import AgentRegistry
from dd_agents.persistence.provenance import compute_persona_hashes

_GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "golden"
_DEAL_TYPES = ("acquisition", "asset_sale", "divestiture")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> None:
    base = Path.cwd()

    spec_dir = _GOLDEN / "specialist_prompts"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_manifest: dict[str, str] = {}
    for agent in AgentRegistry.all_specialist_names():
        for deal_type in _DEAL_TYPES:
            builder = PromptBuilder(project_dir=base, run_dir=base, run_id="golden")
            cfg = {
                "config_version": "1.0.0",
                "buyer": {"name": "B"},
                "target": {"name": "T"},
                "deal": {"type": deal_type, "focus_areas": [agent]},
            }
            prompt = builder.build_specialist_prompt(agent, ["Subject A"], deal_config=cfg)
            # Normalize the absolute run dir to a stable token so snapshots are
            # environment-independent (matches test_prompt_golden_master._build).
            prompt = prompt.replace(str(base), "<ROOT>")
            fn = f"{agent}__{deal_type}.txt"
            (spec_dir / fn).write_text(prompt, encoding="utf-8")
            spec_manifest[fn] = _sha(prompt)
    (spec_dir / "_manifest.json").write_text(json.dumps(spec_manifest, indent=2, sort_keys=True) + "\n")

    misc_dir = _GOLDEN / "misc"
    misc_dir.mkdir(parents=True, exist_ok=True)
    misc_manifest: dict[str, str] = {}

    def snap(name: str, text: str) -> None:
        (misc_dir / f"{name}.txt").write_text(text, encoding="utf-8")
        misc_manifest[name] = _sha(text)

    snap("search_templates", json.dumps(PROMPT_TEMPLATES, sort_keys=True, indent=2))
    for cls in (
        JudgeAgent,
        ExecutiveSynthesisAgent,
        RedFlagScannerAgent,
        AcquirerIntelligenceAgent,
        NarrativeGenerationAgent,
    ):
        try:
            inst = cls(project_dir=base, run_dir=base, run_id="golden")  # type: ignore[call-arg]
        except TypeError:
            inst = cls()
        snap(f"sys__{inst.get_agent_name()}", inst.get_system_prompt())
    texts = AgentRegistry.collect_persona_texts(AgentRegistry.all_specialist_names())
    snap("provenance_persona_hashes", json.dumps(compute_persona_hashes(texts), sort_keys=True, indent=2))
    (misc_dir / "_manifest.json").write_text(json.dumps(misc_manifest, indent=2, sort_keys=True) + "\n")

    print(f"captured {len(spec_manifest)} specialist + {len(misc_manifest)} misc snapshots")


if __name__ == "__main__":
    main()
