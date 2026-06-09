"""Tests for the shared LLM provider seam (dd_agents.llm.provider).

The seam is where dd-agents stays model- and provider-agnostic: one place that
builds ``ClaudeAgentOptions``, always sets the CLI path + an explicit model when
given, applies the output-token clamp, and reports the active provider from the
environment. These tests need no API key and no live SDK call.
"""

from __future__ import annotations

import pytest

from dd_agents.llm import build_agent_options, resolve_provider


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test from a known-empty provider environment."""
    for var in (
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "DD_MAX_OUTPUT_TOKENS",
        "DD_AGENTS_CLI_PATH",
    ):
        monkeypatch.delenv(var, raising=False)


class TestResolveProvider:
    def test_default_is_anthropic(self) -> None:
        info = resolve_provider()
        assert info.provider == "anthropic"
        assert info.base_url is None
        assert info.max_output_tokens is None

    def test_bedrock_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        assert resolve_provider().provider == "bedrock"

    def test_vertex_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "true")
        assert resolve_provider().provider == "vertex"

    def test_gateway_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A base URL means a gateway/proxy (any model) regardless of cloud flags."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:4011")
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        info = resolve_provider()
        assert info.provider == "gateway"
        assert info.base_url == "http://localhost:4011"

    def test_falsey_flag_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "0")
        assert resolve_provider().provider == "anthropic"

    def test_max_output_tokens_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DD_MAX_OUTPUT_TOKENS", "4096")
        assert resolve_provider().max_output_tokens == 4096

    def test_invalid_max_output_tokens_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DD_MAX_OUTPUT_TOKENS", "not-a-number")
        assert resolve_provider().max_output_tokens is None


class TestBuildAgentOptions:
    def test_sets_model_when_given(self) -> None:
        opts = build_agent_options(model="claude-sonnet-4-6", system_prompt="x", max_turns=1)
        assert opts.model == "claude-sonnet-4-6"

    def test_model_none_leaves_default(self) -> None:
        """model=None inherits the CLI/provider default (model attr stays None)."""
        opts = build_agent_options(model=None, system_prompt="x", max_turns=1)
        assert opts.model is None

    def test_arbitrary_model_id_passes_through(self) -> None:
        """Any model id is accepted — gateway models are not Claude IDs."""
        opts = build_agent_options(model="openai/gpt-4o", max_turns=1)
        assert opts.model == "openai/gpt-4o"

    def test_cli_path_set_when_resolvable(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
        fake_cli = tmp_path / "claude"
        fake_cli.write_text("#!/bin/sh\n")
        monkeypatch.setenv("DD_AGENTS_CLI_PATH", str(fake_cli))
        opts = build_agent_options(model="claude-sonnet-4-6", max_turns=1)
        assert opts.cli_path == str(fake_cli)

    def test_caller_cli_path_not_overridden(self) -> None:
        opts = build_agent_options(model="claude-sonnet-4-6", cli_path="/custom/claude", max_turns=1)
        assert opts.cli_path == "/custom/claude"

    def test_token_clamp_forwarded_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DD_MAX_OUTPUT_TOKENS", "4096")
        opts = build_agent_options(model="claude-sonnet-4-6", max_turns=1)
        assert opts.env.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == "4096"

    def test_no_clamp_no_env(self) -> None:
        opts = build_agent_options(model="claude-sonnet-4-6", max_turns=1)
        assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in (opts.env or {})

    def test_extra_env_merged(self) -> None:
        opts = build_agent_options(model="claude-sonnet-4-6", max_turns=1, extra_env={"FOO": "bar"})
        assert opts.env.get("FOO") == "bar"

    def test_forwards_kwargs(self) -> None:
        opts = build_agent_options(
            model="claude-sonnet-4-6",
            system_prompt="sys",
            max_turns=3,
            permission_mode="bypassPermissions",
            allowed_tools=["Read"],
        )
        assert opts.system_prompt == "sys"
        assert opts.max_turns == 3
        assert opts.allowed_tools == ["Read"]
