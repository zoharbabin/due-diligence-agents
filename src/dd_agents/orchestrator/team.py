"""Agent team management for the forensic DD pipeline.

Provides ``AgentTeam`` -- a high-level coordinator that spawns specialist
agents in parallel, monitors their liveness, and collects results.  The
actual agent SDK integration lives in ``dd_agents.agents``; this module
wraps it with timeout / retry / liveness logic used by the orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.agents.registry import AgentRegistry
from dd_agents.utils.constants import (
    AGENT_JUDGE,
    COVERAGE_MANIFEST_JSON,
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

# Adaptive timeout parameters (Issue #42)
BASE_TIMEOUT_S: int = 1800  # 30 minutes base
PER_SUBJECT_TIMEOUT_S: int = 120  # 2 minutes per subject
MAX_TIMEOUT_S: int = 60 * 60  # 60 minutes hard cap
WARN_NO_OUTPUT_S: int = 5 * 60  # 5 minutes -- log WARNING
STALL_NO_OUTPUT_S: int = 10 * 60  # 10 minutes -- consider stalled
STALL_CANCEL_S: int = 15 * 60  # 15 minutes -- cancel stalled tasks


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
        self._completed_agents: set[str] = set()
        # Per-batch SDK turn counts: "commercial_b1" → turn_number
        self._batch_turns: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Specialist agents
    # ------------------------------------------------------------------

    async def spawn_specialists(
        self,
        agent_configs: dict[str, Any] | None = None,
        *,
        num_subjects: int = 0,
        agents: list[str] | None = None,
    ) -> dict[str, Any]:
        """Spawn specialist agents in parallel.

        Parameters
        ----------
        agent_configs:
            Optional per-agent configuration overrides.
        num_subjects:
            Number of subjects to process.  When > 0, an adaptive timeout
            is calculated (base + per-subject).  Otherwise falls back to
            the instance's ``agent_timeout_s``.
        agents:
            Optional subset of agent names to spawn.  When *None* (default),
            all four specialist agents are spawned.  Used by step 16 resume
            to skip already-completed agents (Issue #51).

        Returns
        -------
        dict[str, Any]
            Mapping of agent name to its result dict.  Each result
            contains at minimum ``{"agent": name, "status": "completed"}``.
        """
        configs = agent_configs or {}
        tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

        agent_names = agents if agents is not None else AgentRegistry.all_specialist_names()

        # Adaptive timeout (Issue #42).  Account for batch count and
        # concurrency: with parallel batches, effective sequential waves
        # = ceil(batches / concurrency).
        max_batches = 1
        for agent_name in agent_names:
            n = len(self.state.agent_prompts.get(agent_name, []))
            if n > max_batches:
                max_batches = n

        _dc = self.state.deal_config or {}
        batch_concurrency = (
            _dc.get("execution", {}).get("batch_concurrency", 6)
            if isinstance(_dc, dict)
            else getattr(getattr(_dc, "execution", None), "batch_concurrency", 6)
        )
        # Effective sequential waves = ceil(batches / concurrency)
        effective_waves = max(1, -(-max_batches // max(1, batch_concurrency)))

        timeout = (
            self.calculate_adaptive_timeout(num_subjects, num_batches=effective_waves)
            if num_subjects > 0
            else self.agent_timeout_s
        )
        logger.info(
            "Specialist timeout: %ds (subjects=%d, batches=%d, concurrency=%d, waves=%d, adaptive=%s)",
            timeout,
            num_subjects,
            max_batches,
            batch_concurrency,
            effective_waves,
            num_subjects > 0,
        )

        for agent_name in agent_names:
            cfg = configs.get(agent_name, {})
            task = asyncio.create_task(
                self._run_specialist(agent_name, cfg),
                name=f"specialist-{agent_name}",
            )
            tasks[agent_name] = task
            self._agent_start_times[agent_name] = time.monotonic()
            self._agent_last_activity[agent_name] = time.monotonic()

        # Start filesystem monitor alongside agent tasks (Issue #42).
        # The monitor also performs stall-based cancellation: if no new output
        # files appear for STALL_CANCEL_S seconds, it cancels stalled tasks.
        stop_monitor = asyncio.Event()
        monitor_task: asyncio.Task[None] | None = None
        run_dir = getattr(self.state, "run_dir", None)
        if run_dir is not None:
            findings_dir = Path(run_dir) / "findings"
            monitor_task = asyncio.create_task(
                self.monitor_agent_output(
                    findings_dir,
                    agent_names,
                    stop_event=stop_monitor,
                    agent_tasks=tasks,
                    total_subjects=len(self.state.subject_safe_names),
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
        *,
        prompt: str | None = None,
        prompts: list[str] | None = None,
        run_suffix: str = "",
    ) -> dict[str, Any]:
        """Run a single specialist agent via the agent runner SDK integration.

        Creates the appropriate specialist runner, builds the pipeline state
        dict, and invokes :meth:`BaseAgentRunner.run`.  When the agent has
        multiple batch prompts (from step 14), each batch is run as a separate
        SDK session so that no single prompt exceeds the model's context.

        Parameters
        ----------
        prompt:
            Optional single pre-built prompt string.  When *None* (default),
            the pre-built prompt(s) from ``state.agent_prompts`` are used.
        prompts:
            Optional list of pre-built prompts (one per batch).  Takes
            precedence over *prompt*.  Used by respawn to pass multiple
            batched prompts for missing subjects.
        run_suffix:
            When non-empty, appended to the agent name for output directory
            naming (e.g. ``"_pass2"`` → ``findings/legal_pass2/``).  Used
            by cross-domain targeted respawn.
        """
        from dd_agents.agents.prompt_builder import AgentType
        from dd_agents.agents.specialists import SPECIALIST_CLASSES

        agent_type_map: dict[str, AgentType] = {at.value: at for at in AgentType if at.value in SPECIALIST_CLASSES}

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

        # Apply optional per-agent config overrides.
        runner_kwargs: dict[str, Any] = {}
        if config.get("max_turns"):
            runner_kwargs["max_turns"] = int(config["max_turns"])
        if config.get("max_budget_usd"):
            runner_kwargs["max_budget_usd"] = float(config["max_budget_usd"])

        # Determine batch prompts.  ``prompts`` (list) takes precedence
        # over ``prompt`` (single string), which takes precedence over
        # pre-built batches from step 14.
        if prompts is not None:
            batch_prompts: list[str | None] = list(prompts)
        elif prompt is not None:
            batch_prompts = [prompt]
        else:
            pre_built = self.state.agent_prompts.get(agent_name, [])
            batch_prompts = list(pre_built) if pre_built else [None]

        # Concurrency limit for parallel batch execution.  Each batch
        # processes different subjects writing to different files, so
        # parallelism is safe.  Default 6 (configurable via deal-config).
        _dc2 = self.state.deal_config or {}
        concurrency = (
            _dc2.get("execution", {}).get("batch_concurrency", 6)
            if isinstance(_dc2, dict)
            else getattr(getattr(_dc2, "execution", None), "batch_concurrency", 6)
        )
        concurrency = max(1, min(concurrency, len(batch_prompts)))

        async def _run_one_batch(batch_idx: int, batch_prompt: str | None) -> dict[str, Any]:
            batch_label = (
                f"{agent_name}"
                if len(batch_prompts) == 1
                else f"{agent_name} batch {batch_idx + 1}/{len(batch_prompts)}"
            )
            logger.info("Spawning specialist agent: %s", batch_label)

            runner = runner_cls(
                project_dir=self.state.project_dir,
                run_dir=self.state.run_dir,
                run_id=self.state.run_id,
            )
            runner.batch_label = batch_label
            if runner_kwargs.get("max_turns"):
                runner.max_turns = runner_kwargs["max_turns"]
            if runner_kwargs.get("max_budget_usd"):
                runner.max_budget_usd = runner_kwargs["max_budget_usd"]

            agent_state: dict[str, Any] = {
                "subjects": self.state.subject_safe_names,
                "deal_config": self.state.deal_config,
                "prompt": batch_prompt,
            }

            # Progress callback: updates shared dict so monitor can display
            # per-agent SDK turn counts during warm-up.
            batch_key = f"{agent_name}_b{batch_idx + 1}"

            def _on_turn(_agent: str, turn: int, _key: str = batch_key) -> None:
                self._batch_turns[_key] = turn

            start_ms = time.monotonic()
            result = await runner.run(agent_state, on_turn=_on_turn)
            elapsed_ms = int((time.monotonic() - start_ms) * 1000)
            return {
                "output": result.get("output"),
                "error": result.get("error"),
                "elapsed_ms": elapsed_ms,
                "label": batch_label,
                "num_turns": result.get("num_turns", 0),
                "input_tokens_est": result.get("input_tokens_est", 0),
                "output_tokens_est": result.get("output_tokens_est", 0),
            }

        # Run batches concurrently (up to *concurrency* at a time).
        all_outputs: list[Any] = []
        total_elapsed_ms = 0
        total_turns = 0
        total_input_tokens = 0
        total_output_tokens = 0
        errors: list[str] = []

        if concurrency >= len(batch_prompts):
            # All batches fit in one wave — launch them all.
            if len(batch_prompts) > 1:
                logger.info(
                    "Agent %s: running %d batches in parallel (concurrency=%d)",
                    agent_name,
                    len(batch_prompts),
                    concurrency,
                )
            batch_tasks = [_run_one_batch(i, bp) for i, bp in enumerate(batch_prompts)]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for br in batch_results:
                if isinstance(br, BaseException):
                    errors.append(f"[{agent_name}] batch exception: {br}")
                    continue
                total_elapsed_ms = max(total_elapsed_ms, br["elapsed_ms"])
                total_turns += br.get("num_turns", 0)
                total_input_tokens += br.get("input_tokens_est", 0)
                total_output_tokens += br.get("output_tokens_est", 0)
                if br["output"]:
                    all_outputs.extend(br["output"])
                if br["error"]:
                    errors.append(f"[{br['label']}] {br['error']}")
        else:
            # Use a semaphore to limit concurrent batches.
            logger.info(
                "Agent %s: running %d batches with concurrency=%d",
                agent_name,
                len(batch_prompts),
                concurrency,
            )
            sem = asyncio.Semaphore(concurrency)

            async def _limited(idx: int, bp: str | None) -> dict[str, Any]:
                async with sem:
                    return await _run_one_batch(idx, bp)

            batch_tasks = [_limited(i, bp) for i, bp in enumerate(batch_prompts)]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            for br in batch_results:
                if isinstance(br, BaseException):
                    errors.append(f"[{agent_name}] batch exception: {br}")
                    continue
                total_elapsed_ms = max(total_elapsed_ms, br["elapsed_ms"])
                total_turns += br.get("num_turns", 0)
                total_input_tokens += br.get("input_tokens_est", 0)
                total_output_tokens += br.get("output_tokens_est", 0)
                if br["output"]:
                    all_outputs.extend(br["output"])
                if br["error"]:
                    errors.append(f"[{br['label']}] {br['error']}")

        status = "completed"
        if errors and not all_outputs:
            status = "failed"
        elif errors:
            status = "partial"

        # Estimate cost from token counts
        from dd_agents.agents.cost_tracker import _estimate_cost

        model_id = ""
        if runner_cls is not None:
            try:
                _tmp = runner_cls.__new__(runner_cls)  # type: ignore[call-overload]
                model_id = (_tmp.get_model_id() if hasattr(_tmp, "get_model_id") else "") or ""
            except Exception:  # noqa: BLE001
                pass
        cost_usd = _estimate_cost(model_id, total_input_tokens, total_output_tokens)

        return {
            "agent": agent_name,
            "status": status,
            "cost_usd": cost_usd,
            "session_id": "",
            "num_turns": total_turns,
            "duration_ms": total_elapsed_ms,
            "input_tokens_est": total_input_tokens,
            "output_tokens_est": total_output_tokens,
            "is_error": status == "failed",
            "output": all_outputs or None,
            "error": "; ".join(errors) if errors else None,
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

        # Collect telemetry from the runner (accumulated across iteration rounds)
        input_tokens = getattr(runner, "_last_session_prompt_chars", 0) // 4
        output_tokens = getattr(runner, "_last_session_output_chars", 0) // 4
        num_turns = getattr(runner, "_last_session_turns", 0)

        from dd_agents.agents.cost_tracker import _estimate_cost

        model_id = (runner.get_model_id() if hasattr(runner, "get_model_id") else "") or ""
        cost_usd = _estimate_cost(model_id, input_tokens, output_tokens)

        return {
            "agent": AGENT_JUDGE,
            "status": "completed",
            "cost_usd": cost_usd,
            "session_id": "",
            "num_turns": num_turns,
            "duration_ms": elapsed_ms,
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "is_error": False,
            "quality_scores": scores,
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
                # task.exception() raises CancelledError for cancelled tasks
                # (e.g. when the stall monitor cancels them).  Catch it
                # explicitly so we don't crash the pipeline.
                try:
                    exc = task.exception()
                except asyncio.CancelledError:
                    logger.warning("Agent %s was cancelled (stall detection or timeout)", agent_name)
                    results[agent_name] = {
                        "agent": agent_name,
                        "status": "cancelled",
                        "error": "Agent was cancelled by stall monitor",
                        "is_error": True,
                    }
                    self._completed_agents.add(agent_name)
                    continue
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
                # Mark as completed so stall detection ignores it.
                self._completed_agents.add(agent_name)
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
        recorded activity exceeds ``stall_threshold_s``.  Agents that
        have already completed are excluded.
        """
        now = time.monotonic()
        stalled: list[str] = []
        for agent_name, last in self._agent_last_activity.items():
            if agent_name in self._completed_agents:
                continue
            if (now - last) > self.stall_threshold_s:
                stalled.append(agent_name)
        return stalled

    def mark_agent_completed(self, agent_name: str) -> None:
        """Mark an agent as completed so it's excluded from stall detection."""
        self._completed_agents.add(agent_name)

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
        num_subjects: int,
        *,
        num_batches: int = 1,
        base_timeout_s: int = BASE_TIMEOUT_S,
        per_subject_s: int = PER_SUBJECT_TIMEOUT_S,
        max_timeout_s: int = MAX_TIMEOUT_S,
    ) -> int:
        """Calculate an adaptive timeout based on subjects and batch count.

        When agents run multiple batches sequentially (e.g. 4 batches of 20
        subjects each), each batch needs its own time budget.  The timeout
        is calculated per-batch and then multiplied by the batch count,
        capped at ``max_timeout_s`` (default 60 min).

        Parameters
        ----------
        num_subjects:
            Total number of subjects the agent must process.
        num_batches:
            Number of sequential batches (default 1).  Each batch gets its
            own share of per-subject time.
        base_timeout_s:
            Fixed base timeout in seconds (default 1800 = 30 min).
        per_subject_s:
            Additional seconds per subject (default 120 = 2 min).
        max_timeout_s:
            Hard cap on calculated timeout (default 3600 = 60 min).

        Returns
        -------
        int
            Calculated timeout in seconds, capped at *max_timeout_s*.
        """
        effective_batches = max(1, num_batches)
        # Each batch gets the base timeout + per-subject time for its share.
        per_batch = base_timeout_s + (num_subjects * per_subject_s) // effective_batches
        raw = per_batch * effective_batches
        return min(raw, max_timeout_s)

    # ------------------------------------------------------------------
    # Filesystem-based output monitoring (Issue #42)
    # ------------------------------------------------------------------

    @staticmethod
    def _latest_file_mtime(directory: Path) -> float | None:
        """Return the most recent mtime of any file under *directory*.

        Returns ``None`` if the directory does not exist or contains no files.
        """
        dir_path = Path(directory) if not isinstance(directory, Path) else directory
        if not dir_path.is_dir():
            return None

        latest: float | None = None
        for child in dir_path.rglob("*"):
            if child.is_file():
                mt = child.stat().st_mtime
                if latest is None or mt > latest:
                    latest = mt
        return latest

    @staticmethod
    def _count_agent_files(
        output_dir: Path,
        agent_name: str,
        *,
        since: float | None = None,
    ) -> tuple[int, int, str]:
        """Count subject JSON files for *agent_name*.

        Returns ``(total_count, modified_count, latest_filename)``.

        *modified_count* is the number of files whose mtime is >= *since*
        (i.e. files written or overwritten since the monitor started).
        When *since* is ``None``, *modified_count* equals *total_count*.

        Excludes non-subject files like ``*coverage_manifest.json`` and
        ``_temp_*`` scratch files.
        """
        agent_dir = output_dir / agent_name
        if not agent_dir.is_dir():
            return 0, 0, ""
        latest_mtime = 0.0
        latest_name = ""
        total = 0
        modified = 0
        for f in agent_dir.iterdir():
            if f.suffix != ".json":
                continue
            if f.name.startswith("_temp_") or f.name.endswith(COVERAGE_MANIFEST_JSON):
                continue
            total += 1
            mt = f.stat().st_mtime
            if since is not None and mt >= since:
                modified += 1
                # "latest" only tracks files modified in this run.
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_name = f.stem
            elif since is None:
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_name = f.stem
        if since is None:
            modified = total
        return total, modified, latest_name

    @staticmethod
    def _update_incremental_manifest(agent_dir: Path) -> None:
        """Incrementally update ``coverage_manifest.json`` from subject files on disk.

        Called by the output monitor whenever new file activity is detected.
        Reads all subject JSONs, extracts ``file_headers``, and writes an
        up-to-date manifest.  Because this runs in the orchestrator process
        (not inside the SDK session), the manifest survives agent crashes.

        The method is intentionally cheap: it only rewrites when the set of
        subject files has changed since the last write.
        """
        if not agent_dir.is_dir():
            return

        manifest_path = agent_dir / COVERAGE_MANIFEST_JSON

        # Collect current subject JSON files (exclude non-subject files).
        subject_files = sorted(
            f
            for f in agent_dir.iterdir()
            if f.suffix == ".json" and not f.name.endswith(COVERAGE_MANIFEST_JSON) and not f.name.startswith("_temp_")
        )

        if not subject_files:
            return

        # Quick staleness check: skip rewrite if manifest exists and is
        # newer than all subject files (nothing changed since last update).
        if manifest_path.exists():
            try:
                manifest_mtime = manifest_path.stat().st_mtime
                newest_subject = max(f.stat().st_mtime for f in subject_files)
                if manifest_mtime >= newest_subject:
                    return  # Manifest is up-to-date
            except OSError:
                pass  # Fall through to rebuild

        # Build manifest from subject file contents.
        files_read: list[dict[str, str]] = []
        subjects_info: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        for sf in subject_files:
            try:
                sdata = json.loads(sf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            subj_files: list[str] = []
            for fh in sdata.get("file_headers", []):
                fp = fh.get("file_path", "") if isinstance(fh, dict) else ""
                if fp and fp not in seen_paths:
                    seen_paths.add(fp)
                    files_read.append({"path": fp, "extraction_quality": "primary"})
                    subj_files.append(fp)

            subjects_info.append(
                {
                    "name": sf.stem,
                    "files_assigned": subj_files,
                    "files_processed": subj_files,
                    "status": "complete",
                }
            )

        # Merge with existing manifest (preserve agent-written fields).
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = {}

        manifest["files_read"] = files_read
        manifest["subjects"] = subjects_info
        manifest["analysis_units_completed"] = len(subjects_info)

        try:
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("Failed to write incremental manifest for %s: %s", agent_dir.name, exc)

    async def monitor_agent_output(
        self,
        output_dir: Path,
        agent_names: list[str],
        *,
        check_interval_s: float | None = None,
        warn_threshold_s: float | None = None,
        stall_threshold_s: float | None = None,
        cancel_threshold_s: float | None = None,
        stop_event: asyncio.Event | None = None,
        agent_tasks: dict[str, asyncio.Task[dict[str, Any]]] | None = None,
        total_subjects: int = 0,
    ) -> None:
        """Continuously monitor *output_dir* for new files with live progress.

        Runs until *stop_event* is set (or cancelled).  At each interval it
        counts subject output files per agent and logs a progress summary.

        - After ``warn_threshold_s`` seconds with no new files: log WARNING.
        - After ``stall_threshold_s`` seconds with no new files: log ERROR.
        - After ``cancel_threshold_s`` seconds with no new files: CANCEL
          stalled agent tasks.

        Parameters
        ----------
        output_dir:
            The directory to watch (typically ``run_dir / "findings"``).
        agent_names:
            Agent names being monitored (for logging).
        check_interval_s:
            Seconds between checks (default: 15s).
        warn_threshold_s:
            Seconds without output before WARNING (default: ``WARN_NO_OUTPUT_S``).
        stall_threshold_s:
            Seconds without output before stall declaration
            (default: ``STALL_NO_OUTPUT_S``).
        cancel_threshold_s:
            Seconds without output before cancelling stalled tasks
            (default: ``STALL_CANCEL_S``).
        stop_event:
            When set, the monitor exits its loop.
        agent_tasks:
            Mapping of agent name to asyncio.Task — used to cancel stalled
            tasks after ``cancel_threshold_s`` elapses.
        total_subjects:
            Total number of subjects being processed.
        """
        # Use a shorter interval for progress display (15s) while keeping
        # the stall detection thresholds unchanged.
        interval = check_interval_s if check_interval_s is not None else 15.0
        warn_s = warn_threshold_s if warn_threshold_s is not None else float(WARN_NO_OUTPUT_S)
        stall_s = stall_threshold_s if stall_threshold_s is not None else float(STALL_NO_OUTPUT_S)
        cancel_s = cancel_threshold_s if cancel_threshold_s is not None else float(STALL_CANCEL_S)
        evt = stop_event or asyncio.Event()

        last_seen_mtime = self._latest_file_mtime(output_dir)
        last_new_file_time = time.monotonic()
        start_time = time.monotonic()
        warned = False
        cancelled = False

        # Record wall-clock epoch for "since" tracking — files modified
        # after this timestamp are counted as actively written this run.
        monitor_epoch = time.time()

        # Use provided total_subjects; fall back to state attribute.
        if total_subjects <= 0:
            total_subjects = len(getattr(self.state, "subject_safe_names", []))

        while not evt.is_set():
            try:
                await asyncio.wait_for(evt.wait(), timeout=interval)
                break  # Event was set -- stop monitoring.
            except TimeoutError:
                pass  # Normal: interval elapsed without stop signal.

            # Build progress summary for each agent.
            elapsed_total = time.monotonic() - start_time
            elapsed_min = int(elapsed_total) // 60
            elapsed_sec = int(elapsed_total) % 60
            parts: list[str] = []
            for name in agent_names:
                total, modified, latest = self._count_agent_files(
                    output_dir,
                    name,
                    since=monitor_epoch,
                )
                # Aggregate SDK turns across all batches for this agent.
                agent_turns = sum(v for k, v in self._batch_turns.items() if k.startswith(f"{name}_"))
                if modified == 0:
                    if agent_turns > 0:
                        parts.append(f"{name}: analyzing ({agent_turns} turns)")
                    else:
                        parts.append(f"{name}: starting up")
                else:
                    pct = f" ({modified * 100 // total_subjects}%)" if total_subjects > 0 else ""
                    parts.append(f"{name}: {modified}/{total_subjects} done{pct} | latest: {latest}")

            progress_line = " | ".join(parts)
            logger.info(
                "Agent progress [%02d:%02d]: %s",
                elapsed_min,
                elapsed_sec,
                progress_line,
            )

            # Stall detection and cancellation.
            # Two activity signals: (a) new files on disk, (b) SDK turn advancement.
            # An agent reading large files may go minutes without writing output
            # but is still actively working if its turn count is advancing.
            current_mtime = self._latest_file_mtime(output_dir)
            file_activity = current_mtime is not None and (last_seen_mtime is None or current_mtime > last_seen_mtime)

            # Check if any non-completed agent has advanced its SDK turn count.
            turn_activity = False
            for name in agent_names:
                if name in self._completed_agents:
                    continue
                current_turns = sum(v for k, v in self._batch_turns.items() if k.startswith(f"{name}_"))
                prev_key = f"_prev_turns_{name}"
                prev_turns = getattr(self, prev_key, 0)
                if current_turns > prev_turns:
                    turn_activity = True
                    setattr(self, prev_key, current_turns)

            if file_activity or turn_activity:
                if file_activity:
                    last_seen_mtime = current_mtime
                    # Incrementally update coverage manifests so they
                    # survive SDK crashes.  Runs in the orchestrator
                    # process — immune to agent-side failures.
                    for name in agent_names:
                        self._update_incremental_manifest(output_dir / name)
                last_new_file_time = time.monotonic()
                warned = False
                cancelled = False
                for name in agent_names:
                    self.record_activity(name)
                continue

            elapsed_since_last = time.monotonic() - last_new_file_time

            # Per-agent completion tracking: mark agents as completed when
            # they've written files for all (or nearly all) subjects.
            # This prevents the global stall detector from cancelling
            # agents that finished early while others are still working.
            if total_subjects > 0:
                for name in agent_names:
                    if name in self._completed_agents:
                        continue
                    total_files, _, _ = self._count_agent_files(
                        output_dir,
                        name,
                        since=monitor_epoch,
                    )
                    # Mark done when agent has covered all subjects (±1 for
                    # rounding / off-by-one in agent-side counting).
                    if total_files >= total_subjects:
                        logger.info(
                            "Agent %s appears complete: %d/%d files written",
                            name,
                            total_files,
                            total_subjects,
                        )
                        self.mark_agent_completed(name)

            # Cancel stalled tasks after cancel_threshold_s (default 15 min).
            # Only cancel agents that haven't finished writing their output.
            if elapsed_since_last >= cancel_s and not cancelled and agent_tasks:
                cancelled = True
                stalled = self.detect_stalled_agents()
                if stalled:
                    logger.error(
                        "CANCELLING stalled agents (no new output for %.0fs): %s",
                        elapsed_since_last,
                        ", ".join(stalled),
                    )
                    for name in stalled:
                        task = agent_tasks.get(name)
                        if task is not None and not task.done():
                            logger.warning("Cancelling task for stalled agent: %s", name)
                            task.cancel()
                    # Only stop if ALL remaining agents are stalled.
                    # If some agents are still active, let them continue.
                    active_agents = [n for n in agent_names if n not in self._completed_agents and n not in stalled]
                    if not active_agents:
                        evt.set()
                        break
                    else:
                        logger.info(
                            "Some agents still active after cancellation: %s -- continuing monitor",
                            ", ".join(active_agents),
                        )
                        # Reset stall timer for remaining active agents.
                        last_new_file_time = time.monotonic()
                        cancelled = False
            elif elapsed_since_last >= stall_s:
                stalled = self.detect_stalled_agents()
                if stalled:
                    logger.error(
                        "Agents appear stalled (no new output for %.0fs): %s",
                        elapsed_since_last,
                        ", ".join(stalled),
                    )
            elif elapsed_since_last >= warn_s and not warned:
                warned = True
                logger.warning(
                    "No new output files for %.0fs in %s (agents: %s)",
                    elapsed_since_last,
                    output_dir,
                    ", ".join(agent_names),
                )

        # Final manifest update when monitor exits — ensures manifests
        # reflect all subject files written before the coverage gate runs.
        for name in agent_names:
            self._update_incremental_manifest(output_dir / name)
