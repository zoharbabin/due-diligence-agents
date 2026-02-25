"""Agent team management for the forensic DD pipeline.

Provides ``AgentTeam`` -- a high-level coordinator that spawns specialist
agents in parallel, monitors their liveness, and collects results.  The
actual agent SDK integration lives in ``dd_agents.agents``; this module
wraps it with timeout / retry / liveness logic used by the orchestrator.

Until the agent SDK integration is wired up, methods return **placeholder**
results so the pipeline skeleton can be tested end-to-end.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from dd_agents.utils.constants import (
    AGENT_JUDGE,
    AGENT_REPORTING_LEAD,
    ALL_SPECIALIST_AGENTS,
)

if TYPE_CHECKING:
    from dd_agents.orchestrator.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_AGENT_TIMEOUT_S: int = 30 * 60  # 30 minutes per agent
DEFAULT_LIVENESS_INTERVAL_S: int = 5 * 60  # check every 5 minutes
DEFAULT_STALL_THRESHOLD_S: int = 10 * 60  # 10 minutes with no output


# ---------------------------------------------------------------------------
# AgentTeam
# ---------------------------------------------------------------------------


class AgentTeam:
    """Manages the lifecycle of all pipeline agents.

    Parameters
    ----------
    state:
        Current pipeline state (provides run_dir, project_dir, prompts, etc.).
    agent_timeout_s:
        Wall-clock timeout for each agent invocation (seconds).
    liveness_interval_s:
        How often to check for stalled agents (seconds).
    stall_threshold_s:
        Declare an agent stalled if no new output for this many seconds.
    """

    def __init__(
        self,
        state: PipelineState,
        *,
        agent_timeout_s: int = DEFAULT_AGENT_TIMEOUT_S,
        liveness_interval_s: int = DEFAULT_LIVENESS_INTERVAL_S,
        stall_threshold_s: int = DEFAULT_STALL_THRESHOLD_S,
    ) -> None:
        self.state = state
        self.agent_timeout_s = agent_timeout_s
        self.liveness_interval_s = liveness_interval_s
        self.stall_threshold_s = stall_threshold_s

        # Internal tracking
        self._agent_start_times: dict[str, float] = {}
        self._agent_last_activity: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Specialist agents
    # ------------------------------------------------------------------

    async def spawn_specialists(
        self,
        agent_configs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Spawn the four specialist agents in parallel.

        Parameters
        ----------
        agent_configs:
            Optional per-agent configuration overrides.

        Returns
        -------
        dict[str, Any]
            Mapping of agent name to its result dict.  Each result
            contains at minimum ``{"agent": name, "status": "completed"}``.
        """
        configs = agent_configs or {}
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

        for agent_name in ALL_SPECIALIST_AGENTS:
            cfg = configs.get(agent_name, {})
            task = asyncio.create_task(
                self._run_specialist(agent_name, cfg),
                name=f"specialist-{agent_name}",
            )
            tasks[agent_name] = task
            self._agent_start_times[agent_name] = time.monotonic()
            self._agent_last_activity[agent_name] = time.monotonic()

        results = await self.wait_for_agents(tasks, self.agent_timeout_s)
        return results

    async def _run_specialist(
        self,
        agent_name: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a single specialist agent.

        This is a **placeholder** implementation.  The real version will
        import from ``dd_agents.agents.specialists`` and invoke the agent
        SDK.
        """
        logger.info("Spawning specialist agent: %s (placeholder)", agent_name)
        # Placeholder: simulate agent work
        await asyncio.sleep(0)
        return {
            "agent": agent_name,
            "status": "completed",
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": 0,
            "is_error": False,
            "placeholder": True,
        }

    # ------------------------------------------------------------------
    # Judge agent
    # ------------------------------------------------------------------

    async def spawn_judge(self) -> dict[str, Any]:
        """Spawn the Judge agent.

        Returns
        -------
        dict[str, Any]
            Result dict from the Judge agent.
        """
        logger.info("Spawning Judge agent (placeholder)")
        self._agent_start_times[AGENT_JUDGE] = time.monotonic()
        self._agent_last_activity[AGENT_JUDGE] = time.monotonic()
        await asyncio.sleep(0)
        return {
            "agent": AGENT_JUDGE,
            "status": "completed",
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": 0,
            "is_error": False,
            "placeholder": True,
        }

    # ------------------------------------------------------------------
    # Reporting Lead agent
    # ------------------------------------------------------------------

    async def spawn_reporting_lead(self) -> dict[str, Any]:
        """Spawn the Reporting Lead agent.

        Returns
        -------
        dict[str, Any]
            Result dict from the Reporting Lead agent.
        """
        logger.info("Spawning Reporting Lead agent (placeholder)")
        self._agent_start_times[AGENT_REPORTING_LEAD] = time.monotonic()
        self._agent_last_activity[AGENT_REPORTING_LEAD] = time.monotonic()
        await asyncio.sleep(0)
        return {
            "agent": AGENT_REPORTING_LEAD,
            "status": "completed",
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": 0,
            "is_error": False,
            "placeholder": True,
        }

    # ------------------------------------------------------------------
    # Agent collection
    # ------------------------------------------------------------------

    async def wait_for_agents(
        self,
        tasks: dict[str, asyncio.Task[dict[str, Any]]],
        timeout: float,
    ) -> dict[str, Any]:
        """Collect results from running agent tasks, with timeout.

        Parameters
        ----------
        tasks:
            Mapping of agent name to its ``asyncio.Task``.
        timeout:
            Maximum seconds to wait for all agents.

        Returns
        -------
        dict[str, Any]
            Mapping of agent name to its result (or error dict).
        """
        results: dict[str, Any] = {}

        done, pending = await asyncio.wait(
            tasks.values(),
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )

        # Process completed tasks
        for agent_name, task in tasks.items():
            if task in done:
                exc = task.exception()
                if exc is not None:
                    logger.error("Agent %s raised: %s", agent_name, exc)
                    results[agent_name] = {
                        "agent": agent_name,
                        "status": "failed",
                        "error": str(exc),
                        "is_error": True,
                    }
                else:
                    results[agent_name] = task.result()
            else:
                # Timed out
                logger.warning("Agent %s timed out after %ds", agent_name, timeout)
                task.cancel()
                results[agent_name] = {
                    "agent": agent_name,
                    "status": "timeout",
                    "error": f"Timed out after {timeout}s",
                    "is_error": True,
                }

        return results

    # ------------------------------------------------------------------
    # Liveness monitoring
    # ------------------------------------------------------------------

    def record_activity(self, agent_name: str) -> None:
        """Record activity for an agent (called by hooks / progress tool)."""
        self._agent_last_activity[agent_name] = time.monotonic()

    def detect_stalled_agents(self) -> list[str]:
        """Return names of agents that have not produced output recently.

        An agent is considered stalled if the time since its last
        recorded activity exceeds ``stall_threshold_s``.
        """
        now = time.monotonic()
        stalled: list[str] = []
        for agent_name, last in self._agent_last_activity.items():
            if (now - last) > self.stall_threshold_s:
                stalled.append(agent_name)
        return stalled

    def is_timed_out(self, agent_name: str) -> bool:
        """Check if an agent has exceeded its wall-clock timeout."""
        start = self._agent_start_times.get(agent_name)
        if start is None:
            return False
        return (time.monotonic() - start) > self.agent_timeout_s
