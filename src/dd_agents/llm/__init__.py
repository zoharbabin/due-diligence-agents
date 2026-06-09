"""LLM provider seam — the single place dd-agents builds SDK model calls.

dd-agents is provider- and model-agnostic by configuration: every reasoning
call goes through ``claude_agent_sdk`` (the Anthropic Messages wire protocol),
and the provider/model is chosen by environment, never hardcoded. Native
providers (Anthropic API, AWS Bedrock, Google Vertex) are selected by the
Claude CLI's own env vars; *any other model* (GPT, Gemini, DeepSeek, local) is
reachable by pointing ``ANTHROPIC_BASE_URL`` at an Anthropic-compatible gateway
(e.g. LiteLLM). See ``docs/user-guide/model-providers.md``.

This package centralizes that contract so no call site hand-builds
``ClaudeAgentOptions`` or silently rides the CLI default model.
"""

from __future__ import annotations

from dd_agents.llm.provider import (
    ProviderInfo,
    build_agent_options,
    resolve_provider,
)

__all__ = [
    "ProviderInfo",
    "build_agent_options",
    "resolve_provider",
]
