"""Base agent runner -- abstract class for all agent types.

Provides common spawn logic, prompt construction delegation, output parsing,
timeout monitoring, and error handling.  Subclassed by each concrete agent.
"""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dd_agents.models.config import DealConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK import -- graceful degradation when not installed
# ---------------------------------------------------------------------------

_HAS_SDK: bool = False
try:
    from claude_agent_sdk import (
        AssistantMessage as _AssistantMessage,
    )
    from claude_agent_sdk import (
        ClaudeAgentOptions as _ClaudeAgentOptions,
    )
    from claude_agent_sdk import (
        ResultMessage as _ResultMessage,
    )
    from claude_agent_sdk import (
        TextBlock as _TextBlock,
    )
    from claude_agent_sdk import (
        query as _query,
    )

    _HAS_SDK = True
except ImportError:
    logger.debug("claude_agent_sdk not installed -- agent spawning will return empty output")


class BaseAgentRunner(ABC):
    """Abstract base for every agent runner.

    Subclasses must implement three abstract methods (``get_agent_name``,
    ``get_system_prompt``, ``get_tools``).  ``get_model_id`` and
    ``build_prompt`` have sensible defaults that can be overridden.
    The ``run`` method orchestrates a single agent invocation:
    build prompt -> spawn (placeholder) -> parse output.
    """

    # Configurable defaults -- subclasses may override via class attributes.
    timeout_seconds: int = 600
    max_turns: int = 200
    max_budget_usd: float = 5.0

    # Set by the orchestrator to identify which batch this runner is
    # processing.  When non-empty, all log lines use this label instead
    # of the plain agent name so concurrent batches are distinguishable.
    batch_label: str = ""

    # Hard-limit multiplier: if an agent exceeds max_turns * HARD_LIMIT_MULTIPLIER,
    # the session is forcibly cancelled.  The gap between soft (max_turns) and hard
    # allows agents that are legitimately finishing work (writing final files) to
    # complete gracefully, while guaranteeing termination before costs spiral.
    HARD_LIMIT_MULTIPLIER: int = 3

    # Batch sizing -- subclasses may override for agents that need
    # smaller batches (e.g., FinanceAgent processes dense spreadsheets).
    max_customers_per_batch: int = 20
    max_tokens_per_batch: int = 40_000

    # Minimum SDK message buffer (bytes).  The actual value is computed
    # dynamically from the largest extracted-text file in the data room.
    _MIN_BUFFER_BYTES: int = 5 * 1024 * 1024  # 5 MB floor

    def __init__(
        self,
        project_dir: Path,
        run_dir: Path,
        run_id: str,
        deal_config: DealConfig | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.run_dir = run_dir
        self.run_id = run_id
        self.deal_config = deal_config

    # ------------------------------------------------------------------
    # Abstract interface -- every concrete agent must implement these.
    # ------------------------------------------------------------------

    @abstractmethod
    def get_agent_name(self) -> str:
        """Return the canonical agent name (e.g. ``'legal'``)."""

    def get_model_id(self) -> str | None:
        """Return the LLM model identifier for this agent.

        Checks ``deal_config.agent_models`` for profile-based or per-agent
        override model selection (Issue #129).  Returns ``None`` as fallback
        so the SDK uses its own configured model.
        """
        if self.deal_config is not None:
            agent_models = getattr(self.deal_config, "agent_models", None)
            if agent_models is not None and hasattr(agent_models, "resolve_model"):
                result: str | None = agent_models.resolve_model(self.get_agent_name())
                return result
        return None

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system-level preamble injected before the user prompt."""

    @abstractmethod
    def get_tools(self) -> list[str]:
        """Return the list of tool names available to this agent."""

    def _compute_buffer_size(self) -> int:
        """Compute SDK message buffer from the largest extracted-text file.

        The ``claude_agent_sdk`` streams JSON messages on stdout.  When an
        agent reads a file via a tool call, the entire file content appears
        inside a single JSON message.  The buffer must be large enough to
        hold that message (file bytes + JSON/base64 encoding overhead).

        Returns 3× the largest ``.txt`` file in the text directory, with
        a floor of :attr:`_MIN_BUFFER_BYTES`.
        """
        text_dir = Path(self.project_dir) / "_dd" / "forensic-dd" / "index" / "text"
        if not text_dir.is_dir():
            return self._MIN_BUFFER_BYTES

        max_size = 0
        for f in text_dir.iterdir():
            if f.suffix in (".md", ".txt") and f.is_file():
                try:
                    size = f.stat().st_size
                    if size > max_size:
                        max_size = size
                except OSError:
                    continue

        # 3× for JSON encoding overhead (escaping, base64, wrapper)
        computed = max_size * 3
        return max(computed, self._MIN_BUFFER_BYTES)

    def _raw_output_path(self) -> Path:
        """Return the path for saving raw agent output text."""
        return Path(self.run_dir) / "agent_output" / f"{self.get_agent_name()}_raw.txt"

    # ------------------------------------------------------------------
    # Main execution entry-point
    # ------------------------------------------------------------------

    async def run(
        self,
        state: dict[str, Any],
        *,
        on_turn: Any | None = None,
    ) -> dict[str, Any]:
        """Build prompt, spawn the agent, collect and return structured output.

        Parameters
        ----------
        state:
            Mutable pipeline state dict.  Keys vary by agent type.
        on_turn:
            Optional callback ``(agent_name: str, turn: int) -> None`` invoked
            periodically during the SDK session for progress tracking.

        Returns
        -------
        dict with at minimum ``agent_name``, ``status``, and ``output``.
        """
        agent_name = self.get_agent_name()
        result: dict[str, Any] = {
            "agent_name": agent_name,
            "status": "pending",
            "output": None,
            "error": None,
            "elapsed_seconds": 0.0,
        }

        start = time.monotonic()
        try:
            # Use pre-built prompt from pipeline step 14 if available.
            # Fall back to build_prompt() for tests / standalone invocations.
            prompt = state.get("prompt") or self.build_prompt(state)

            customers = state.get("customers", [])
            raw_output = await self._spawn_agent(
                prompt,
                on_turn=on_turn,
                expected_customers=len(customers),
            )

            # Persist raw output for diagnostics (always, not just on failure).
            raw_output_path = self._raw_output_path()
            parsed = self._parse_agent_output(raw_output, raw_output_path=raw_output_path)
            result["output"] = parsed

            if raw_output.strip():
                # Agent ran and produced text output.  Specialist agents write
                # findings as files on disk — their text stream is commentary,
                # not structured JSON.  Status is success; the coverage gate
                # (step 17) verifies actual file output.
                result["status"] = "success"
            else:
                # Agent returned empty — SDK may have failed silently.
                result["status"] = "error"
                result["error"] = f"Agent {agent_name} produced no output"
                logger.warning(result["error"])
        except TimeoutError:
            result["status"] = "timeout"
            result["error"] = f"Agent {agent_name} exceeded timeout of {self.timeout_seconds}s"
            logger.error(result["error"])
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("Agent %s failed", agent_name)
        finally:
            elapsed = time.monotonic() - start
            result["elapsed_seconds"] = elapsed

            # Telemetry: token estimates from session stats (chars // 4 heuristic)
            prompt_chars = getattr(self, "_last_session_prompt_chars", 0)
            output_chars = getattr(self, "_last_session_output_chars", 0)
            turns = getattr(self, "_last_session_turns", 0)
            result["num_turns"] = turns
            result["input_tokens_est"] = prompt_chars // 4
            result["output_tokens_est"] = output_chars // 4
            result["duration_ms"] = int(elapsed * 1000)

        return result

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Delegate prompt construction to :class:`PromptBuilder`.

        Default implementation calls ``build_specialist_prompt`` which is
        correct for all four specialist agents.  Judge overrides this
        to call its own builder method.
        """
        from dd_agents.agents.prompt_builder import PromptBuilder

        builder = PromptBuilder(
            project_dir=self.project_dir,
            run_dir=self.run_dir,
            run_id=self.run_id,
        )
        return builder.build_specialist_prompt(
            agent_name=self.get_agent_name(),
            customers=state.get("customers", []),
            reference_files=state.get("reference_files"),
            deal_config=state.get("deal_config") or self.deal_config,
        )

    # ------------------------------------------------------------------
    # Agent spawn -- SDK integration
    # ------------------------------------------------------------------

    def get_agent_type(self) -> str:
        """Return the agent type for tool/hook configuration.

        Override in subclasses that need different tool sets (e.g. ``"judge"``).
        Default is ``"specialist"`` which gives access to all custom DD tools.
        """
        return "specialist"

    async def _spawn_agent(
        self,
        prompt: str,
        *,
        on_turn: Any | None = None,
        expected_customers: int = 0,
    ) -> str:
        """Spawn the agent via ``claude_agent_sdk.query()`` and return raw text.

        Collects all :class:`TextBlock` content from :class:`AssistantMessage`
        objects yielded by the SDK's async generator.  If the SDK is not
        installed (e.g. in unit-test environments), logs a warning and returns
        an empty string so callers degrade gracefully.

        Parameters
        ----------
        prompt:
            The fully-assembled user prompt for the agent.
        on_turn:
            Optional callback ``(agent_name: str, turn: int) -> None`` invoked
            every 5 SDK messages.  Used by the orchestrator to track per-batch
            progress for the live monitor.
        expected_customers:
            Number of customer JSONs the agent should produce.  Used to
            configure stop hooks.

        Returns
        -------
        str
            Concatenated text output from the agent, or ``""`` when the SDK
            is unavailable or the agent produces no text.
        """
        if not _HAS_SDK:
            logger.warning(
                "claude_agent_sdk not available -- returning empty output for agent %s",
                self.get_agent_name(),
            )
            return ""

        # Build system prompt with hard anti-sub-agent constraint.
        # The system prompt is the most authoritative prompt layer — the LLM
        # treats it as developer instructions.  User-prompt-level rules were
        # observed to be ignored, so this constraint MUST be in the system prompt.
        base_system = self.get_system_prompt()
        system_prompt = (
            f"{base_system}\n\n"
            "CRITICAL CONSTRAINTS (NEVER VIOLATE):\n"
            "1. You do NOT have access to the Agent tool. NEVER attempt to spawn "
            "sub-agents, background agents, or parallel agents. You are a single "
            "agent — process all customers yourself, sequentially, in this session.\n"
            "2. You do NOT have access to the Bash tool. Do not attempt shell commands.\n"
            "3. Do NOT read or validate existing output files before writing. Write "
            "fresh output directly. If a file exists at the output path, overwrite it.\n"
            "4. Do NOT summarize progress or produce status reports. Write JSON files "
            "and move to the next customer immediately.\n"
            "5. Your final output message MUST be a single valid JSON object. Do not "
            "wrap it in markdown fences (no ```json). Do not include explanatory text "
            "before or after the JSON. Output ONLY the JSON object."
        )

        # Build hooks and MCP server for the agent
        from dd_agents.hooks.factory import build_hooks_for_agent
        from dd_agents.tools.mcp_server import _build_runtime_context, build_mcp_server

        hooks = build_hooks_for_agent(
            agent_name=self.get_agent_name(),
            run_dir=self.run_dir,
            project_dir=self.project_dir,
            expected_customers=expected_customers,
        )

        runtime_ctx = _build_runtime_context(
            project_dir=self.project_dir,
            run_dir=self.run_dir,
        )
        mcp_server = build_mcp_server(agent_type=self.get_agent_type(), **runtime_ctx)

        # Build options dict — only include hooks/mcp_servers when available
        options_kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "model": self.get_model_id(),
            "max_turns": self.max_turns,
            "max_budget_usd": self.max_budget_usd,
            "permission_mode": "bypassPermissions",
            "cwd": str(self.project_dir),
            "allowed_tools": self.get_tools(),
            "max_buffer_size": self._compute_buffer_size(),
        }
        if hooks is not None:
            options_kwargs["hooks"] = hooks
        if mcp_server is not None:
            options_kwargs["mcp_servers"] = {"dd_tools": mcp_server}

        options = _ClaudeAgentOptions(**options_kwargs)

        agent_name = self.batch_label or self.get_agent_name()
        hard_limit = self.max_turns * self.HARD_LIMIT_MULTIPLIER
        prompt_tokens = len(prompt) // 4
        buffer_mb = self._compute_buffer_size() / (1024 * 1024)
        logger.info(
            "Agent %s: starting SDK session "
            "(prompt ~%dK tokens, buffer %.1f MB, max_turns=%d, hard_limit=%d, budget=$%.2f)",
            agent_name,
            prompt_tokens // 1000,
            buffer_mb,
            self.max_turns,
            hard_limit,
            self.max_budget_usd,
        )

        text_parts: list[str] = []
        msg_count = 0
        exceeded_soft = False
        try:
            async for message in _query(prompt=prompt, options=options):
                msg_count += 1

                # --- Turn enforcement (defense-in-depth, Issue #96) ---
                # Soft limit: warn once when max_turns is exceeded.
                if not exceeded_soft and msg_count > self.max_turns:
                    exceeded_soft = True
                    logger.warning(
                        "Agent %s exceeded soft limit (max_turns=%d) at message %d "
                        "— %d text parts collected (%d chars). "
                        "Grace period until hard limit at %d.",
                        agent_name,
                        self.max_turns,
                        msg_count,
                        len(text_parts),
                        sum(len(p) for p in text_parts),
                        hard_limit,
                    )
                # Hard limit: break to prevent runaway.
                # The async generator from _query() is created and consumed
                # within the same asyncio task, so breaking the async-for
                # loop triggers a clean aclose() on the generator.  Partial
                # output collected so far is preserved and returned.
                if msg_count > hard_limit:
                    logger.error(
                        "Agent %s hit hard limit (%d messages, max_turns=%d). "
                        "Stopping to prevent runaway. "
                        "Partial output: %d parts, %d chars.",
                        agent_name,
                        msg_count,
                        self.max_turns,
                        len(text_parts),
                        sum(len(p) for p in text_parts),
                    )
                    break

                # Periodic progress: log every 10 turns, callback every 5.
                if on_turn is not None and msg_count % 5 == 0:
                    on_turn(agent_name, msg_count)
                if msg_count % 10 == 0:
                    logger.info(
                        "Agent %s: SDK turn %d/%d",
                        agent_name,
                        msg_count,
                        self.max_turns,
                    )

                if isinstance(message, _AssistantMessage):
                    for block in message.content:
                        if isinstance(block, _TextBlock):
                            text_parts.append(block.text)
                elif isinstance(message, _ResultMessage):
                    if message.is_error:
                        logger.error(
                            "Agent %s SDK error (msg #%d): %s",
                            agent_name,
                            msg_count,
                            message.result,
                        )
                    else:
                        logger.info(
                            "Agent %s completed (msg #%d): %s",
                            agent_name,
                            msg_count,
                            str(message.result)[:200] if message.result else "OK",
                        )
                    # Do NOT break here — breaking an anyio-backed async
                    # generator from an asyncio.create_task triggers
                    # "Attempted to exit cancel scope in a different task".
                    # ResultMessage is terminal; the loop ends naturally.
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Agent %s SDK call failed: %s — returning partial output (%d parts collected)",
                agent_name,
                exc,
                len(text_parts),
            )

        total_text = sum(len(p) for p in text_parts)
        logger.info(
            "Agent %s: session ended after %d messages, %d text chars collected%s",
            agent_name,
            msg_count,
            total_text,
            " (exceeded soft limit)" if exceeded_soft else "",
        )

        # Store telemetry for the caller to pick up
        self._last_session_turns = msg_count
        self._last_session_output_chars = total_text
        self._last_session_prompt_chars = len(prompt)

        return "\n".join(text_parts)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _repair_json_text(text: str) -> str:
        """Apply heuristic repairs to malformed JSON text.

        Repairs applied (in order):
        1. Strip UTF-8 BOM prefix.
        2. Strip markdown code fences (``\\`\\`\\`json ... \\`\\`\\```).
        3. Remove trailing commas before ``}`` or ``]``.
        """
        # 1. Strip BOM.
        if text.startswith("\ufeff"):
            text = text[1:]

        # 2. Strip markdown fences (outermost only).
        fence_pattern = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)
        fence_match = fence_pattern.match(text.strip())
        if fence_match:
            text = fence_match.group(1)

        # 3. Remove trailing commas before closing braces/brackets.
        text = re.sub(r",\s*([}\]])", r"\1", text)

        return text

    @staticmethod
    def _parse_agent_output(
        raw_output: str,
        *,
        raw_output_path: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Extract structured JSON objects from free-form agent text output.

        The method looks for top-level JSON objects or arrays embedded in the
        agent's response (possibly surrounded by markdown fences or prose).

        Parameters
        ----------
        raw_output:
            The raw text from the agent.
        raw_output_path:
            Optional filesystem path.  When provided **and** parsing fails,
            the raw output is written to this path for later inspection.

        Returns a list of dicts.  If no valid JSON is found, returns ``[]``.
        """
        if not raw_output or not raw_output.strip():
            logger.debug("Agent output is empty or whitespace-only")
            return []

        # Pre-process: strip BOM so all downstream strategies see clean text.
        cleaned = raw_output
        if cleaned.startswith("\ufeff"):
            cleaned = cleaned[1:]

        results: list[dict[str, Any]] = []

        # Strategy 1: try entire output as JSON.
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict):
                results.append(data)
            return results
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug(
                "Strategy 1 (full JSON parse) failed for output of %d chars: %s",
                len(raw_output),
                exc,
            )

        # Strategy 2: extract from markdown code fences.
        fence_pattern = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)
        for match in fence_pattern.finditer(cleaned):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Strategy 2 (fence extraction) failed for fenced block of %d chars: %s",
                    len(match.group(1)),
                    exc,
                )
                continue

        if results:
            return results

        # Strategy 3: find standalone JSON objects via brace matching.
        brace_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
        for match in brace_pattern.finditer(cleaned):
            try:
                data = json.loads(match.group(0))
                results.append(data)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Strategy 3 (brace matching) failed for candidate of %d chars: %s",
                    len(match.group(0)),
                    exc,
                )
                continue

        if results:
            return results

        # Strategy 4 (repair): apply heuristic fixes and retry.
        repaired = BaseAgentRunner._repair_json_text(cleaned)
        if repaired != cleaned:
            try:
                data = json.loads(repaired)
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
                return results
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Strategy 4 (JSON repair) failed for output of %d chars: %s",
                    len(raw_output),
                    exc,
                )

        # All strategies exhausted -- log and optionally persist raw output.
        if raw_output.strip():
            preview = raw_output.strip()[:500]
            logger.error(
                "Agent output contained no parseable JSON (%d chars). Preview:\n%s",
                len(raw_output),
                preview,
            )
            if raw_output_path is not None:
                try:
                    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_output_path.write_text(raw_output, encoding="utf-8")
                    logger.info("Raw agent output saved to %s", raw_output_path)
                except OSError as exc:
                    logger.warning("Failed to save raw output to %s: %s", raw_output_path, exc)

        return results
