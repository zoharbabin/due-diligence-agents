"""Chat Mode — interactive multi-turn DD conversations.

Provides an interactive chat session backed by pipeline findings and
document analysis tools, with persistent cross-session memory.
"""

from dd_agents.chat.context import ChatContextBuilder
from dd_agents.chat.corrections import CorrectionAction, CorrectionStore, FindingCorrection
from dd_agents.chat.engine import BudgetExhaustedError, ChatConfig, ChatEngine, ChatError, ChatResponse
from dd_agents.chat.history import ChatMessage, ConversationHistory, MessageRole
from dd_agents.chat.memory import ChatMemory, ChatMemoryStore, MemoryType, SessionMetadata

__all__ = [
    "BudgetExhaustedError",
    "ChatConfig",
    "ChatContextBuilder",
    "ChatEngine",
    "ChatError",
    "ChatMemory",
    "ChatMemoryStore",
    "ChatMessage",
    "ChatResponse",
    "ConversationHistory",
    "CorrectionAction",
    "CorrectionStore",
    "FindingCorrection",
    "MemoryType",
    "MessageRole",
    "SessionMetadata",
]
