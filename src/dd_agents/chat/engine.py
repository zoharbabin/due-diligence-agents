"""Chat engine for interactive multi-turn DD conversations.

Manages the conversation loop, SDK calls, context assembly,
persistent memory, and session lifecycle.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from pydantic import BaseModel, Field

from dd_agents.chat.context import ChatContextBuilder
from dd_agents.chat.history import ConversationHistory, MessageRole
from dd_agents.chat.memory import ChatMemoryStore, SessionMetadata, generate_session_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK import
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
    logger.debug("claude_agent_sdk not installed — chat mode unavailable")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChatError(Exception):
    """Base exception for chat errors."""


class BudgetExhaustedError(ChatError):
    """Session budget has been exceeded."""


class NoFindingsError(ChatError):
    """No findings found in the specified run directory."""


# ---------------------------------------------------------------------------
# Config & Response models
# ---------------------------------------------------------------------------


class ChatConfig(BaseModel):
    """Configuration for a chat session."""

    model: str | None = Field(default=None, description="Model override (None = SDK default)")
    max_turns_per_query: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Max tool-use turns per query() call",
    )
    max_cost_per_turn: float = Field(default=0.50, description="Per-turn budget in USD")
    max_session_cost: float = Field(default=2.00, description="Total session budget in USD")
    max_history_chars: int = Field(default=80_000, description="Max conversation history chars")
    enable_tools: bool = Field(default=True, description="Enable document analysis MCP tools")
    verbose: bool = Field(default=False, description="Show tool usage in output")


class ChatResponse(BaseModel):
    """Response from a single chat turn."""

    text: str = Field(description="Assistant's response text")
    tools_used: list[str] = Field(default_factory=list, description="MCP tools invoked during this turn")
    turn_number: int = Field(default=0, description="Turn number in the session")
    estimated_cost: float = Field(default=0.0, description="Estimated cost for this turn in USD")
    session_cost: float = Field(default=0.0, description="Cumulative session cost in USD")
    message_count: int = Field(default=0, description="SDK messages processed in this turn")
    memories_saved: int = Field(default=0, description="Memories saved during this turn")


# ---------------------------------------------------------------------------
# Chat-mode tools
# ---------------------------------------------------------------------------

# MCP tools available in chat mode
CHAT_READ_TOOLS: list[str] = ["Read", "Glob", "Grep"]

# Custom MCP tools (document + memory + corrections)
CHAT_MCP_TOOL_NAMES: list[str] = [
    "verify_citation",
    "search_in_file",
    "get_page_content",
    "read_office",
    "get_subject_files",
    "resolve_entity",
    "search_similar",
    "batch_verify_citations",
    "save_memory",
    "search_chat_memory",
    "flag_finding",
    "list_corrections",
]

# Cost estimation constants
_CHARS_PER_TOKEN = 4
_INPUT_COST_PER_MTOK = 3.0  # Claude Sonnet 4
_OUTPUT_COST_PER_MTOK = 15.0
_MIN_BUFFER_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ChatEngine:
    """Interactive multi-turn chat engine for DD analysis.

    Parameters
    ----------
    run_dir:
        Path to the pipeline run directory (contains ``findings/merged/``).
    project_dir:
        Root project directory (contains ``_dd/``).
    config:
        Chat session configuration.
    """

    def __init__(
        self,
        run_dir: Path,
        project_dir: Path,
        config: ChatConfig | None = None,
    ) -> None:
        self._run_dir = run_dir
        self._project_dir = project_dir
        self._config = config or ChatConfig()
        self._history = ConversationHistory(max_context_chars=self._config.max_history_chars)
        self._session_cost: float = 0.0
        self._turn_count: int = 0
        self._session_id = generate_session_id()
        self._memories_saved_this_session: int = 0

        # Load findings index
        from dd_agents.query.indexer import FindingIndexer

        self._index = FindingIndexer().index_report(run_dir)

        # Load knowledge base (optional)
        self._kb: Any = None
        try:
            from dd_agents.knowledge.base import DealKnowledgeBase

            kb = DealKnowledgeBase(project_dir)
            if kb.exists:
                self._kb = kb
        except Exception:
            pass

        # Load chronicle (optional)
        self._chronicle: Any = None
        chronicle_path = project_dir / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl"
        if chronicle_path.parent.exists():
            try:
                from dd_agents.knowledge.chronicle import AnalysisChronicle

                self._chronicle = AnalysisChronicle(chronicle_path)
            except Exception:
                pass

        # Memory store
        chat_dir = project_dir / "_dd" / "forensic-dd" / "chat"
        self._memory_store = ChatMemoryStore(chat_dir)
        self._memory_store.ensure_dirs()

        # Correction store (chat-to-pipeline feedback)
        from dd_agents.chat.corrections import CorrectionStore

        self._correction_store = CorrectionStore(chat_dir)
        self._correction_store.ensure_dirs()

        # Build context and cache system prompt
        self._context_builder = ChatContextBuilder(
            finding_index=self._index,
            knowledge_base=self._kb,
            chronicle=self._chronicle,
            memory_store=self._memory_store,
            correction_store=self._correction_store,
            run_dir=run_dir,
        )
        self._system_prompt = self._context_builder.build_system_prompt()

        # Lazy-init
        self._mcp_server: Any | None = None
        self._hooks: dict[str, list[Any]] | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def finding_count(self) -> int:
        """Number of indexed findings."""
        return self._index.total_findings

    @property
    def session_cost(self) -> float:
        """Cumulative session cost estimate in USD."""
        return self._session_cost

    @property
    def turn_count(self) -> int:
        """Number of completed turns."""
        return self._turn_count

    @property
    def history_chars(self) -> int:
        """Current character count of conversation history."""
        return self._history.total_chars

    @property
    def memory_count(self) -> int:
        """Total memories in the store (across all sessions)."""
        return self._memory_store.memory_count

    @property
    def correction_count(self) -> int:
        """Total finding corrections stored."""
        return self._correction_store.correction_count

    # ------------------------------------------------------------------
    # Core: ask
    # ------------------------------------------------------------------

    async def ask(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
        on_tool_status: Callable[[str], None] | None = None,
    ) -> ChatResponse:
        """Process a single user question and return the assistant's response.

        Parameters
        ----------
        question:
            The user's question.
        on_text:
            Optional callback for streaming final answer text chunks.
            Only called for text in AssistantMessages that contain no tool
            calls (i.e., the final answer, not intermediate reasoning).
        on_tool_status:
            Optional callback for tool-use progress updates.  Called with
            the tool name each time the model invokes a tool.

        Returns
        -------
        ChatResponse with the full answer, tools used, and cost estimates.

        Raises
        ------
        BudgetExhaustedError:
            If the session budget has been exceeded.
        ChatError:
            If the SDK is not available.
        """
        if not _HAS_SDK:
            msg = "claude-agent-sdk is required for chat mode. Install it with: pip install claude-agent-sdk"
            raise ChatError(msg)

        remaining = self._config.max_session_cost - self._session_cost
        if remaining <= 0:
            msg = f"Session budget exhausted (${self._config.max_session_cost:.2f})"
            raise BudgetExhaustedError(msg)

        # Truncate history if over budget
        self._history.truncate_to_budget(self._config.max_history_chars)

        # Build prompt
        turn_prompt = self._context_builder.build_turn_prompt(question, self._history)

        # Build SDK options
        options = self._build_options(remaining)

        # Execute query — wrapped in try/except so SDK crashes don't
        # kill the session.  We return whatever text was collected.
        text_parts: list[str] = []
        final_text_parts: list[str] = []
        tools_used: list[str] = []
        msg_count = 0
        memories_this_turn = 0
        sdk_error: str | None = None

        try:
            async for message in _query(prompt=turn_prompt, options=options):
                msg_count += 1

                if isinstance(message, _AssistantMessage):
                    # Check whether this message contains tool-use blocks.
                    has_tool_use = any(
                        hasattr(block, "name") and not isinstance(block, _TextBlock) for block in message.content
                    )

                    for block in message.content:
                        if isinstance(block, _TextBlock):
                            text_parts.append(block.text)
                            if not has_tool_use:
                                final_text_parts.append(block.text)
                                if on_text is not None:
                                    on_text(block.text)
                        elif hasattr(block, "name"):
                            tool_name = getattr(block, "name", "unknown")
                            if tool_name not in tools_used:
                                tools_used.append(tool_name)
                            if tool_name == "save_memory":
                                memories_this_turn += 1
                            if on_tool_status is not None:
                                on_tool_status(tool_name)

                elif isinstance(message, _ResultMessage) and message.is_error:
                    if message.result:
                        logger.debug("SDK error result: %s", message.result)
        except Exception as exc:
            sdk_error = str(exc)
            logger.debug("SDK query failed: %s", exc)

        # Prefer text from pure-text messages (the final answer).
        # Fall back to all collected text, then to an error message.
        if final_text_parts:
            full_text = "\n".join(final_text_parts)
        elif text_parts:
            full_text = "\n".join(text_parts)
        elif sdk_error:
            full_text = (
                "The analysis encountered an error. "
                "Please try rephrasing your question or use "
                f"`--verbose` for details.\n\nTechnical: {sdk_error}"
            )
        else:
            full_text = "I wasn't able to generate a response. Try rephrasing your question."
        self._turn_count += 1
        self._memories_saved_this_session += memories_this_turn

        # Estimate cost
        prompt_chars = len(self._system_prompt) + len(turn_prompt)
        response_chars = len(full_text)
        input_tokens = prompt_chars // _CHARS_PER_TOKEN
        output_tokens = response_chars // _CHARS_PER_TOKEN
        turn_cost = (input_tokens * _INPUT_COST_PER_MTOK + output_tokens * _OUTPUT_COST_PER_MTOK) / 1_000_000
        self._session_cost += turn_cost

        # Update history
        self._history.add_message(MessageRole.USER, question)
        self._history.add_message(MessageRole.ASSISTANT, full_text, tool_usage=tools_used)

        # Log to chronicle
        self._log_to_chronicle(question, full_text, tools_used, turn_cost)

        return ChatResponse(
            text=full_text,
            tools_used=tools_used,
            turn_number=self._turn_count,
            estimated_cost=turn_cost,
            session_cost=self._session_cost,
            message_count=msg_count,
            memories_saved=memories_this_turn,
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Finalize the session: save transcript, run fallback summarization."""
        # Fallback: if no memories were saved and we had a real conversation,
        # ask the model to extract key insights.
        if _HAS_SDK and self._turn_count >= 3 and self._memories_saved_this_session == 0 and self._config.enable_tools:
            try:
                remaining = self._config.max_session_cost - self._session_cost
                if remaining > 0.05:
                    await self._run_session_summarization()
            except Exception as exc:
                logger.debug("Session-end summarization failed: %s", exc)

        # Save transcript
        try:
            self._memory_store.save_session_transcript(
                self._session_id,
                self._history.messages,
            )
        except Exception as exc:
            logger.warning("Failed to save session transcript: %s", exc)

        # Update session index
        try:
            run_id = ""
            if self._run_dir is not None:
                run_id = self._run_dir.name
            meta = SessionMetadata(
                session_id=self._session_id,
                start_time=self._history.messages[0].timestamp if self._history.messages else "",
                end_time=datetime.now(tz=UTC).isoformat(),
                turn_count=self._turn_count,
                run_id=run_id,
                topics_discussed=sorted(self._index.by_subject.keys())[:20],
                memory_count=self._memories_saved_this_session,
            )
            self._memory_store.update_session_index(meta)
        except Exception as exc:
            logger.warning("Failed to update session index: %s", exc)

    async def _run_session_summarization(self) -> None:
        """Ask the model to extract key insights from the conversation."""
        history_text = self._history.to_prompt_text()
        prompt = (
            "Review the following conversation and extract 1-5 key insights "
            "worth remembering for future sessions about this deal. "
            "For each insight, call the save_memory tool with a concise "
            "description (1-3 sentences), relevant topics, and the appropriate "
            "memory_type (insight, cross_reference, user_note, or conclusion).\n\n"
            f"{history_text}"
        )
        remaining = self._config.max_session_cost - self._session_cost
        options = self._build_options(min(remaining, 0.10))  # cap at $0.10

        async for message in _query(prompt=prompt, options=options):
            if isinstance(message, _ResultMessage) and message.is_error:
                logger.debug("Summarization error: %s", message.result)

    # ------------------------------------------------------------------
    # SDK setup helpers
    # ------------------------------------------------------------------

    def _build_options(self, max_budget: float) -> _ClaudeAgentOptions:
        """Build ClaudeAgentOptions for a chat turn."""
        from dd_agents.utils import resolve_sdk_cli_path

        options_kwargs: dict[str, Any] = {
            "system_prompt": self._system_prompt,
            "max_turns": self._config.max_turns_per_query,
            "max_budget_usd": min(self._config.max_cost_per_turn, max_budget),
            "permission_mode": "bypassPermissions",
            "cwd": str(self._project_dir),
            "allowed_tools": self._get_allowed_tools(),
            "max_buffer_size": self._compute_buffer_size(),
        }

        cli_path = resolve_sdk_cli_path()
        if cli_path is not None:
            options_kwargs["cli_path"] = cli_path

        if self._config.model is not None:
            options_kwargs["model"] = self._config.model

        hooks = self._build_hooks()
        if hooks:
            options_kwargs["hooks"] = hooks

        mcp_server = self._build_mcp_server()
        if mcp_server is not None:
            options_kwargs["mcp_servers"] = {"dd_tools": mcp_server}

        return _ClaudeAgentOptions(**options_kwargs)

    def _get_allowed_tools(self) -> list[str]:
        """Return the allowed tool list for the chat session."""
        if not self._config.enable_tools:
            return []
        return [*CHAT_READ_TOOLS, *[f"mcp__dd_tools__{t}" for t in CHAT_MCP_TOOL_NAMES]]

    def _build_mcp_server(self) -> Any | None:
        """Build or return the cached MCP server."""
        if not self._config.enable_tools:
            return None
        if self._mcp_server is not None:
            return self._mcp_server

        try:
            from dd_agents.tools.mcp_server import _build_runtime_context, build_mcp_server

            ctx = _build_runtime_context(
                project_dir=self._project_dir,
                run_dir=self._run_dir,
            )
            self._mcp_server = build_mcp_server(
                agent_type="chat",
                memory_store=self._memory_store,
                session_id=self._session_id,
                correction_store=self._correction_store,
                finding_index=self._index,
                **ctx,
            )
            return self._mcp_server
        except Exception as exc:
            logger.warning("Failed to build MCP server: %s", exc)
            return None

    def _build_hooks(self) -> dict[str, list[Any]] | None:
        """Build chat-mode hooks (path_guard only)."""
        if self._hooks is not None:
            return self._hooks

        try:
            from claude_agent_sdk import HookMatcher
        except ImportError:
            return None

        from dd_agents.hooks.pre_tool import path_guard

        project_dir = self._project_dir

        async def chat_pre_tool_hook(
            hook_input: Any,
            tool_name: str | None = None,
            context: Any = None,
        ) -> dict[str, Any]:
            try:
                tn = tool_name or hook_input.get("tool_name", "")
                ti = hook_input.get("tool_input", {})
                result = path_guard(tn, ti, project_dir)
                if result["decision"] == "block":
                    return {"decision": "block", "reason": result["reason"]}
            except Exception:
                pass
            return {}

        self._hooks = {
            "PreToolUse": [HookMatcher(hooks=[chat_pre_tool_hook], timeout=5.0)],  # type: ignore[list-item]
        }
        return self._hooks

    def _compute_buffer_size(self) -> int:
        """Compute SDK message buffer size from the largest extracted-text file."""
        text_dir = self._project_dir / "_dd" / "forensic-dd" / "index" / "text"
        if not text_dir.is_dir():
            return _MIN_BUFFER_BYTES
        max_size = 0
        try:
            for f in text_dir.iterdir():
                if f.suffix in (".md", ".txt") and f.is_file():
                    try:
                        size = f.stat().st_size
                        if size > max_size:
                            max_size = size
                    except OSError:
                        continue
        except OSError:
            pass
        return max(max_size * 3, _MIN_BUFFER_BYTES)

    # ------------------------------------------------------------------
    # Chronicle logging
    # ------------------------------------------------------------------

    def _log_to_chronicle(
        self,
        question: str,
        answer: str,
        tools_used: list[str],
        cost: float,
    ) -> None:
        """Log a chat turn to the analysis chronicle."""
        if self._chronicle is None:
            return
        try:
            import uuid

            from dd_agents.knowledge.chronicle import AnalysisLogEntry, InteractionType

            entry = AnalysisLogEntry(
                id=uuid.uuid4().hex[:12],
                timestamp=datetime.now(tz=UTC).isoformat(),
                interaction_type=InteractionType.CHAT,
                title=f"Chat: {question[:80]}",
                details={
                    "question": question,
                    "answer_length": len(answer),
                    "tools_used": tools_used,
                    "turn": self._turn_count,
                    "session_id": self._session_id,
                },
                entities_affected=[],
                cost_usd=cost,
                user_initiated=True,
            )
            self._chronicle.append(entry)
        except Exception as exc:
            logger.debug("Failed to log to chronicle: %s", exc)
