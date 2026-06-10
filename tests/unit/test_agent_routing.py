"""Tests for per-agent provider routing (Issue #233)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.models.config import AgentModelsConfig, AgentRoute, DealConfig

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestResolveModelAndRoute:
    def test_route_model_takes_precedence_over_override_and_profile(self) -> None:
        am = AgentModelsConfig(
            profile="standard",
            overrides={"legal": "claude-opus-4-8"},
            routes={"legal": AgentRoute(model="claude-haiku-4-5-20251001")},
        )
        # route.model wins over overrides and profile.
        assert am.resolve_model("legal") == "claude-haiku-4-5-20251001"

    def test_override_still_works_without_route(self) -> None:
        am = AgentModelsConfig(overrides={"legal": "claude-opus-4-8"})
        assert am.resolve_model("legal") == "claude-opus-4-8"
        assert am.resolve_route("legal") is None

    def test_profile_default_when_no_route_or_override(self) -> None:
        am = AgentModelsConfig(profile="economy")
        # economy → Haiku for specialists (real profile resolution).
        assert am.resolve_model("legal") == "claude-haiku-4-5-20251001"

    def test_route_without_model_keeps_profile_model(self) -> None:
        # A route that only sets base_url (no model) must NOT blank the model.
        am = AgentModelsConfig(profile="economy", routes={"legal": AgentRoute(base_url="http://gw")})
        assert am.resolve_model("legal") == "claude-haiku-4-5-20251001"


class TestRoutingFingerprint:
    def test_empty_when_no_routes(self) -> None:
        assert AgentModelsConfig().routing_fingerprint() == ""

    def test_changes_with_routing(self) -> None:
        a = AgentModelsConfig(routes={"legal": AgentRoute(base_url="http://gw-a")})
        b = AgentModelsConfig(routes={"legal": AgentRoute(base_url="http://gw-b")})
        assert a.routing_fingerprint() != b.routing_fingerprint()

    def test_deterministic_and_order_independent(self) -> None:
        a = AgentModelsConfig(routes={"legal": AgentRoute(model="m1"), "finance": AgentRoute(model="m2")})
        b = AgentModelsConfig(routes={"finance": AgentRoute(model="m2"), "legal": AgentRoute(model="m1")})
        assert a.routing_fingerprint() == b.routing_fingerprint()

    def test_token_value_never_in_fingerprint(self) -> None:
        # Only the env-var NAME is in config; the fingerprint must not contain a token.
        fp = AgentModelsConfig(
            routes={"legal": AgentRoute(base_url="http://x", auth_token_env="SECRET_TOK")}
        ).routing_fingerprint()
        assert "SECRET_TOK" in fp  # the NAME is fine
        # (no token value exists in config to leak — guard documents intent)

    def test_credentialed_base_url_stripped(self) -> None:
        fp = AgentModelsConfig(
            routes={"legal": AgentRoute(base_url="https://tok:pw@gw.example/v1")}  # pragma: allowlist secret
        ).routing_fingerprint()
        assert "pw@" not in fp and "tok:" not in fp
        assert "gw.example/v1" in fp


class TestProvenanceCoversRouting:
    def test_config_hash_busts_on_route_change(self) -> None:
        from dd_agents.persistence.provenance import compute_config_hash

        base = {
            "config_version": "1.0.0",
            "buyer": {"name": "B"},
            "target": {"name": "T"},
            "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
        }
        with_route = {**base, "agent_models": {"routes": {"legal": {"base_url": "http://gw"}}}}
        # Per-agent routing rides config_hash → resume is fail-closed across changes.
        assert compute_config_hash(base) != compute_config_hash(with_route)


class TestGetRouteEnv:
    def _runner(self, tmp_path: Path, deal_config: DealConfig | None):
        from dd_agents.agents.specialists import LegalAgent

        return LegalAgent(project_dir=tmp_path, run_dir=tmp_path, run_id="r", deal_config=deal_config)

    def test_no_config_no_env(self, tmp_path: Path) -> None:
        assert self._runner(tmp_path, None).get_route_env() == {}

    def test_route_without_base_url_no_env(self, tmp_path: Path) -> None:
        cfg = _deal_config(routes={"legal": AgentRoute(model="claude-haiku-4-5-20251001")})
        assert self._runner(tmp_path, cfg).get_route_env() == {}

    def test_base_url_sets_anthropic_base_url(self, tmp_path: Path) -> None:
        cfg = _deal_config(routes={"legal": AgentRoute(base_url="http://gw:4011")})
        env = self._runner(tmp_path, cfg).get_route_env()
        assert env == {"ANTHROPIC_BASE_URL": "http://gw:4011"}

    def test_auth_token_env_resolved_from_environment(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_GW_TOKEN", "sk-secret")  # pragma: allowlist secret
        cfg = _deal_config(routes={"legal": AgentRoute(base_url="http://gw", auth_token_env="MY_GW_TOKEN")})
        env = self._runner(tmp_path, cfg).get_route_env()
        assert env["ANTHROPIC_BASE_URL"] == "http://gw"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-secret"  # pragma: allowlist secret

    def test_missing_token_env_omitted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ABSENT_TOK", raising=False)
        cfg = _deal_config(routes={"legal": AgentRoute(base_url="http://gw", auth_token_env="ABSENT_TOK")})
        env = self._runner(tmp_path, cfg).get_route_env()
        assert "ANTHROPIC_AUTH_TOKEN" not in env  # absent token → not injected (no empty value)


def _deal_config(routes: dict[str, AgentRoute]) -> DealConfig:
    return DealConfig.model_validate(
        {
            "config_version": "1.0.0",
            "buyer": {"name": "B"},
            "target": {"name": "T"},
            "deal": {"type": "acquisition", "focus_areas": ["ip_ownership"]},
            "agent_models": {"routes": {k: v.model_dump() for k, v in routes.items()}},
        }
    )
