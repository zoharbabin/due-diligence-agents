"""Tests for Agent Cost Optimization — Model Selection, Cost Tracking & Budget (Issue #129)."""

from __future__ import annotations

import pytest

from dd_agents.agents.cost_tracker import (
    AgentCostEntry,
    CostTracker,
    get_model_profiles,
)
from dd_agents.models.config import AgentModelsConfig, DealConfig

# ---------------------------------------------------------------------------
# ModelProfile tests
# ---------------------------------------------------------------------------


class TestModelProfiles:
    """Test model profile presets."""

    def test_three_profiles_exist(self) -> None:
        profiles = get_model_profiles()
        assert set(profiles.keys()) == {"economy", "standard", "premium"}

    def test_economy_uses_haiku_for_specialists(self) -> None:
        profiles = get_model_profiles()
        econ = profiles["economy"]
        assert "haiku" in econ.specialist_model.lower()

    def test_premium_uses_opus_for_synthesis(self) -> None:
        profiles = get_model_profiles()
        premium = profiles["premium"]
        assert "opus" in premium.executive_synthesis_model.lower()

    def test_standard_uses_sonnet_for_specialists(self) -> None:
        profiles = get_model_profiles()
        std = profiles["standard"]
        assert "sonnet" in std.specialist_model.lower()

    def test_profile_has_all_agent_types(self) -> None:
        profiles = get_model_profiles()
        for name, profile in profiles.items():
            assert profile.specialist_model, f"{name} missing specialist_model"
            assert profile.judge_model, f"{name} missing judge_model"
            assert profile.executive_synthesis_model, f"{name} missing executive_synthesis_model"
            assert profile.red_flag_scanner_model, f"{name} missing red_flag_scanner_model"

    def test_profile_get_model_for_agent(self) -> None:
        profiles = get_model_profiles()
        std = profiles["standard"]
        assert std.get_model_for_agent("legal") == std.specialist_model
        assert std.get_model_for_agent("finance") == std.specialist_model
        assert std.get_model_for_agent("judge") == std.judge_model
        assert std.get_model_for_agent("executive_synthesis") == std.executive_synthesis_model
        assert std.get_model_for_agent("red_flag_scanner") == std.red_flag_scanner_model

    def test_profile_unknown_agent_returns_specialist(self) -> None:
        profiles = get_model_profiles()
        std = profiles["standard"]
        assert std.get_model_for_agent("unknown_agent") == std.specialist_model


# ---------------------------------------------------------------------------
# AgentModelsConfig tests
# ---------------------------------------------------------------------------


class TestAgentModelsConfig:
    """Test deal config model selection."""

    def test_default_profile_is_standard(self) -> None:
        cfg = AgentModelsConfig()
        assert cfg.profile == "standard"

    def test_custom_overrides(self) -> None:
        cfg = AgentModelsConfig(
            profile="economy",
            overrides={"legal": "claude-opus-4-6"},
        )
        assert cfg.profile == "economy"
        assert cfg.overrides["legal"] == "claude-opus-4-6"

    def test_resolve_model_uses_override(self) -> None:
        cfg = AgentModelsConfig(
            profile="economy",
            overrides={"legal": "claude-opus-4-6"},
        )
        assert cfg.resolve_model("legal") == "claude-opus-4-6"

    def test_resolve_model_falls_back_to_profile(self) -> None:
        cfg = AgentModelsConfig(profile="economy")
        profiles = get_model_profiles()
        assert cfg.resolve_model("finance") == profiles["economy"].specialist_model

    def test_in_deal_config(self) -> None:
        dc = DealConfig(
            config_version="1.0.0",
            buyer={"name": "Buyer"},
            target={"name": "Target"},
            deal={"type": "acquisition", "focus_areas": ["ip_ownership"]},
            agent_models={"profile": "premium"},
        )
        assert dc.agent_models.profile == "premium"

    def test_deal_config_default_agent_models(self) -> None:
        dc = DealConfig(
            config_version="1.0.0",
            buyer={"name": "Buyer"},
            target={"name": "Target"},
            deal={"type": "acquisition", "focus_areas": ["ip_ownership"]},
        )
        assert dc.agent_models.profile == "standard"


# ---------------------------------------------------------------------------
# CostTracker tests
# ---------------------------------------------------------------------------


class TestCostTracker:
    """Test token/cost tracking."""

    def test_empty_tracker(self) -> None:
        tracker = CostTracker()
        assert tracker.total_cost() == 0.0
        assert tracker.total_tokens() == 0

    def test_record_usage(self) -> None:
        tracker = CostTracker()
        tracker.record(
            agent_name="legal",
            step="step_16",
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-6",
        )
        assert tracker.total_tokens() == 1500
        assert tracker.total_cost() > 0.0

    def test_multiple_records(self) -> None:
        tracker = CostTracker()
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        tracker.record("finance", "step_16", 2000, 800, "claude-sonnet-4-6")
        assert tracker.total_tokens() == 4300
        assert len(tracker.entries) == 2

    def test_cost_by_agent(self) -> None:
        tracker = CostTracker()
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        tracker.record("finance", "step_16", 2000, 800, "claude-sonnet-4-6")
        by_agent = tracker.cost_by_agent()
        assert "legal" in by_agent
        assert "finance" in by_agent
        assert by_agent["legal"] > 0.0

    def test_cost_by_step(self) -> None:
        tracker = CostTracker()
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        tracker.record("judge", "step_20", 2000, 800, "claude-sonnet-4-6")
        by_step = tracker.cost_by_step()
        assert "step_16" in by_step
        assert "step_20" in by_step

    def test_budget_check_within(self) -> None:
        tracker = CostTracker(budget_limit_usd=100.0)
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        assert not tracker.is_budget_exceeded()

    def test_budget_check_exceeded(self) -> None:
        tracker = CostTracker(budget_limit_usd=0.001)
        tracker.record("legal", "step_16", 100_000, 50_000, "claude-sonnet-4-6")
        assert tracker.is_budget_exceeded()

    def test_no_budget_limit(self) -> None:
        tracker = CostTracker()
        tracker.record("legal", "step_16", 100_000, 50_000, "claude-sonnet-4-6")
        assert not tracker.is_budget_exceeded()

    def test_remaining_budget(self) -> None:
        tracker = CostTracker(budget_limit_usd=10.0)
        assert tracker.remaining_budget() == pytest.approx(10.0)
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        assert tracker.remaining_budget() < 10.0

    def test_to_dict(self) -> None:
        tracker = CostTracker()
        tracker.record("legal", "step_16", 1000, 500, "claude-sonnet-4-6")
        d = tracker.to_dict()
        assert "total_cost" in d
        assert "total_tokens" in d
        assert "entries" in d
        assert "by_agent" in d
        assert "by_step" in d

    def test_entry_model(self) -> None:
        entry = AgentCostEntry(
            agent_name="legal",
            step="step_16",
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4-6",
            cost_usd=0.012,
        )
        assert entry.total_tokens == 1500
        assert entry.cost_usd == pytest.approx(0.012)
