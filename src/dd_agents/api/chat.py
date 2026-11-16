"""One chat session per project, kept in memory for the life of the server."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dd_agents.chat.engine import ChatConfig, ChatEngine, ChatError, ChatResponse
from dd_agents.llm.provider import scrub_secrets

logger = logging.getLogger(__name__)

CLOSE_TIMEOUT_SECONDS = 30.0


class ChatBusyError(Exception):
    """A question is already running for this project."""


class ChatEngineLike(Protocol):
    """What the API needs from a chat engine. ``ChatEngine`` satisfies it."""

    @property
    def finding_count(self) -> int: ...
    @property
    def session_cost(self) -> float: ...
    @property
    def turn_count(self) -> int: ...

    async def ask(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> ChatResponse: ...

    async def close(self) -> None: ...


ChatFactory = Callable[[Path, Path], ChatEngineLike]


def default_factory(run_dir: Path, project_dir: Path) -> ChatEngineLike:
    return ChatEngine(run_dir, project_dir)


def _frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@dataclass
class _Session:
    run_dir: Path
    engine: ChatEngineLike | None = None
    busy: bool = True
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def release(self, _task: asyncio.Task[None]) -> None:
        self.busy = False


class ChatSessions:
    """Sessions by project slug. All methods run on the server's event loop."""

    def __init__(self, factory: ChatFactory | None = None) -> None:
        self._factory = factory or default_factory
        self._sessions: dict[str, _Session] = {}

    def status(self, slug: str) -> dict[str, Any]:
        session = self._sessions.get(slug)
        engine = session.engine if session else None
        return {
            "active": engine is not None,
            "busy": bool(session and session.busy),
            "turn_count": engine.turn_count if engine else 0,
            "session_cost": engine.session_cost if engine else 0.0,
            "finding_count": engine.finding_count if engine else 0,
            "max_session_cost": ChatConfig().max_session_cost,
        }

    async def begin(self, slug: str, run_dir: Path, room: Path, question: str) -> AsyncIterator[str]:
        """Claim the session and start the question. Raises before streaming starts.

        The question keeps running if the client disconnects, so the session
        stays consistent. The returned iterator yields server-sent events.
        """
        session = self._sessions.get(slug)
        if session is not None and session.busy:
            raise ChatBusyError("A question is already running")
        if session is not None and session.run_dir != run_dir:
            await self._drop(slug)  # a newer review exists: answers must come from it
            session = None
        if session is None:
            session = _Session(run_dir=run_dir)
            self._sessions[slug] = session
            try:
                session.engine = await asyncio.to_thread(self._factory, run_dir, room)
            except BaseException:
                self._sessions.pop(slug, None)
                raise
        session.busy = True
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        engine = session.engine
        assert engine is not None
        session.task = asyncio.create_task(self._run(engine, question, queue))
        session.task.add_done_callback(session.release)
        return self._frames(queue)

    @staticmethod
    async def _run(engine: ChatEngineLike, question: str, queue: asyncio.Queue[str | None]) -> None:
        try:
            response = await engine.ask(
                question,
                on_text=lambda t: queue.put_nowait(_frame("text", {"text": t})),
                on_tool_status=lambda n: queue.put_nowait(_frame("tool", {"name": n})),
            )
            queue.put_nowait(_frame("done", response.model_dump()))
        except ChatError as exc:
            queue.put_nowait(_frame("error", {"message": scrub_secrets(str(exc))}))
        except Exception as exc:  # noqa: BLE001 - the stream must end with an error event
            logger.exception("chat question failed")
            queue.put_nowait(_frame("error", {"message": scrub_secrets(f"{type(exc).__name__}: {exc}")}))
        finally:
            queue.put_nowait(None)

    @staticmethod
    async def _frames(queue: asyncio.Queue[str | None]) -> AsyncIterator[str]:
        while (item := await queue.get()) is not None:
            yield item

    async def reset(self, slug: str) -> None:
        session = self._sessions.get(slug)
        if session is not None and session.busy:
            raise ChatBusyError("A question is running. Wait for it to finish")
        await self._drop(slug)

    async def _drop(self, slug: str) -> None:
        session = self._sessions.pop(slug, None)
        if session is not None and session.engine is not None:
            await self._close(session.engine)

    @staticmethod
    async def _close(engine: ChatEngineLike) -> None:
        try:
            await asyncio.wait_for(engine.close(), CLOSE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - closing is best effort
            logger.warning("chat session did not close cleanly", exc_info=True)

    async def close_all(self) -> None:
        for session in list(self._sessions.values()):
            if session.task is not None and not session.task.done():
                session.task.cancel()
        for slug in list(self._sessions):
            await self._drop(slug)
