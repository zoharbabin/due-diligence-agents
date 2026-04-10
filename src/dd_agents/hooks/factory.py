"""Hook factory — builds SDK-compatible hook configurations for agents.

Wraps the individual hook functions from ``pre_tool``, ``post_tool``, and
``stop`` into async closures matching the ``claude_agent_sdk`` callback
signatures, then packages them as ``HookMatcher`` objects keyed by event type.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.hooks.pre_tool import (
    BLOCKED_FILENAMES,
    bash_guard,
    file_size_guard,
    path_guard,
)
from dd_agents.hooks.stop import check_coverage, check_manifest

if TYPE_CHECKING:
    from claude_agent_sdk import HookMatcher  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PreToolUse hook builder
# ---------------------------------------------------------------------------


def _build_pre_tool_hook(
    agent_name: str,
    project_dir: Path,
) -> Any:
    """Return an async PreToolUse callback compatible with the SDK.

    The callback receives ``(hook_input, tool_name, context)`` and returns
    a ``SyncHookJSONOutput``-compatible dict.
    """

    async def pre_tool_hook(hook_input: Any, tool_name: str | None, context: Any) -> dict[str, Any]:
        try:
            tn = hook_input.get("tool_name", "") if tool_name is None else tool_name
            ti = hook_input.get("tool_input", {})

            # 1. Bash guard
            result = bash_guard(tn, ti)
            if result["decision"] == "block":
                return {"decision": "block", "reason": result["reason"]}

            # 2. Path guard — only for Write/Edit
            result = path_guard(tn, ti, project_dir)
            if result["decision"] == "block":
                return {"decision": "block", "reason": result["reason"]}

            # 3. File size guard (warning only)
            result = file_size_guard(tn, ti)
            if result["reason"]:
                logger.warning("[%s] %s", agent_name, result["reason"])

            # 4. Aggregate file guard — block writes to known bad filenames
            if tn in ("Write", "Edit"):
                file_path = ti.get("file_path", "")
                filename = Path(file_path).name if file_path else ""
                if filename in BLOCKED_FILENAMES:
                    return {
                        "decision": "block",
                        "reason": (
                            f"Blocked write to aggregate filename '{filename}'. "
                            f"Findings must be per-subject, not aggregated."
                        ),
                    }

            return {}
        except Exception as exc:  # noqa: BLE001
            # Guard against SDK stream-closed errors during session teardown.
            logger.debug("PreToolUse hook error (likely session teardown): %s", exc)
            return {}

    return pre_tool_hook


# ---------------------------------------------------------------------------
# Stop hook builder
# ---------------------------------------------------------------------------


def _build_stop_hook(
    agent_name: str,
    run_dir: Path,
    expected_subjects: int,
) -> Any:
    """Return an async Stop callback compatible with the SDK.

    The callback receives ``(hook_input, tool_name, context)`` and returns
    a ``SyncHookJSONOutput``-compatible dict.
    """
    output_dir = run_dir / "findings" / agent_name

    async def stop_hook(hook_input: Any, tool_name: str | None, context: Any) -> dict[str, Any]:
        try:
            # 1. Coverage check — must have produced all subject JSONs
            result = check_coverage(output_dir, expected_subjects)
            if result["decision"] == "block":
                return {"continue_": False, "stopReason": result["reason"]}

            # 2. Manifest check — coverage_manifest.json must exist
            result = check_manifest(output_dir)
            if result["decision"] == "block":
                return {"continue_": False, "stopReason": result["reason"]}

            # Note: audit log is written by the orchestrator AFTER the agent
            # session completes (_write_audit_log in engine.py), so checking
            # for it here would always warn.  QA audit (step 28, DoD #11)
            # validates audit logs exist post-pipeline.

            return {}
        except Exception as exc:  # noqa: BLE001
            # Guard against SDK stream-closed errors during session teardown.
            logger.debug("Stop hook error (likely session teardown): %s", exc)
            return {}

    return stop_hook


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_hooks_for_agent(
    agent_name: str,
    run_dir: Path,
    project_dir: Path,
    expected_subjects: int,
) -> dict[str, list[HookMatcher]] | None:
    """Build the complete hook configuration for a specialist agent.

    Returns a dict suitable for passing to ``ClaudeAgentOptions(hooks=...)``,
    or ``None`` if ``claude_agent_sdk`` is not installed.

    Parameters
    ----------
    agent_name:
        Agent identifier (e.g., ``"legal"``).
    run_dir:
        Path to the current run directory.
    project_dir:
        Path to the project root (for path guard scope).
    expected_subjects:
        Number of subject JSONs the agent is expected to produce.
    """
    try:
        from claude_agent_sdk import HookMatcher as _HookMatcher  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("claude_agent_sdk not installed — hooks unavailable")
        return None

    return {
        "PreToolUse": [
            _HookMatcher(
                hooks=[_build_pre_tool_hook(agent_name, project_dir)],
                timeout=5.0,
            ),
        ],
        "Stop": [
            _HookMatcher(
                hooks=[_build_stop_hook(agent_name, run_dir, expected_subjects)],
                timeout=10.0,
            ),
        ],
    }
