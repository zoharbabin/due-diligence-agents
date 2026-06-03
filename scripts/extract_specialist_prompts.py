#!/usr/bin/env python3
"""One-time extraction: specialist prompt prose (Python) -> editable Markdown.

Generates ``src/dd_agents/agents/prompts/specialists/{agent}.md`` from the CURRENT
Python source, then verifies each generated file round-trips byte-identically
through the new loader. Uses the **sentinel technique** so that exactly the
severity-threshold-derived numbers (and nothing else) become ``{PLACEHOLDER}``:
each constant in ``severity_thresholds`` is monkeypatched to a unique sentinel
integer, the prose is rendered, and the sentinel is replaced with the placeholder.

Run once during the Phase-1 migration. Safe to re-run (idempotent). After this,
the Python literals are deleted and the registry/builder read the markdown.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import dd_agents.agents.severity_thresholds as thr

# Unique, unmistakable sentinel per threshold constant (values that never appear
# naturally in the prose).
_SENTINELS: dict[str, int] = {
    "TFC_REVENUE_PCT": 970001,
    "TFC_NOTICE_DAYS": 970002,
    "ARR_MISMATCH_P1_PCT": 970003,
    "ARR_MISMATCH_P2_PCT": 970004,
    "COC_REVENUE_PCT": 970005,
    "COC_AUTOTERM_REVENUE_PCT": 970006,
}

_AGENTS = [
    "legal",
    "finance",
    "commercial",
    "producttech",
    "cybersecurity",
    "hr",
    "tax",
    "regulatory",
    "esg",
]

_SPEC_DIR = Path(__file__).resolve().parents[1] / "src" / "dd_agents" / "agents" / "prompts" / "specialists"


def _placeholderize(text: str) -> str:
    for name, sentinel in _SENTINELS.items():
        text = text.replace(str(sentinel), "{" + name + "}")
    return text


def _render_with_sentinels() -> dict[str, dict[str, str]]:
    """Render role/focus/domain prose for every agent with thresholds = sentinels."""
    # Patch the constants, then reload every module that interpolated them at import.
    for name, sentinel in _SENTINELS.items():
        setattr(thr, name, sentinel)
    import dd_agents.agents.prompt_constants as pc

    importlib.reload(pc)
    import dd_agents.agents.prompt_builder as pb

    importlib.reload(pb)
    import dd_agents.agents.specialists as sp

    importlib.reload(sp)

    from dd_agents.agents.prompt_constants import SEVERITY_PREAMBLE

    out: dict[str, dict[str, str]] = {}
    for agent in _AGENTS:
        agent_type = sp.AgentType(agent)
        cls = sp.SPECIALIST_CLASSES[agent_type]
        runner = cls(project_dir=Path.cwd(), run_dir=Path.cwd(), run_id="extract")
        system = runner.get_system_prompt()
        # Role = system prompt minus the trailing SEVERITY_PREAMBLE (re-appended in code).
        assert system.endswith(SEVERITY_PREAMBLE), f"{agent}: get_system_prompt no longer ends with SEVERITY_PREAMBLE"
        role = system[: -len(SEVERITY_PREAMBLE)].rstrip()
        focus = pb.SPECIALIST_FOCUS[agent_type]
        domain = cls.domain_robustness()
        out[agent] = {
            "role": _placeholderize(role),
            "focus": _placeholderize(focus),
            "domain": _placeholderize(domain),
        }
    return out


def _write_markdown(rendered: dict[str, dict[str, str]]) -> None:
    _SPEC_DIR.mkdir(parents=True, exist_ok=True)
    for agent, parts in rendered.items():
        body = (
            f"---\nagent: {agent}\n---\n\n"
            f"## Role\n\n{parts['role']}\n\n"
            f"## Specialist Focus\n\n{parts['focus']}\n\n"
            f"## Domain Guidance\n\n{parts['domain']}\n"
        )
        (_SPEC_DIR / f"{agent}.md").write_text(body, encoding="utf-8")


def main() -> None:
    rendered = _render_with_sentinels()
    _write_markdown(rendered)
    print(f"wrote {len(rendered)} specialist markdown files to {_SPEC_DIR}")

    # Verify round-trip: restore real constants, load via the loader, compare to
    # the real Python render (no sentinels).
    importlib.reload(thr)  # restore real threshold values
    import dd_agents.agents.prompt_constants as pc

    importlib.reload(pc)
    import dd_agents.agents.prompt_builder as pb

    importlib.reload(pb)
    import dd_agents.agents.specialists as sp

    importlib.reload(sp)
    from dd_agents.agents.prompt_constants import SEVERITY_PREAMBLE
    from dd_agents.agents.prompts import loader

    loader.load_builtin_specialist.cache_clear()
    loader._read.cache_clear()

    failures = []
    for agent in _AGENTS:
        agent_type = sp.AgentType(agent)
        cls = sp.SPECIALIST_CLASSES[agent_type]
        runner = cls(project_dir=Path.cwd(), run_dir=Path.cwd(), run_id="verify")
        want_role = runner.get_system_prompt()[: -len(SEVERITY_PREAMBLE)].rstrip()
        want_focus = pb.SPECIALIST_FOCUS[agent_type]
        want_domain = cls.domain_robustness()
        got = loader.load_builtin_specialist(agent)
        if got.role != want_role:
            failures.append(f"{agent}.role")
        if got.specialist_focus != want_focus:
            failures.append(f"{agent}.focus")
        if got.domain_guidance != want_domain:
            failures.append(f"{agent}.domain")
    if failures:
        raise SystemExit(f"ROUND-TRIP MISMATCH: {failures}")
    print("round-trip verified byte-identical for all 9 specialists")


if __name__ == "__main__":
    main()
