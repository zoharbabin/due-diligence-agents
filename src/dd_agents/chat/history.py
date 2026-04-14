"""Conversation history management for Chat Mode.

Tracks user/assistant messages, serializes history for prompt injection,
and truncates oldest turns when the context budget is exceeded.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MessageRole(StrEnum):
    """Role of a chat message."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: MessageRole = Field(description="Who sent the message")
    content: str = Field(description="Message text")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(tz=UTC).isoformat(),
        description="ISO-8601 timestamp",
    )
    tool_usage: list[str] = Field(
        default_factory=list,
        description="Tools used while generating this message",
    )
    token_estimate: int = Field(
        default=0,
        description="Estimated token count (chars // 4)",
    )


class ConversationHistory(BaseModel):
    """Manages the conversation history for a chat session.

    Stores messages, serializes them for prompt injection, and
    handles truncation when the context budget is exceeded.
    """

    messages: list[ChatMessage] = Field(default_factory=list)
    max_context_chars: int = Field(
        default=80_000,
        description="Maximum total chars for serialized history",
    )
    total_chars: int = Field(
        default=0,
        description="Running total of content chars across all messages",
    )

    @property
    def turn_count(self) -> int:
        """Number of complete user/assistant turn pairs."""
        user_count = sum(1 for m in self.messages if m.role == MessageRole.USER)
        assistant_count = sum(1 for m in self.messages if m.role == MessageRole.ASSISTANT)
        return min(user_count, assistant_count)

    def add_message(
        self,
        role: MessageRole,
        content: str,
        tool_usage: list[str] | None = None,
    ) -> None:
        """Append a message and update the running character total."""
        msg = ChatMessage(
            role=role,
            content=content,
            tool_usage=tool_usage or [],
            token_estimate=len(content) // 4,
        )
        self.messages.append(msg)
        self.total_chars += len(content)

    def to_prompt_text(self) -> str:
        """Serialize the conversation history for prompt injection.

        Returns an empty string when no messages exist.
        """
        if not self.messages:
            return ""

        parts: list[str] = ["<conversation_history>"]
        turn_num = 0

        i = 0
        while i < len(self.messages):
            msg = self.messages[i]
            if msg.role == MessageRole.USER:
                turn_num += 1
                parts.append(f"\n[Turn {turn_num}]")
                parts.append(f"USER: {msg.content}")
                # Look for the paired assistant message
                if i + 1 < len(self.messages) and self.messages[i + 1].role == MessageRole.ASSISTANT:
                    assistant_msg = self.messages[i + 1]
                    tool_note = ""
                    if assistant_msg.tool_usage:
                        tool_note = f" [Used tools: {', '.join(assistant_msg.tool_usage)}]"
                    parts.append(f"ASSISTANT:{tool_note}\n{assistant_msg.content}")
                    i += 2
                    continue
            i += 1

        parts.append("</conversation_history>")
        return "\n".join(parts)

    def truncate_to_budget(self, max_chars: int | None = None) -> int:
        """Remove oldest turn pairs until total chars fits within budget.

        Always preserves the most recent user/assistant pair.

        Returns the number of pairs removed.
        """
        budget = max_chars if max_chars is not None else self.max_context_chars
        removed = 0

        while self.total_chars > budget and len(self.messages) > 2:
            # Remove the oldest pair (messages[0] should be USER, [1] ASSISTANT)
            if (
                len(self.messages) >= 2
                and self.messages[0].role == MessageRole.USER
                and self.messages[1].role == MessageRole.ASSISTANT
            ):
                user_msg = self.messages.pop(0)
                assistant_msg = self.messages.pop(0)
                self.total_chars -= len(user_msg.content) + len(assistant_msg.content)
                removed += 1
            else:
                # Unexpected ordering — remove one message at a time
                old = self.messages.pop(0)
                self.total_chars -= len(old.content)

        if removed > 0:
            logger.debug("Truncated %d turn pair(s) to fit within %d char budget", removed, budget)

        return removed
