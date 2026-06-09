"""Live proof that dd-agents runs on ANY model via an Anthropic-compatible gateway.

This is the automated version of the manual validation behind the LLM provider
seam (``dd_agents.llm.provider``): point ``ANTHROPIC_BASE_URL`` at a gateway
(e.g. LiteLLM) that fronts a non-Claude model, and confirm a real
``claude_agent_sdk`` query completes without error. It exercises the *whole*
stack — the seam → the SDK → the CLI → the gateway → an arbitrary model.

Opt-in: skipped unless ``DD_TEST_GATEWAY_URL`` is set (so it never runs in the
normal CI matrix, which has no proxy). To run it:

    # 1. start a gateway, e.g. the recipe in examples/litellm-gateway/
    # 2. point the test at it:
    DD_TEST_GATEWAY_URL=http://localhost:4011 \
    DD_TEST_GATEWAY_KEY=sk-anything \
    DD_TEST_GATEWAY_MODEL=claude-sonnet-4-6 \
    DD_MAX_OUTPUT_TOKENS=4096 \
    pytest tests/e2e/test_gateway_provider.py -m gateway
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.gateway

_GATEWAY_URL = os.getenv("DD_TEST_GATEWAY_URL", "").strip()

skip_no_gateway = pytest.mark.skipif(
    not _GATEWAY_URL,
    reason="DD_TEST_GATEWAY_URL not set — skipping the live gateway provider test",
)


@skip_no_gateway
@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_query_completes_through_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real query through the gateway returns a non-error completion.

    Proves the model-agnostic path end-to-end: the seam builds options pointed
    (via env) at an Anthropic-compatible gateway, and the SDK round-trips a
    completion regardless of which model the gateway actually serves.
    """
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

    from dd_agents.llm import build_agent_options, resolve_provider

    # Route the SDK/CLI at the gateway; clear native cloud routing for the test.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", _GATEWAY_URL)
    monkeypatch.setenv("ANTHROPIC_API_KEY", os.getenv("DD_TEST_GATEWAY_KEY", "sk-test"))
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", os.getenv("DD_TEST_GATEWAY_KEY", "sk-test"))
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)

    assert resolve_provider().provider == "gateway"

    options = build_agent_options(
        model=os.getenv("DD_TEST_GATEWAY_MODEL") or None,
        max_turns=1,
        permission_mode="bypassPermissions",
    )

    text: list[str] = []
    errored = False
    async for message in query(prompt="Reply with exactly the token GATEWAY_OK.", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text.append(block.text)
        elif isinstance(message, ResultMessage):
            errored = bool(message.is_error)

    joined = " ".join(text)
    assert not errored, f"gateway query errored; partial text: {joined[:200]!r}"
    assert joined.strip(), "gateway query returned no text"
