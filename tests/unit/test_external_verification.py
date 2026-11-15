"""External verification plumbing (Issue #274, phase 1).

Covers: config model, MCP server spec, tool allowlist, pre-tool guard,
runner wiring and provenance. No network and no real MCP server.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.hooks.pre_tool import external_tool_guard
from dd_agents.models.config import (
    EXTERNAL_DENIED_TOOLS,
    DealConfig,
    ExternalVerificationConfig,
)
from dd_agents.persistence.provenance import compute_config_hash
from dd_agents.tools.external_mcp import (
    ExternalAccess,
    build_external_mcp_servers,
    external_tool_names,
    resolve_external_access,
)


def _deal(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer A"},
        "target": {"name": "Subject A"},
        "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
    }
    base.update(extra or {})
    return base


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


class TestConfig:
    def test_off_by_default(self) -> None:
        cfg = DealConfig.model_validate(_deal())
        assert cfg.external_verification.enabled is False

    def test_defaults_point_at_web_researcher(self) -> None:
        server = ExternalVerificationConfig().server
        assert server.name == "web-researcher"
        assert server.command == "uvx"
        assert server.args == ["web-researcher-mcp"]
        assert server.env_passthrough == []

    def test_default_allowlist_is_read_only(self) -> None:
        cfg = ExternalVerificationConfig()
        assert cfg.allowed_tools
        assert not set(cfg.allowed_tools) & set(EXTERNAL_DENIED_TOOLS)

    @pytest.mark.parametrize("tool", sorted(EXTERNAL_DENIED_TOOLS))
    def test_denied_tool_rejected(self, tool: str) -> None:
        with pytest.raises(ValidationError):
            ExternalVerificationConfig(allowed_tools=["web_search", tool])

    @pytest.mark.parametrize("bad", ["*", "web search", "a/b", ""])
    def test_bad_tool_name_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            ExternalVerificationConfig(allowed_tools=[bad])

    def test_empty_allowlist_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExternalVerificationConfig(allowed_tools=[])

    @pytest.mark.parametrize("bad", ["dd_tools", "has space", "a__b", ""])
    def test_bad_server_name_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            ExternalVerificationConfig.model_validate({"server": {"name": bad}})

    @pytest.mark.parametrize("bad", ["lower", "HAS SPACE", "A=B", ""])
    def test_env_passthrough_takes_names_only(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            ExternalVerificationConfig.model_validate({"server": {"env_passthrough": [bad]}})

    def test_env_values_cannot_be_stored_in_config(self) -> None:
        # Secrets stay in the process env. A literal `env` map is rejected, not ignored.
        with pytest.raises(ValidationError):
            ExternalVerificationConfig.model_validate({"server": {"env": {"EDGAR_CONTACT_EMAIL": "x@example.com"}}})


# ---------------------------------------------------------------------------
# MCP server spec and tool names
# ---------------------------------------------------------------------------


class TestServerSpec:
    def test_disabled_returns_nothing(self) -> None:
        assert build_external_mcp_servers(ExternalVerificationConfig(), {}) == {}
        assert external_tool_names(ExternalVerificationConfig()) == []
        assert resolve_external_access(DealConfig.model_validate(_deal())) is None

    def test_enabled_builds_stdio_spec(self) -> None:
        cfg = ExternalVerificationConfig.model_validate({"enabled": True})
        servers = build_external_mcp_servers(cfg, {})
        assert servers == {
            "web-researcher": {"type": "stdio", "command": "uvx", "args": ["web-researcher-mcp"], "env": {}}
        }

    def test_passthrough_copies_only_named_vars_that_exist(self) -> None:
        cfg = ExternalVerificationConfig.model_validate(
            {"enabled": True, "server": {"env_passthrough": ["EDGAR_CONTACT_EMAIL", "MISSING_ONE"]}}
        )
        env = {"EDGAR_CONTACT_EMAIL": "a@example.com", "ANTHROPIC_API_KEY": "must-not-leak"}
        spec = build_external_mcp_servers(cfg, env)["web-researcher"]
        assert spec["env"] == {"EDGAR_CONTACT_EMAIL": "a@example.com"}

    def test_tool_names_use_mcp_prefix(self) -> None:
        cfg = ExternalVerificationConfig.model_validate({"enabled": True, "allowed_tools": ["web_search"]})
        assert external_tool_names(cfg) == ["mcp__web-researcher__web_search"]

    def test_resolve_access_from_deal_config(self) -> None:
        deal = DealConfig.model_validate(_deal({"external_verification": {"enabled": True}}))
        access = resolve_external_access(deal, environ={})
        assert isinstance(access, ExternalAccess)
        assert access.server_name == "web-researcher"
        assert "web-researcher" in access.servers
        assert "mcp__web-researcher__web_search" in access.tool_names


# ---------------------------------------------------------------------------
# Pre-tool guard
# ---------------------------------------------------------------------------


class TestGuard:
    ACCESS = ExternalAccess(
        server_name="web-researcher",
        servers={},
        tool_names=["mcp__web-researcher__web_search"],
    )

    def test_non_mcp_tool_ignored(self) -> None:
        assert external_tool_guard("Read", None)["decision"] == "allow"

    def test_internal_server_always_allowed(self) -> None:
        assert external_tool_guard("mcp__dd_tools__verify_citation", None)["decision"] == "allow"

    def test_unknown_server_blocked_without_access(self) -> None:
        out = external_tool_guard("mcp__web-researcher__web_search", None)
        assert out["decision"] == "block"

    def test_unknown_server_blocked_with_access(self) -> None:
        out = external_tool_guard("mcp__other__thing", self.ACCESS)
        assert out["decision"] == "block"

    def test_allowlisted_tool_allowed(self) -> None:
        assert external_tool_guard("mcp__web-researcher__web_search", self.ACCESS)["decision"] == "allow"

    def test_other_tool_on_external_server_blocked(self) -> None:
        out = external_tool_guard("mcp__web-researcher__archive_source", self.ACCESS)
        assert out["decision"] == "block"
        assert "archive_source" in out["reason"]


# ---------------------------------------------------------------------------
# Runner wiring
# ---------------------------------------------------------------------------


class _Runner(BaseAgentRunner):
    def __init__(self, access: ExternalAccess | None) -> None:
        from pathlib import Path

        super().__init__(Path("."), Path("."), "run_1")
        self._access = access

    def get_agent_name(self) -> str:
        return "stub"

    def get_system_prompt(self) -> str:
        return ""

    def get_tools(self) -> list[str]:
        return ["Read"]

    def build_prompt(self, state: dict[str, Any]) -> str:
        return ""

    def get_external_access(self) -> ExternalAccess | None:
        return self._access


class TestRunnerWiring:
    def test_default_runner_has_no_external_access(self) -> None:
        assert BaseAgentRunner.get_external_access(_Runner(None)) is None

    def test_without_access_only_internal_server(self) -> None:
        runner = _Runner(None)
        servers, tools = runner._mcp_servers_and_tools(internal_server="srv")
        assert servers == {"dd_tools": "srv"}
        assert tools == ["Read"]

    def test_with_access_adds_server_and_tools(self) -> None:
        access = ExternalAccess(
            server_name="web-researcher",
            servers={"web-researcher": {"type": "stdio", "command": "x", "args": [], "env": {}}},
            tool_names=["mcp__web-researcher__web_search"],
        )
        servers, tools = _Runner(access)._mcp_servers_and_tools(internal_server="srv")
        assert set(servers or {}) == {"dd_tools", "web-researcher"}
        assert tools == ["Read", "mcp__web-researcher__web_search"]

    def test_with_access_and_no_internal_server(self) -> None:
        access = ExternalAccess("web-researcher", {"web-researcher": {}}, ["mcp__web-researcher__web_search"])
        servers, _ = _Runner(access)._mcp_servers_and_tools(internal_server=None)
        assert set(servers or {}) == {"web-researcher"}


# ---------------------------------------------------------------------------
# Provenance: the block is inside the config hash, so resume fails closed
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_absent_block_leaves_hash_unchanged(self) -> None:
        assert compute_config_hash(_deal()) == compute_config_hash(_deal())

    def test_enabling_changes_hash(self) -> None:
        on = _deal({"external_verification": {"enabled": True}})
        assert compute_config_hash(on) != compute_config_hash(_deal())

    def test_allowlist_change_changes_hash(self) -> None:
        a = _deal({"external_verification": {"enabled": True, "allowed_tools": ["web_search"]}})
        b = _deal({"external_verification": {"enabled": True, "allowed_tools": ["web_search", "news_search"]}})
        assert compute_config_hash(a) != compute_config_hash(b)

    def test_server_change_changes_hash(self) -> None:
        a = _deal({"external_verification": {"enabled": True}})
        b = _deal({"external_verification": {"enabled": True, "server": {"command": "other"}}})
        assert compute_config_hash(a) != compute_config_hash(b)
