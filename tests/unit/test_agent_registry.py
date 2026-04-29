"""Unit tests for dd_agents.agents.descriptor and dd_agents.agents.registry."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dd_agents.agents.base import BaseAgentRunner
from dd_agents.agents.descriptor import DEFAULT_AGENT_COLORS, AgentDescriptor
from dd_agents.agents.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAgent(BaseAgentRunner):
    """Minimal concrete agent for testing."""

    def get_agent_name(self) -> str:
        return "stub"

    def get_system_prompt(self) -> str:
        return "You are a stub."

    def get_tools(self) -> list[str]:
        return ["Read"]


def _make_descriptor(name: str = "test_agent", **overrides: Any) -> AgentDescriptor:
    defaults: dict[str, Any] = {
        "name": name,
        "display_name": name.replace("_", " ").title(),
        "color": "#000000",
        "focus_areas": ("area_a", "area_b"),
        "reference_categories": ("financial",),
        "agent_class": _StubAgent,
        "specialist_focus": "Focus on testing.",
    }
    defaults.update(overrides)
    return AgentDescriptor(**defaults)


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    """Reset the registry before and after each test.

    Sets ``_builtins_loaded = True`` so lazy loading is suppressed.
    Tests that explicitly want builtins use ``_with_builtins`` fixture.
    """
    import dd_agents.agents.registry as _reg

    AgentRegistry.reset()
    _reg._builtins_loaded = True  # suppress lazy loading for isolated tests
    yield
    AgentRegistry.reset()


# ===================================================================
# AgentDescriptor
# ===================================================================


class TestAgentDescriptor:
    def test_creation(self) -> None:
        d = _make_descriptor("legal")
        assert d.name == "legal"
        assert d.display_name == "Legal"
        assert d.focus_areas == ("area_a", "area_b")

    def test_frozen_immutability(self) -> None:
        d = _make_descriptor()
        with pytest.raises(AttributeError):
            d.name = "changed"  # type: ignore[misc]

    def test_defaults(self) -> None:
        d = _make_descriptor()
        assert d.max_subjects_per_batch == 20
        assert d.max_tokens_per_batch == 40_000
        assert d.is_builtin is True
        assert d.source_package == ""
        assert d.citation_examples == ""
        assert d.domain_robustness == ""

    def test_custom_batch_sizing(self) -> None:
        d = _make_descriptor(max_subjects_per_batch=7, max_tokens_per_batch=20_000)
        assert d.max_subjects_per_batch == 7
        assert d.max_tokens_per_batch == 20_000

    def test_external_agent_fields(self) -> None:
        d = _make_descriptor(is_builtin=False, source_package="dd-agents-esg")
        assert d.is_builtin is False
        assert d.source_package == "dd-agents-esg"


class TestDefaultAgentColors:
    def test_all_builtin_agents_have_colors(self) -> None:
        for name in (
            "legal",
            "finance",
            "commercial",
            "producttech",
            "hr",
            "tax",
            "cybersecurity",
            "regulatory",
            "esg",
        ):
            assert name in DEFAULT_AGENT_COLORS
            assert DEFAULT_AGENT_COLORS[name].startswith("#")

    def test_all_colors_are_distinct(self) -> None:
        colors = list(DEFAULT_AGENT_COLORS.values())
        assert len(colors) == len(set(colors))


# ===================================================================
# AgentRegistry — registration and lookup
# ===================================================================


class TestAgentRegistryBasic:
    def test_register_and_get(self) -> None:
        d = _make_descriptor("alpha")
        AgentRegistry.register(d)
        assert AgentRegistry.get("alpha") is d

    def test_get_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="No agent registered"):
            AgentRegistry.get("nonexistent")

    def test_keyerror_lists_known_agents(self) -> None:
        AgentRegistry.register(_make_descriptor("aaa"))
        AgentRegistry.register(_make_descriptor("zzz"))
        with pytest.raises(KeyError, match="aaa, zzz"):
            AgentRegistry.get("missing")

    def test_all_specialist_names_insertion_order(self) -> None:
        AgentRegistry.register(_make_descriptor("charlie"))
        AgentRegistry.register(_make_descriptor("alpha"))
        AgentRegistry.register(_make_descriptor("bravo"))
        assert AgentRegistry.all_specialist_names() == ["charlie", "alpha", "bravo"]

    def test_duplicate_registration_overwrites(self) -> None:
        d1 = _make_descriptor("dup", color="#111111")
        d2 = _make_descriptor("dup", color="#222222")
        AgentRegistry.register(d1)
        AgentRegistry.register(d2)
        assert AgentRegistry.get("dup").color == "#222222"

    def test_reset_clears_all(self) -> None:
        import dd_agents.agents.registry as _reg

        AgentRegistry.register(_make_descriptor("x"))
        AgentRegistry.reset()
        _reg._builtins_loaded = True  # suppress lazy reload after reset
        assert AgentRegistry.all_specialist_names() == []


# ===================================================================
# AgentRegistry — resolve_active
# ===================================================================


class TestResolveActive:
    def test_no_config_returns_all(self) -> None:
        AgentRegistry.register(_make_descriptor("a"))
        AgentRegistry.register(_make_descriptor("b"))
        assert AgentRegistry.resolve_active(None) == ["a", "b"]

    def test_empty_disabled_returns_all(self) -> None:
        AgentRegistry.register(_make_descriptor("a"))
        AgentRegistry.register(_make_descriptor("b"))
        config = self._make_config(disabled=[])
        assert AgentRegistry.resolve_active(config) == ["a", "b"]

    def test_disable_one_agent(self) -> None:
        AgentRegistry.register(_make_descriptor("legal"))
        AgentRegistry.register(_make_descriptor("finance"))
        AgentRegistry.register(_make_descriptor("commercial"))
        config = self._make_config(disabled=["finance"])
        assert AgentRegistry.resolve_active(config) == ["legal", "commercial"]

    def test_disable_multiple_agents(self) -> None:
        for name in ("a", "b", "c", "d"):
            AgentRegistry.register(_make_descriptor(name))
        config = self._make_config(disabled=["b", "d"])
        assert AgentRegistry.resolve_active(config) == ["a", "c"]

    def test_disable_all_agents(self) -> None:
        AgentRegistry.register(_make_descriptor("only"))
        config = self._make_config(disabled=["only"])
        assert AgentRegistry.resolve_active(config) == []

    def test_unknown_disabled_name_warns(self) -> None:
        AgentRegistry.register(_make_descriptor("real"))
        config = self._make_config(disabled=["fake"])
        with patch("dd_agents.agents.registry.logger") as mock_log:
            result = AgentRegistry.resolve_active(config)
        assert result == ["real"]
        mock_log.warning.assert_called_once()
        assert "fake" in str(mock_log.warning.call_args)

    def test_config_without_specialists_attr(self) -> None:
        AgentRegistry.register(_make_descriptor("x"))
        config = MagicMock(spec=[])
        assert AgentRegistry.resolve_active(config) == ["x"]

    @staticmethod
    def _make_config(disabled: list[str]) -> Any:
        config = MagicMock()
        config.forensic_dd.specialists.disabled = disabled
        return config


# ===================================================================
# AgentRegistry — entry points discovery
# ===================================================================


class TestDiscoverEntryPoints:
    def test_loads_valid_entry_point(self) -> None:
        descriptor = _make_descriptor("ext_agent", is_builtin=False)
        mock_ep = MagicMock()
        mock_ep.name = "ext_agent"
        mock_ep.value = "ext_package.agents:register"
        mock_ep.load.return_value = lambda: descriptor

        with (
            patch("dd_agents.agents.registry.entry_points", return_value=[mock_ep], create=True),
            patch("importlib.metadata.entry_points", return_value=[mock_ep]),
        ):
            AgentRegistry.discover_entry_points()

        assert AgentRegistry.get("ext_agent") is descriptor

    def test_broken_entry_point_skipped(self) -> None:
        mock_ep = MagicMock()
        mock_ep.name = "broken"
        mock_ep.load.side_effect = ImportError("missing dep")

        with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
            AgentRegistry.discover_entry_points()

        assert "broken" not in AgentRegistry.all_specialist_names()


# ===================================================================
# AgentRegistry — builtin lazy loading
# ===================================================================


class TestBuiltinLazyLoading:
    """These tests re-enable lazy loading to verify built-in self-registration."""

    @pytest.fixture(autouse=True)
    def _allow_builtins(self) -> Any:
        """Re-enable lazy loading so builtins register."""

        AgentRegistry.reset()  # clears descriptors AND sets _builtins_loaded=False
        yield

    def test_all_specialist_names_triggers_builtin_load(self) -> None:
        names = AgentRegistry.all_specialist_names()
        assert "legal" in names
        assert "finance" in names
        assert "commercial" in names
        assert "producttech" in names
        assert "cybersecurity" in names
        assert "hr" in names
        assert "tax" in names
        assert "regulatory" in names
        assert "esg" in names
        assert len(names) == 9

    def test_get_builtin_agent(self) -> None:
        d = AgentRegistry.get("legal")
        assert d.name == "legal"
        assert d.display_name == "Legal"
        assert len(d.focus_areas) > 0

    def test_resolve_active_triggers_builtin_load(self) -> None:
        result = AgentRegistry.resolve_active(None)
        assert len(result) == 9

    def test_builtin_descriptors_have_focus_areas(self) -> None:
        for name in (
            "legal",
            "finance",
            "commercial",
            "producttech",
            "cybersecurity",
            "hr",
            "tax",
            "regulatory",
            "esg",
        ):
            d = AgentRegistry.get(name)
            assert len(d.focus_areas) >= 8, f"{name} should have at least 8 focus areas"

    def test_builtin_descriptors_have_colors(self) -> None:
        for name in (
            "legal",
            "finance",
            "commercial",
            "producttech",
            "cybersecurity",
            "hr",
            "tax",
            "regulatory",
            "esg",
        ):
            d = AgentRegistry.get(name)
            assert d.color.startswith("#")

    def test_builtin_descriptors_have_specialist_focus(self) -> None:
        for name in (
            "legal",
            "finance",
            "commercial",
            "producttech",
            "cybersecurity",
            "hr",
            "tax",
            "regulatory",
            "esg",
        ):
            d = AgentRegistry.get(name)
            assert len(d.specialist_focus) > 100, f"{name} specialist_focus should be substantial"

    def test_builtin_descriptors_have_citation_examples(self) -> None:
        for name in (
            "legal",
            "finance",
            "commercial",
            "producttech",
            "cybersecurity",
            "hr",
            "tax",
            "regulatory",
            "esg",
        ):
            d = AgentRegistry.get(name)
            assert len(d.citation_examples) > 50, f"{name} should have citation examples"

    def test_finance_producttech_smaller_batches(self) -> None:
        for name in ("finance", "producttech"):
            d = AgentRegistry.get(name)
            assert d.max_subjects_per_batch == 7
            assert d.max_tokens_per_batch == 20_000

    def test_cybersecurity_batch_sizing(self) -> None:
        d = AgentRegistry.get("cybersecurity")
        assert d.max_subjects_per_batch == 15
        assert d.max_tokens_per_batch == 30_000
