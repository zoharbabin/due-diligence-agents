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


class BaseAgentRunner(ABC):
    """Abstract base for every agent runner.

    Subclasses must implement the four property methods that define the agent's
    identity and capability surface.  The ``run`` method orchestrates a single
    agent invocation: build prompt -> spawn (placeholder) -> parse output.
    """

    # Configurable defaults -- subclasses may override via class attributes.
    timeout_seconds: int = 600
    max_turns: int = 200
    max_budget_usd: float = 5.0
    default_tools: list[str] = ["Read", "Write", "Glob", "Grep"]

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

    @abstractmethod
    def get_model_id(self) -> str:
        """Return the LLM model identifier for this agent."""

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system-level preamble injected before the user prompt."""

    @abstractmethod
    def get_tools(self) -> list[str]:
        """Return the list of tool names available to this agent."""

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
            prompt = self.build_prompt(state)

            # Placeholder: actual SDK integration would call ``query()`` here.
            raw_output = await self._spawn_agent(prompt)

            parsed = self._parse_agent_output(raw_output)
            result["output"] = parsed
            result["status"] = "success"
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

        Subclasses may override to customise prompt assembly.
        """
        from dd_agents.agents.prompt_builder import PromptBuilder

        PromptBuilder(
            project_dir=self.project_dir,
            run_dir=self.run_dir,
            run_id=self.run_id,
        )
        # Default: return a minimal prompt.  Specialist / Judge / ReportingLead
        # override this to call the appropriate builder method.
        return f"{self.get_system_prompt()}\n\nRun ID: {self.run_id}\nProject directory: {self.project_dir}\n"

    # ------------------------------------------------------------------
    # Agent spawn placeholder
    # ------------------------------------------------------------------

    async def _spawn_agent(self, prompt: str) -> str:
        """Spawn the agent via the SDK and return raw textual output.

        This is a **placeholder** for the real ``claude_agent_sdk.query()``
        integration.  In production this will be replaced with::

            from claude_agent_sdk import query, ClaudeAgentOptions
            options = ClaudeAgentOptions(model=self.get_model_id(), ...)
            result = await query(options=options, prompt=prompt)
            return result.text

        For now it returns an empty string so the rest of the pipeline can be
        tested without API calls.
        """
        _ = prompt  # consumed by real SDK call
        return ""

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_agent_output(raw_output: str) -> list[dict[str, Any]]:
        """Extract structured JSON objects from free-form agent text output.

        The method looks for top-level JSON objects or arrays embedded in the
        agent's response (possibly surrounded by markdown fences or prose).

        Returns a list of dicts.  If no valid JSON is found, returns ``[]``.
        """
        if not raw_output or not raw_output.strip():
            return []

        results: list[dict[str, Any]] = []

        # Strategy 1: try entire output as JSON.
        try:
            data = json.loads(raw_output)
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict):
                results.append(data)
            return results
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: extract from markdown code fences.
        fence_pattern = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)
        for match in fence_pattern.finditer(raw_output):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, ValueError):
                continue

        if results:
            return results

        # Strategy 3: find standalone JSON objects via brace matching.
        brace_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}")
        for match in brace_pattern.finditer(raw_output):
            try:
                data = json.loads(match.group(0))
                results.append(data)
            except (json.JSONDecodeError, ValueError):
                continue

        return results
