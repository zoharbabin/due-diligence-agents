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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

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

        Returns ``None`` so the SDK uses its own configured model.
        Subclasses may override to force a specific model.
        """
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
        from pathlib import Path as _Path

        text_dir = _Path(self.project_dir) / "_dd" / "forensic-dd" / "index" / "text"
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
        from pathlib import Path as _Path

        return _Path(self.run_dir) / "agent_output" / f"{self.get_agent_name()}_raw.txt"

    # ------------------------------------------------------------------
    # Main execution entry-point
    # ------------------------------------------------------------------

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Build prompt, spawn the agent, collect and return structured output.

        Parameters
        ----------
        state:
            Mutable pipeline state dict.  Keys vary by agent type.

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

            # Placeholder: actual SDK integration would call ``query()`` here.
            raw_output = await self._spawn_agent(prompt)

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
            result["elapsed_seconds"] = time.monotonic() - start

        return result

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def build_prompt(self, state: dict[str, Any]) -> str:
        """Delegate prompt construction to :class:`PromptBuilder`.

        Default implementation calls ``build_specialist_prompt`` which is
        correct for all four specialist agents.  Judge and ReportingLead
        override this to call their own builder methods.
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
            text_dir=state.get("text_dir"),
        )

    # ------------------------------------------------------------------
    # Agent spawn -- SDK integration
    # ------------------------------------------------------------------

    async def _spawn_agent(self, prompt: str) -> str:
        """Spawn the agent via ``claude_agent_sdk.query()`` and return raw text.

        Collects all :class:`TextBlock` content from :class:`AssistantMessage`
        objects yielded by the SDK's async generator.  If the SDK is not
        installed (e.g. in unit-test environments), logs a warning and returns
        an empty string so callers degrade gracefully.

        Parameters
        ----------
        prompt:
            The fully-assembled user prompt for the agent.

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

        options = _ClaudeAgentOptions(
            system_prompt=self.get_system_prompt(),
            model=self.get_model_id(),
            max_turns=self.max_turns,
            permission_mode="bypassPermissions",
            cwd=str(self.project_dir),
            allowed_tools=self.get_tools(),
            max_buffer_size=self._compute_buffer_size(),
        )

        agent_name = self.get_agent_name()
        prompt_tokens = len(prompt) // 4
        buffer_mb = self._compute_buffer_size() / (1024 * 1024)
        logger.info(
            "Agent %s: starting SDK session (prompt ~%dK tokens, buffer %.1f MB, max_turns=%d)",
            agent_name,
            prompt_tokens // 1000,
            buffer_mb,
            self.max_turns,
        )

        text_parts: list[str] = []
        msg_count = 0
        try:
            async for message in _query(prompt=prompt, options=options):
                msg_count += 1
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
                    # The ResultMessage is the terminal message so the loop
                    # will end naturally.
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Agent %s SDK call failed: %s -- returning partial output (%d parts collected)",
                agent_name,
                exc,
                len(text_parts),
            )

        total_text = len("\n".join(text_parts))
        logger.info(
            "Agent %s: session ended after %d messages, %d text chars collected",
            agent_name,
            msg_count,
            total_text,
        )

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
            logger.warning(
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
