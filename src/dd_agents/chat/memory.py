"""Persistent chat memory for cross-session context.

Stores compact insights extracted during chat sessions in an append-only
JSONL file.  Provides performant keyword/fuzzy search over memories using
rapidfuzz (already a project dependency).

Storage layout::

    _dd/forensic-dd/chat/
        sessions/                  # Full transcripts per session
            chat_20260413_143022.jsonl
        memories.jsonl             # Extracted insights (append-only)
        session_index.json         # Session metadata index
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.chat.history import ChatMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MemoryType(StrEnum):
    """Type of chat memory."""

    INSIGHT = "insight"
    CROSS_REFERENCE = "cross_reference"
    USER_NOTE = "user_note"
    CONCLUSION = "conclusion"


class ChatMemory(BaseModel):
    """A single persistent memory extracted from a chat session."""

    id: str = Field(description="Unique ID (UUID hex[:12])")
    timestamp: str = Field(description="ISO-8601 creation time")
    session_id: str = Field(description="Session that produced this memory")
    content: str = Field(description="The insight text (1-3 concise sentences)")
    topics: list[str] = Field(description="Subject names, categories, keywords")
    memory_type: MemoryType = Field(description="Classification of the memory")
    source_turn: int = Field(default=0, description="Turn number that generated this")


class SessionMetadata(BaseModel):
    """Metadata for a completed chat session."""

    session_id: str = Field(description="Session identifier (chat_YYYYMMDD_HHMMSS)")
    start_time: str = Field(description="ISO-8601 session start")
    end_time: str | None = Field(default=None, description="ISO-8601 session end")
    turn_count: int = Field(default=0, description="Number of completed turns")
    run_id: str = Field(default="", description="Pipeline run being discussed")
    topics_discussed: list[str] = Field(default_factory=list, description="Subjects/categories mentioned")
    memory_count: int = Field(default=0, description="Memories saved during session")


# ---------------------------------------------------------------------------
# Memory Store
# ---------------------------------------------------------------------------


def generate_memory_id() -> str:
    """Generate a short unique memory ID."""
    return uuid.uuid4().hex[:12]


class ChatMemoryStore:
    """Persistent store for chat memories and session transcripts.

    Parameters
    ----------
    chat_dir:
        Root directory for chat data (``_dd/forensic-dd/chat/``).
    """

    def __init__(self, chat_dir: Path) -> None:
        self._chat_dir = chat_dir
        self._memories_path = chat_dir / "memories.jsonl"
        self._sessions_dir = chat_dir / "sessions"
        self._index_path = chat_dir / "session_index.json"
        # In-memory cache for search performance
        self._memories_cache: list[ChatMemory] = []
        self._cache_mtime: float = 0.0

    def ensure_dirs(self) -> None:
        """Create the chat directory structure if it doesn't exist."""
        self._chat_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    @property
    def memory_count(self) -> int:
        """Total number of stored memories."""
        self._refresh_cache()
        return len(self._memories_cache)

    # ----- Memory CRUD -----

    def save_memory(self, memory: ChatMemory) -> None:
        """Atomically append a memory to ``memories.jsonl``."""
        self.ensure_dirs()
        line = memory.model_dump_json() + "\n"

        if self._memories_path.exists():
            # Atomic append: read existing, append, write to temp, replace
            existing = self._memories_path.read_text(encoding="utf-8")
            new_content = existing + line
        else:
            new_content = line

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._chat_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, self._memories_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

        # Invalidate cache
        self._cache_mtime = 0.0
        logger.debug("Saved memory %s: %s", memory.id, memory.content[:80])

    def search_memories(self, query: str, *, limit: int = 10) -> list[ChatMemory]:
        """Search memories using rapidfuzz keyword/fuzzy matching.

        Returns up to *limit* memories sorted by relevance, with recency
        as a tiebreaker.
        """
        from rapidfuzz import fuzz

        self._refresh_cache()
        if not self._memories_cache:
            return []

        query_lower = query.lower()
        scored: list[tuple[float, int, ChatMemory]] = []

        for idx, mem in enumerate(self._memories_cache):
            # Build searchable text from content + topics
            searchable = f"{mem.content} {' '.join(mem.topics)}".lower()
            score = fuzz.token_sort_ratio(query_lower, searchable)
            if score >= 40:
                # Use negative index so later entries (more recent) rank higher
                scored.append((score, idx, mem))

        # Sort by score descending, then by index ascending (recency tiebreak)
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [mem for _, _, mem in scored[:limit]]

    def load_recent_memories(self, limit: int = 15) -> list[ChatMemory]:
        """Load the most recent *limit* memories."""
        self._refresh_cache()
        return self._memories_cache[-limit:]

    # ----- Session Transcripts -----

    def save_session_transcript(
        self,
        session_id: str,
        messages: list[ChatMessage],
    ) -> None:
        """Write the full session transcript to a JSONL file."""
        self.ensure_dirs()
        path = self._sessions_dir / f"{session_id}.jsonl"

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._sessions_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for msg in messages:
                    f.write(msg.model_dump_json() + "\n")
            os.replace(tmp_path, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        logger.debug("Saved session transcript %s (%d messages)", session_id, len(messages))

    # ----- Session Index -----

    def update_session_index(self, meta: SessionMetadata) -> None:
        """Add or update a session entry in the index."""
        self.ensure_dirs()
        entries = self.load_session_index()

        # Update existing or append
        found = False
        for i, entry in enumerate(entries):
            if entry.session_id == meta.session_id:
                entries[i] = meta
                found = True
                break
        if not found:
            entries.append(meta)

        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._chat_dir),
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([e.model_dump() for e in entries], f, indent=2)
            os.replace(tmp_path, self._index_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def load_session_index(self) -> list[SessionMetadata]:
        """Load all session metadata entries."""
        if not self._index_path.exists():
            return []
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return [SessionMetadata.model_validate(entry) for entry in data]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read session index: %s", exc)
            return []

    # ----- Cache Management -----

    def _refresh_cache(self) -> None:
        """Reload memories from disk if the file has been modified."""
        if not self._memories_path.exists():
            self._memories_cache = []
            self._cache_mtime = 0.0
            return

        try:
            current_mtime = self._memories_path.stat().st_mtime
        except OSError:
            return

        if current_mtime <= self._cache_mtime:
            return

        memories: list[ChatMemory] = []
        try:
            with self._memories_path.open(encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        memories.append(ChatMemory.model_validate_json(line))
                    except Exception:
                        logger.warning("Corrupt memory at line %d — skipping", line_num)
        except OSError as exc:
            logger.warning("Could not read memories file: %s", exc)
            return

        self._memories_cache = memories
        self._cache_mtime = current_mtime
        logger.debug("Refreshed memory cache: %d memories", len(memories))


def generate_session_id() -> str:
    """Generate a session ID from the current timestamp."""
    now = datetime.now(tz=UTC)
    return f"chat_{now.strftime('%Y%m%d_%H%M%S')}"
