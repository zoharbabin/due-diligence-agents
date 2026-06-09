"""Atlas DD Analyst — an agno agent that answers questions about a completed
dd-agents due-diligence report.

No server is started here. ``cli.py`` calls ``get_agent()`` for one-shot local
runs; ``bindu_agent.py`` calls it to expose the agent over A2A.

The agent's tools (in ``report_tools.py``) read a deal's *already-produced*
merged findings through the upstream ``dd_agents.query`` finding index — pure,
deterministic Python, no LLM and no key. The agno model supplies the
conversational reasoning on top. The dd-agents pipeline itself is never run here.

Provider-agnostic, like the pipeline: pick the LLM backend with
``BINDU_AGENT_PROVIDER`` (default ``bedrock``, matching dd-agents' enterprise
posture — your data stays within your own AWS account). Each provider reads its
own standard credentials (the same env you already use for the pipeline), so no
single vendor is hardcoded. See ``.env.example`` for the supported providers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from prompts import AGENT_DESCRIPTION, AGENT_NAME, SYSTEM_PROMPT

# Deterministic, key-free report tools (also unit-tested without agno/bindu).
from report_tools import TOOLS, report_path

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.models.base import Model

__all__ = ["BINDU_AGENT_PROVIDERS", "build_agent", "get_agent", "report_path"]

# Default model id per provider (override with BINDU_AGENT_MODEL). These are
# illustrative current Claude tiers; the example reasons over deterministic
# tools, so any solid tool-calling model works.
_DEFAULT_MODEL_ID: dict[str, str] = {
    "bedrock": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o",
    "google": "gemini-2.5-flash",
    "openrouter": "anthropic/claude-sonnet-4.5",
}

# Human-readable list of supported providers (used in error messages + docs).
BINDU_AGENT_PROVIDERS = tuple(_DEFAULT_MODEL_ID)


def _build_model() -> Model:
    """Build the agno model for the configured provider (BINDU_AGENT_PROVIDER).

    Provider-agnostic by design — mirrors dd-agents' own "bring your own
    provider" stance. The model class is imported lazily so installing only the
    SDK for the provider you use is enough. Each provider reads its standard
    credentials from the environment (e.g. AWS creds for Bedrock,
    ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GOOGLE_API_KEY``,
    ``OPENROUTER_API_KEY``), exactly as the agno docs specify.
    """
    provider = os.getenv("BINDU_AGENT_PROVIDER", "bedrock").strip().lower()
    if provider not in _DEFAULT_MODEL_ID:
        raise RuntimeError(
            f"Unknown BINDU_AGENT_PROVIDER {provider!r}. Choose one of: {', '.join(BINDU_AGENT_PROVIDERS)}."
        )
    model_id = os.getenv("BINDU_AGENT_MODEL", _DEFAULT_MODEL_ID[provider])
    max_tokens = int(os.getenv("BINDU_AGENT_MAX_TOKENS", "4096"))

    if provider == "bedrock":
        # Anthropic-on-Bedrock — your data stays in your AWS account. Reads the
        # standard AWS credential chain (AWS_PROFILE / AWS_REGION / keys).
        from agno.models.aws import Claude as BedrockClaude

        return BedrockClaude(id=model_id, max_tokens=max_tokens)
    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=model_id, max_tokens=max_tokens)
    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=model_id, max_tokens=max_tokens)
    if provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=model_id)
    # openrouter
    from agno.models.openrouter import OpenRouter

    return OpenRouter(id=model_id, max_tokens=max_tokens)


def build_agent() -> Agent:
    from agno.agent import Agent

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

    Lazy by design: constructing the model needs provider credentials
    (``BINDU_AGENT_PROVIDER``), but the three deterministic tools and the finding
    index do NOT. Deferring the build keeps this module importable — and the
    tools unit-testable in CI — without any key. The agno import is also lazy so
    the report tools can be exercised without agno installed.
    """
    return build_agent()
