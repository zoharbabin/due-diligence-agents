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
    from pathlib import Path

    from dd_agents.orchestrator.state import PipelineState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_AGENT_TIMEOUT_S: int = 30 * 60  # 30 minutes per agent
DEFAULT_LIVENESS_INTERVAL_S: int = 5 * 60  # check every 5 minutes
DEFAULT_STALL_THRESHOLD_S: int = 10 * 60  # 10 minutes with no output

# Adaptive timeout parameters (Issue #42)
BASE_TIMEOUT_S: int = 1800  # 30 minutes base
PER_CUSTOMER_TIMEOUT_S: int = 120  # 2 minutes per customer
WARN_NO_OUTPUT_S: int = 5 * 60  # 5 minutes -- log WARNING
STALL_NO_OUTPUT_S: int = 10 * 60  # 10 minutes -- consider stalled


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
        *,
        num_customers: int = 0,
    ) -> dict[str, Any]:
        """Spawn the four specialist agents in parallel.

        Parameters
        ----------
        agent_configs:
            Optional per-agent configuration overrides.
        num_customers:
            Number of customers to process.  When > 0, an adaptive timeout
            is calculated (base + per-customer).  Otherwise falls back to
            the instance's ``agent_timeout_s``.

        Returns
        -------
        dict[str, Any]
            Mapping of agent name to its result dict.  Each result
            contains at minimum ``{"agent": name, "status": "completed"}``.
        """
        configs = agent_configs or {}
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

        # Adaptive timeout (Issue #42)
        timeout = self.calculate_adaptive_timeout(num_customers) if num_customers > 0 else self.agent_timeout_s
        logger.info(
            "Specialist timeout: %ds (customers=%d, adaptive=%s)",
            timeout,
            num_customers,
            num_customers > 0,
        )

        for agent_name in ALL_SPECIALIST_AGENTS:
            cfg = configs.get(agent_name, {})
            task = asyncio.create_task(
                self._run_specialist(agent_name, cfg),
                name=f"specialist-{agent_name}",
            )
            tasks[agent_name] = task
            self._agent_start_times[agent_name] = time.monotonic()
            self._agent_last_activity[agent_name] = time.monotonic()

        # Start filesystem monitor alongside agent tasks (Issue #42).
        stop_monitor = asyncio.Event()
        monitor_task: asyncio.Task[None] | None = None
        run_dir = getattr(self.state, "run_dir", None)
        if run_dir is not None:
            from pathlib import Path as _Path

            findings_dir = _Path(str(run_dir)) / "findings"
            monitor_task = asyncio.create_task(
                self.monitor_agent_output(
                    findings_dir,
                    list(ALL_SPECIALIST_AGENTS),
                    stop_event=stop_monitor,
                ),
                name="agent-output-monitor",
            )

        try:
            results = await self.wait_for_agents(tasks, timeout)
        finally:
            # Stop the monitor after agents complete.
            stop_monitor.set()
            if monitor_task is not None:
                try:
                    await asyncio.wait_for(monitor_task, timeout=5.0)
                except (TimeoutError, asyncio.CancelledError):
                    monitor_task.cancel()

        return results

    async def _run_specialist(
        self,
        agent_name: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a single specialist agent via the agent runner SDK integration.

        Creates the appropriate specialist runner, builds the pipeline state
        dict, and invokes :meth:`BaseAgentRunner.run`.
        """
        from dd_agents.agents.prompt_builder import AgentType
        from dd_agents.agents.specialists import SPECIALIST_CLASSES

        agent_type_map: dict[str, AgentType] = {
            "legal": AgentType.LEGAL,
            "finance": AgentType.FINANCE,
            "commercial": AgentType.COMMERCIAL,
            "producttech": AgentType.PRODUCTTECH,
        }

        agent_type = agent_type_map.get(agent_name)
        if agent_type is None or agent_type not in SPECIALIST_CLASSES:
            logger.error("Unknown specialist agent: %s", agent_name)
            return {
                "agent": agent_name,
                "status": "failed",
                "error": f"Unknown specialist agent: {agent_name}",
                "is_error": True,
            }

        runner_cls = SPECIALIST_CLASSES[agent_type]
        runner = runner_cls(
            project_dir=self.state.project_dir,
            run_dir=self.state.run_dir,
            run_id=self.state.run_id,
        )

        # Apply optional per-agent config overrides.
        if config.get("max_turns"):
            runner.max_turns = int(config["max_turns"])
        if config.get("max_budget_usd"):
            runner.max_budget_usd = float(config["max_budget_usd"])

        logger.info("Spawning specialist agent: %s", agent_name)

        # Build state dict for the agent runner from pipeline state.
        agent_state: dict[str, Any] = {
            "customers": self.state.customer_safe_names,
            "deal_config": self.state.deal_config,
        }

        start_ms = time.monotonic()
        result = await runner.run(agent_state)
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        return {
            "agent": agent_name,
            "status": "completed" if result.get("status") == "success" else result.get("status", "failed"),
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": elapsed_ms,
            "is_error": result.get("status") != "success",
            "output": result.get("output"),
            "error": result.get("error"),
        }

    # ------------------------------------------------------------------
    # Judge agent
    # ------------------------------------------------------------------

    async def spawn_judge(self) -> dict[str, Any]:
        """Spawn the Judge agent with the iteration loop.

        Returns
        -------
        dict[str, Any]
            Result dict from the Judge agent.
        """
        from dd_agents.agents.judge import JudgeAgent

        logger.info("Spawning Judge agent")
        self._agent_start_times[AGENT_JUDGE] = time.monotonic()
        self._agent_last_activity[AGENT_JUDGE] = time.monotonic()

        runner = JudgeAgent(
            project_dir=self.state.project_dir,
            run_dir=self.state.run_dir,
            run_id=self.state.run_id,
        )

        agent_state: dict[str, Any] = {
            "findings_dir": str(self.state.run_dir / "findings"),
            "deal_config": self.state.deal_config,
        }

        start_ms = time.monotonic()
        scores = await runner.run_with_iteration(agent_state)
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        return {
            "agent": AGENT_JUDGE,
            "status": "completed",
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": elapsed_ms,
            "is_error": False,
            "quality_scores": scores,
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
        from dd_agents.agents.reporting_lead import ReportingLeadAgent

        logger.info("Spawning Reporting Lead agent")
        self._agent_start_times[AGENT_REPORTING_LEAD] = time.monotonic()
        self._agent_last_activity[AGENT_REPORTING_LEAD] = time.monotonic()

        runner = ReportingLeadAgent(
            project_dir=self.state.project_dir,
            run_dir=self.state.run_dir,
            run_id=self.state.run_id,
        )

        agent_state: dict[str, Any] = {
            "findings_dir": str(self.state.run_dir / "findings"),
            "deal_config": self.state.deal_config,
        }

        start_ms = time.monotonic()
        result = await runner.run_reporting(agent_state)
        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        return {
            "agent": AGENT_REPORTING_LEAD,
            "status": "completed" if result.get("status") == "success" else result.get("status", "failed"),
            "cost_usd": 0.0,
            "session_id": "",
            "num_turns": 0,
            "duration_ms": elapsed_ms,
            "is_error": result.get("status") != "success",
            "output": result.get("output"),
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

    # ------------------------------------------------------------------
    # Adaptive timeout (Issue #42)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_adaptive_timeout(
        num_customers: int,
        *,
        base_timeout_s: int = BASE_TIMEOUT_S,
        per_customer_s: int = PER_CUSTOMER_TIMEOUT_S,
    ) -> int:
        """Calculate an adaptive timeout based on the number of customers.

        Parameters
        ----------
        num_customers:
            How many customers the agent must process.
        base_timeout_s:
            Fixed base timeout in seconds (default 1800 = 30 min).
        per_customer_s:
            Additional seconds per customer (default 120 = 2 min).

        Returns
        -------
        int
            Calculated timeout in seconds.
        """
        return base_timeout_s + (num_customers * per_customer_s)

    # ------------------------------------------------------------------
    # Filesystem-based output monitoring (Issue #42)
    # ------------------------------------------------------------------

    @staticmethod
    def _latest_file_mtime(directory: Path) -> float | None:
        """Return the most recent mtime of any file under *directory*.

        Returns ``None`` if the directory does not exist or contains no files.
        """
        from pathlib import Path as _Path

        dir_path = _Path(directory) if not isinstance(directory, _Path) else directory
        if not dir_path.is_dir():
            return None

        latest: float | None = None
        for child in dir_path.rglob("*"):
            if child.is_file():
                mt = child.stat().st_mtime
                if latest is None or mt > latest:
                    latest = mt
        return latest

    async def monitor_agent_output(
        self,
        output_dir: Path,
        agent_names: list[str],
        *,
        check_interval_s: float | None = None,
        warn_threshold_s: float | None = None,
        stall_threshold_s: float | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuously monitor *output_dir* for new files.

        Runs until *stop_event* is set (or cancelled).  At each interval it
        checks whether any new files have appeared.  If not:

        - After ``warn_threshold_s`` seconds with no new files: log WARNING.
        - After ``stall_threshold_s`` seconds with no new files: log ERROR
          and update ``_agent_last_activity`` to reflect the stall.

        Parameters
        ----------
        output_dir:
            The directory to watch (typically ``run_dir / "findings"``).
        agent_names:
            Agent names being monitored (for logging).
        check_interval_s:
            Seconds between checks (default: ``liveness_interval_s``).
        warn_threshold_s:
            Seconds without output before WARNING (default: ``WARN_NO_OUTPUT_S``).
        stall_threshold_s:
            Seconds without output before stall declaration
            (default: ``STALL_NO_OUTPUT_S``).
        stop_event:
            When set, the monitor exits its loop.
        """
        interval = check_interval_s if check_interval_s is not None else float(self.liveness_interval_s)
        warn_s = warn_threshold_s if warn_threshold_s is not None else float(WARN_NO_OUTPUT_S)
        stall_s = stall_threshold_s if stall_threshold_s is not None else float(STALL_NO_OUTPUT_S)
        evt = stop_event or asyncio.Event()

        last_seen_mtime = self._latest_file_mtime(output_dir)
        last_new_file_time = time.monotonic()
        warned = False

        while not evt.is_set():
            try:
                await asyncio.wait_for(evt.wait(), timeout=interval)
                break  # Event was set -- stop monitoring.
            except TimeoutError:
                pass  # Normal: interval elapsed without stop signal.

            current_mtime = self._latest_file_mtime(output_dir)
            if current_mtime is not None and (last_seen_mtime is None or current_mtime > last_seen_mtime):
                # New file(s) detected -- update tracking.
                last_seen_mtime = current_mtime
                last_new_file_time = time.monotonic()
                warned = False
                for name in agent_names:
                    self.record_activity(name)
                continue

            elapsed = time.monotonic() - last_new_file_time

            if elapsed >= stall_s:
                stalled = self.detect_stalled_agents()
                if stalled:
                    logger.error(
                        "Agents appear stalled (no new output for %.0fs): %s",
                        elapsed,
                        ", ".join(stalled),
                    )
            elif elapsed >= warn_s and not warned:
                warned = True
                logger.warning(
                    "No new output files for %.0fs in %s (agents: %s)",
                    elapsed,
                    output_dir,
                    ", ".join(agent_names),
                )
