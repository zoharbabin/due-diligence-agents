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

    def get_model_id(self) -> str:
        """Return the LLM model identifier for this agent.

        Defaults to ``claude-sonnet-4-20250514``.  Subclasses may override
        if they need a different model.
        """
        return "claude-sonnet-4-20250514"

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
            logger.error(
                "Agent output contained no parseable JSON (%d chars)",
                len(raw_output),
            )
            if raw_output_path is not None:
                try:
                    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_output_path.write_text(raw_output, encoding="utf-8")
                    logger.info("Raw agent output saved to %s", raw_output_path)
                except OSError as exc:
                    logger.warning("Failed to save raw output to %s: %s", raw_output_path, exc)

        return results
