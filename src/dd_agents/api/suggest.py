"""Draft a deal config from the data room with the LLM. Nothing is written to disk."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dd_agents.llm.provider import scrub_secrets

logger = logging.getLogger(__name__)

# A draft normally takes seconds. A model call that hangs must not block the project forever.
DEFAULT_TIMEOUT_SECONDS = 600.0

Suggester = Callable[[Path, str, str], Awaitable[dict[str, Any]]]


class SuggestBusyError(Exception):
    """A draft is already being made for this project."""


async def default_suggester(room: Path, buyer: str, target: str) -> dict[str, Any]:
    """Same steps as ``dd-agents auto-config --dry-run``."""
    from dd_agents.cli_auto_config import (
        DataRoomAnalyzer,
        build_reference_file_summary,
        get_tree_output,
        validate_and_fix_config,
    )
    from dd_agents.cli_init import scan_data_room

    scan = await asyncio.to_thread(scan_data_room, room)
    tree = await asyncio.to_thread(get_tree_output, room, 4)
    references = await asyncio.to_thread(build_reference_file_summary, room)
    config = await DataRoomAnalyzer(data_room_path=room).analyze(
        tree_output=tree,
        scan_result=scan,
        reference_files=references,
        buyer=buyer,
        target=target,
    )
    return validate_and_fix_config(config, scan)


class SuggestJobs:
    """One draft per project, kept in memory. All methods run on the server's event loop."""

    def __init__(self, suggester: Suggester | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._suggester = suggester or default_suggester
        self._timeout = timeout
        self._state: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def status(self, slug: str) -> dict[str, Any]:
        return dict(self._state.get(slug, {"state": "idle"}))

    def start(self, slug: str, room: Path, buyer: str, target: str) -> None:
        task = self._tasks.get(slug)
        if task is not None and not task.done():
            raise SuggestBusyError("A draft is already being made")
        self._state[slug] = {"state": "running"}
        self._tasks[slug] = asyncio.create_task(self._run(slug, room, buyer, target))

    async def _run(self, slug: str, room: Path, buyer: str, target: str) -> None:
        try:
            async with asyncio.timeout(self._timeout):
                config = await self._suggester(room, buyer, target)
            self._state[slug] = {"state": "done", "config": config}
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.warning("config suggestion timed out after %.0f s", self._timeout)
            self._state[slug] = {"state": "error", "error": "The model took too long to answer. Try again."}
        except Exception as exc:  # noqa: BLE001 - the user must see why it failed
            logger.exception("config suggestion failed")
            self._state[slug] = {"state": "error", "error": scrub_secrets(f"{type(exc).__name__}: {exc}")}

    async def close_all(self) -> None:
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
