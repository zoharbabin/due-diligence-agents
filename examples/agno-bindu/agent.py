"""Atlas DD Analyst — an agno agent that answers questions about a completed
dd-agents due-diligence report.

No server is started here. ``cli.py`` calls ``get_agent()`` for one-shot local
runs; ``bindu_agent.py`` calls it to expose the agent over A2A.

The agent's tools (in ``report_tools.py``) read a deal's *already-produced*
merged findings through the upstream ``dd_agents.query`` finding index — pure,
deterministic Python, no LLM and no Anthropic key. The agno model (via
OpenRouter) supplies the conversational reasoning on top. The dd-agents pipeline
itself is never run here.
"""

from __future__ import annotations

import os
from functools import lru_cache

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from prompts import AGENT_DESCRIPTION, AGENT_NAME, SYSTEM_PROMPT

# Deterministic, key-free report tools (also unit-tested without agno/bindu).
from report_tools import TOOLS, report_path

__all__ = ["build_agent", "get_agent", "report_path"]


def _build_model() -> OpenRouter:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to your .env (see .env.example).")
    return OpenRouter(
        id=os.getenv("BINDU_AGENT_MODEL", "anthropic/claude-sonnet-4.5"),
        api_key=api_key,
        max_tokens=int(os.getenv("BINDU_AGENT_MAX_TOKENS", "4096")),
    )


def build_agent() -> Agent:
    return Agent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        instructions=SYSTEM_PROMPT,
        model=_build_model(),
        tools=list(TOOLS),
        markdown=True,
    )


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    """Build the agno agent once, on first use.

    Lazy by design: constructing the model needs ``OPENROUTER_API_KEY``, but the
    three deterministic tools and the finding index do NOT. Deferring the build
    keeps this module importable — and the tools unit-testable in CI — without
    any API key.
    """
    return build_agent()
