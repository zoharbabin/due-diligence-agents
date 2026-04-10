"""Tests for dd_agents.orchestrator.team -- AgentTeam management."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from dd_agents.orchestrator.team import (
    BASE_TIMEOUT_S,
    MAX_TIMEOUT_S,
    PER_SUBJECT_TIMEOUT_S,
    AgentTeam,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    tmp_path: Path,
    *,
    subject_names: list[str] | None = None,
    agent_prompts: dict[str, list[str]] | None = None,
) -> Any:
    """Build a minimal PipelineState-like object for tests."""
    state = MagicMock()
    state.project_dir = tmp_path / "project"
    state.project_dir.mkdir(parents=True, exist_ok=True)
    state.run_dir = tmp_path / "run"
    state.run_dir.mkdir(parents=True, exist_ok=True)
    state.run_id = "test_run_001"
    state.subject_safe_names = subject_names or ["acme", "globex"]
    state.agent_prompts = agent_prompts or {}
    state.deal_config = {}
    return state


# ---------------------------------------------------------------------------
# AgentTeam construction
# ---------------------------------------------------------------------------


class TestAgentTeamInit:
    """Tests for AgentTeam.__init__."""

    def test_default_construction(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)
        assert team.state is state
        assert team.agent_timeout_s == 30 * 60
        assert team._completed_agents == set()

    def test_custom_timeout(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state, agent_timeout_s=120)
        assert team.agent_timeout_s == 120


# ---------------------------------------------------------------------------
# Adaptive timeout (additional tests beyond test_orchestrator.py)
# ---------------------------------------------------------------------------


class TestAdaptiveTimeoutEdgeCases:
    """Additional adaptive timeout edge cases."""

    def test_zero_subjects_returns_base(self) -> None:
        result = AgentTeam.calculate_adaptive_timeout(0)
        assert result == BASE_TIMEOUT_S

    def test_large_subject_count_capped(self) -> None:
        result = AgentTeam.calculate_adaptive_timeout(10000)
        assert result == MAX_TIMEOUT_S

    def test_single_subject(self) -> None:
        result = AgentTeam.calculate_adaptive_timeout(1)
        assert result == BASE_TIMEOUT_S + PER_SUBJECT_TIMEOUT_S

    def test_result_is_integer(self) -> None:
        result = AgentTeam.calculate_adaptive_timeout(5)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# wait_for_agents
# ---------------------------------------------------------------------------


class TestWaitForAgents:
    """Tests for AgentTeam.wait_for_agents."""

    @pytest.mark.asyncio
    async def test_successful_agents(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)

        async def _ok() -> dict[str, Any]:
            return {"agent": "legal", "status": "completed"}

        task = asyncio.create_task(_ok())
        results = await team.wait_for_agents({"legal": task}, timeout=5.0)
        assert results["legal"]["status"] == "completed"
        assert "legal" in team._completed_agents

    @pytest.mark.asyncio
    async def test_timeout_agents(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)

        async def _slow() -> dict[str, Any]:
            await asyncio.sleep(100)
            return {"agent": "legal", "status": "completed"}

        task = asyncio.create_task(_slow())
        results = await team.wait_for_agents({"legal": task}, timeout=0.01)
        assert results["legal"]["status"] == "timeout"
        assert results["legal"]["is_error"] is True

    @pytest.mark.asyncio
    async def test_exception_in_agent(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)

        async def _fail() -> dict[str, Any]:
            raise RuntimeError("Agent crashed")

        task = asyncio.create_task(_fail())
        await asyncio.sleep(0.01)  # let task fail
        results = await team.wait_for_agents({"legal": task}, timeout=5.0)
        assert results["legal"]["status"] == "failed"
        assert "crashed" in results["legal"]["error"]

    @pytest.mark.asyncio
    async def test_cancelled_agent(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)

        async def _hang() -> dict[str, Any]:
            await asyncio.sleep(100)
            return {"agent": "legal", "status": "completed"}

        task = asyncio.create_task(_hang())
        task.cancel()
        await asyncio.sleep(0.01)
        results = await team.wait_for_agents({"legal": task}, timeout=5.0)
        assert results["legal"]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# _run_specialist
# ---------------------------------------------------------------------------


class TestRunSpecialist:
    """Tests for AgentTeam._run_specialist."""

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_failed(self, tmp_path: Path) -> None:
        state = _make_state(tmp_path)
        team = AgentTeam(state)
        result = await team._run_specialist("unknown_agent", {})
        assert result["status"] == "failed"
        assert result["is_error"] is True
        assert "Unknown specialist agent" in result["error"]

    @pytest.mark.asyncio
    async def test_legal_agent_with_mock_runner(self, tmp_path: Path) -> None:
        """Verify the specialist wiring works when the runner is mocked."""
        state = _make_state(tmp_path, agent_prompts={"legal": ["Analyze contracts"]})
        team = AgentTeam(state)

        mock_run = AsyncMock(return_value={"output": [{"finding": "test"}], "error": None})

        with (
            patch("dd_agents.orchestrator.team.SPECIALIST_CLASSES", create=True),
            patch("dd_agents.agents.specialists.SPECIALIST_CLASSES") as mock_classes,
        ):
            mock_cls = MagicMock()
            mock_instance = MagicMock()
            mock_instance.run = mock_run
            mock_cls.return_value = mock_instance

            mock_classes.__getitem__ = MagicMock(return_value=mock_cls)
            mock_classes.__contains__ = MagicMock(return_value=True)

            result = await team._run_specialist("legal", {})

        assert result["agent"] == "legal"
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# spawn_specialists with subset
# ---------------------------------------------------------------------------


class TestSpawnSpecialistsSubset:
    """Tests for spawn_specialists with agent subset (Issue #51)."""

    @pytest.mark.asyncio
    async def test_empty_agent_list_raises(self, tmp_path: Path) -> None:
        """Spawning with an empty agent list raises ValueError from asyncio.wait."""
        state = _make_state(tmp_path)
        team = AgentTeam(state)
        with pytest.raises(ValueError, match="empty"):
            await team.spawn_specialists(agents=[])
