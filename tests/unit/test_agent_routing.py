"""Tests for per-agent provider routing (Issue #233)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dd_agents.models.config import AgentModelsConfig, AgentRoute, DealConfig

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.agents.specialists import LegalAgent


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
    def test_credentialed_base_url_rejected_at_config_boundary(self) -> None:
        # A base_url with embedded credentials must be rejected (fail-closed) —
        # credentials belong in auth_token_env, never in the URL/config.
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            AgentRoute(base_url="https://tok:pw@gw.example/v1")  # pragma: allowlist secret

    def test_safe_base_url_strips_userinfo_defensively(self) -> None:
        # Even if a credentialed URL somehow reaches the model, safe_base_url is clean.
        r = AgentRoute.model_construct(base_url="https://tok:pw@gw.example:4011/v1?x=1")  # pragma: allowlist secret
        safe = r.safe_base_url
        assert safe == "https://gw.example:4011/v1"
        assert "pw@" not in (safe or "") and "tok:" not in (safe or "")

    def test_safe_base_url_none_when_unset(self) -> None:
        assert AgentRoute(model="m1").safe_base_url is None


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
    def _runner(self, tmp_path: Path, deal_config: DealConfig | None) -> LegalAgent:
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
