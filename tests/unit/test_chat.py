"""Tests for the Chat Mode module (dd_agents.chat)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from click.testing import CliRunner

from dd_agents.chat.history import ChatMessage, ConversationHistory, MessageRole
from dd_agents.chat.memory import (
    ChatMemory,
    ChatMemoryStore,
    MemoryType,
    SessionMetadata,
    generate_memory_id,
)


def _sdk_available() -> bool:
    """Check if claude-agent-sdk is importable."""
    try:
        import claude_agent_sdk  # noqa: F401

        return True
    except ImportError:
        return False


# ===================================================================
# ConversationHistory
# ===================================================================


class TestConversationHistory:
    """Tests for ConversationHistory."""

    def test_add_message_updates_total_chars(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "Hello world")
        assert history.total_chars == 11
        history.add_message(MessageRole.ASSISTANT, "Hi there")
        assert history.total_chars == 11 + 8

    def test_to_prompt_text_empty(self) -> None:
        history = ConversationHistory()
        assert history.to_prompt_text() == ""

    def test_to_prompt_text_single_turn(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "What are the P0 findings?")
        history.add_message(MessageRole.ASSISTANT, "There are 3 P0 findings.")
        text = history.to_prompt_text()
        assert "<conversation_history>" in text
        assert "</conversation_history>" in text
        assert "[Turn 1]" in text
        assert "USER: What are the P0 findings?" in text
        assert "There are 3 P0 findings." in text

    def test_to_prompt_text_multi_turn(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "Question 1")
        history.add_message(MessageRole.ASSISTANT, "Answer 1")
        history.add_message(MessageRole.USER, "Question 2")
        history.add_message(MessageRole.ASSISTANT, "Answer 2")
        text = history.to_prompt_text()
        assert "[Turn 1]" in text
        assert "[Turn 2]" in text
        assert "Question 1" in text
        assert "Question 2" in text

    def test_to_prompt_text_includes_tool_usage(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "Verify the clause")
        history.add_message(MessageRole.ASSISTANT, "Verified.", tool_usage=["verify_citation"])
        text = history.to_prompt_text()
        assert "[Used tools: verify_citation]" in text

    def test_truncate_removes_oldest_pairs(self) -> None:
        history = ConversationHistory()
        # Add 3 turns with known sizes
        history.add_message(MessageRole.USER, "A" * 100)
        history.add_message(MessageRole.ASSISTANT, "B" * 100)
        history.add_message(MessageRole.USER, "C" * 100)
        history.add_message(MessageRole.ASSISTANT, "D" * 100)
        history.add_message(MessageRole.USER, "E" * 100)
        history.add_message(MessageRole.ASSISTANT, "F" * 100)
        assert history.total_chars == 600

        removed = history.truncate_to_budget(300)
        assert removed >= 1
        assert history.total_chars <= 300
        # Latest pair preserved
        assert history.messages[-1].content == "F" * 100
        assert history.messages[-2].content == "E" * 100

    def test_truncate_preserves_latest_pair(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "X" * 200)
        history.add_message(MessageRole.ASSISTANT, "Y" * 200)
        # Budget is smaller than latest pair — should NOT remove it
        removed = history.truncate_to_budget(100)
        assert removed == 0
        assert len(history.messages) == 2

    def test_truncate_noop_when_under_budget(self) -> None:
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "short")
        history.add_message(MessageRole.ASSISTANT, "reply")
        removed = history.truncate_to_budget(10_000)
        assert removed == 0
        assert len(history.messages) == 2

    def test_turn_count_property(self) -> None:
        history = ConversationHistory()
        assert history.turn_count == 0
        history.add_message(MessageRole.USER, "Q1")
        assert history.turn_count == 0  # no assistant yet
        history.add_message(MessageRole.ASSISTANT, "A1")
        assert history.turn_count == 1
        history.add_message(MessageRole.USER, "Q2")
        history.add_message(MessageRole.ASSISTANT, "A2")
        assert history.turn_count == 2


# ===================================================================
# ChatMemoryStore
# ===================================================================


class TestChatMemoryStore:
    """Tests for ChatMemoryStore."""

    def _make_memory(self, content: str = "Test insight", topics: list[str] | None = None) -> ChatMemory:
        return ChatMemory(
            id=generate_memory_id(),
            timestamp="2026-04-13T12:00:00+00:00",
            session_id="chat_20260413_120000",
            content=content,
            topics=topics or ["test_subject"],
            memory_type=MemoryType.INSIGHT,
            source_turn=1,
        )

    def test_save_memory_creates_file(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        mem = self._make_memory()
        store.save_memory(mem)
        assert (tmp_path / "chat" / "memories.jsonl").exists()

    def test_save_memory_creates_dir(self, tmp_path: Path) -> None:
        chat_dir = tmp_path / "chat" / "nested"
        store = ChatMemoryStore(chat_dir)
        mem = self._make_memory()
        store.save_memory(mem)
        assert chat_dir.exists()

    def test_save_and_load_memory(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        mem = self._make_memory("Important finding about Acme")
        store.save_memory(mem)
        loaded = store.load_recent_memories(limit=10)
        assert len(loaded) == 1
        assert loaded[0].content == "Important finding about Acme"

    def test_search_memories_returns_relevant(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        store.save_memory(self._make_memory("Change of control clause in MSA", ["acme", "change_of_control"]))
        store.save_memory(self._make_memory("Revenue recognition issue", ["beta", "revenue"]))
        store.save_memory(self._make_memory("IP assignment gap", ["acme", "ip_ownership"]))

        results = store.search_memories("change of control")
        assert len(results) >= 1
        assert "change of control" in results[0].content.lower()

    def test_search_memories_respects_limit(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        for i in range(10):
            store.save_memory(self._make_memory(f"Finding number {i}", ["topic"]))
        results = store.search_memories("finding", limit=3)
        assert len(results) <= 3

    def test_search_memories_empty_store(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        results = store.search_memories("anything")
        assert results == []

    def test_search_memories_no_match(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        store.save_memory(self._make_memory("Alpha bravo charlie"))
        results = store.search_memories("xyz123nonexistent")
        # May return empty or low-score results
        for r in results:
            assert isinstance(r, ChatMemory)

    def test_load_recent_memories(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        for i in range(5):
            store.save_memory(self._make_memory(f"Memory {i}"))
        recent = store.load_recent_memories(limit=3)
        assert len(recent) == 3
        # Should be the last 3
        assert "Memory 4" in recent[-1].content

    def test_memory_count(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        assert store.memory_count == 0
        store.save_memory(self._make_memory())
        assert store.memory_count == 1
        store.save_memory(self._make_memory("Second"))
        assert store.memory_count == 2

    def test_save_session_transcript(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        store.ensure_dirs()
        messages = [
            ChatMessage(role=MessageRole.USER, content="Hello"),
            ChatMessage(role=MessageRole.ASSISTANT, content="Hi there"),
        ]
        store.save_session_transcript("chat_20260413_120000", messages)
        path = tmp_path / "chat" / "sessions" / "chat_20260413_120000.jsonl"
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_update_and_load_session_index(self, tmp_path: Path) -> None:
        store = ChatMemoryStore(tmp_path / "chat")
        meta = SessionMetadata(
            session_id="chat_20260413_120000",
            start_time="2026-04-13T12:00:00+00:00",
            turn_count=5,
            run_id="run_20260413_100000_abc",
            memory_count=2,
        )
        store.update_session_index(meta)
        loaded = store.load_session_index()
        assert len(loaded) == 1
        assert loaded[0].session_id == "chat_20260413_120000"
        assert loaded[0].turn_count == 5


# ===================================================================
# ChatContextBuilder
# ===================================================================


class TestChatContextBuilder:
    """Tests for ChatContextBuilder."""

    @pytest.fixture()
    def mock_index(self) -> Any:
        """Create a minimal FindingIndex-like object."""

        findings = [
            {
                "severity": "P0",
                "agent": "legal",
                "_subject_safe_name": "acme_corp",
                "title": "Change of control termination",
                "citations": [{"source_path": "MSA.pdf", "page_number": 15}],
                "category": "change_of_control",
            },
            {
                "severity": "P1",
                "agent": "finance",
                "_subject_safe_name": "beta_inc",
                "title": "Revenue recognition concern",
                "citations": [{"source_path": "LOI.pdf", "page_number": 3}],
                "category": "revenue",
            },
            {
                "severity": "P2",
                "agent": "commercial",
                "_subject_safe_name": "acme_corp",
                "title": "SLA compliance gap",
                "citations": [],
                "category": "sla_compliance",
            },
        ]
        from dd_agents.query.indexer import FindingIndexer

        return FindingIndexer().index_findings(findings)

    def test_build_system_prompt_includes_findings_summary(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        prompt = builder.build_system_prompt()
        assert "3 findings indexed" in prompt

    def test_build_system_prompt_includes_constraints(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        prompt = builder.build_system_prompt()
        assert "Do NOT attempt to use Bash" in prompt
        assert "save_memory" in prompt

    def test_build_system_prompt_includes_memory_instructions(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        prompt = builder.build_system_prompt()
        assert "search_chat_memory" in prompt

    def test_build_system_prompt_includes_prior_memories(self, mock_index: Any, tmp_path: Path) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        store = ChatMemoryStore(tmp_path / "chat")
        mem = ChatMemory(
            id="abc123",
            timestamp="2026-04-13T12:00:00+00:00",
            session_id="chat_20260413_120000",
            content="Acme MSA has a 30-day cure period for CoC.",
            topics=["acme_corp", "change_of_control"],
            memory_type=MemoryType.INSIGHT,
        )
        store.save_memory(mem)

        builder = ChatContextBuilder(finding_index=mock_index, memory_store=store)
        prompt = builder.build_system_prompt()
        assert "MEMORIES FROM PRIOR SESSIONS" in prompt
        assert "30-day cure period" in prompt

    def test_build_system_prompt_no_memories(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index, memory_store=None)
        prompt = builder.build_system_prompt()
        assert "MEMORIES FROM PRIOR SESSIONS" not in prompt

    def test_findings_digest_p0_before_p1(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        digest = builder.build_findings_digest()
        p0_pos = digest.find("CRITICAL FINDINGS (P0)")
        p1_pos = digest.find("HIGH FINDINGS (P1)")
        assert p0_pos >= 0
        assert p1_pos >= 0
        assert p0_pos < p1_pos

    def test_findings_digest_respects_max_chars(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        digest = builder.build_findings_digest(max_chars=100)
        assert len(digest) <= 200  # some slack for section headers

    def test_build_turn_prompt_with_history(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        history = ConversationHistory()
        history.add_message(MessageRole.USER, "Previous question")
        history.add_message(MessageRole.ASSISTANT, "Previous answer")
        prompt = builder.build_turn_prompt("Current question", history)
        assert "<conversation_history>" in prompt
        assert "Previous question" in prompt
        assert "Current question" in prompt

    def test_build_turn_prompt_without_history(self, mock_index: Any) -> None:
        from dd_agents.chat.context import ChatContextBuilder

        builder = ChatContextBuilder(finding_index=mock_index)
        history = ConversationHistory()
        prompt = builder.build_turn_prompt("My question", history)
        assert "My question" in prompt
        assert "<conversation_history>" not in prompt


# ===================================================================
# ChatEngine
# ===================================================================


class TestChatEngine:
    """Tests for ChatEngine (SDK mocked)."""

    @pytest.fixture()
    def run_dir(self, tmp_path: Path) -> Path:
        """Create a minimal run directory with findings."""
        run = tmp_path / "_dd" / "forensic-dd" / "runs" / "latest"
        merged = run / "findings" / "merged"
        merged.mkdir(parents=True)
        findings = [
            {"severity": "P0", "agent": "legal", "_subject_safe_name": "acme", "title": "CoC risk", "citations": []},
        ]
        (merged / "acme.json").write_text(json.dumps({"findings": findings}))
        return run

    @pytest.fixture()
    def project_dir(self, run_dir: Path) -> Path:
        """Return the project dir (parent of _dd/)."""
        return run_dir.parent.parent.parent.parent

    def test_engine_init_loads_index(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import ChatEngine

        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir)
        assert engine.finding_count == 1

    def test_engine_properties(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import ChatEngine

        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir)
        assert engine.session_cost == 0.0
        assert engine.turn_count == 0
        assert engine.history_chars == 0

    @pytest.mark.skipif(
        not _sdk_available(),
        reason="claude-agent-sdk not installed",
    )
    async def test_ask_budget_enforcement(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import BudgetExhaustedError, ChatConfig, ChatEngine

        config = ChatConfig(max_session_cost=0.0)
        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir, config=config)
        with pytest.raises(BudgetExhaustedError):
            await engine.ask("test")

    def test_allowed_tools_with_tools(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import CHAT_MCP_TOOL_NAMES, ChatConfig, ChatEngine

        config = ChatConfig(enable_tools=True)
        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir, config=config)
        tools = engine._get_allowed_tools()
        assert "Read" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        for t in CHAT_MCP_TOOL_NAMES:
            assert f"mcp__dd_tools__{t}" in tools

    def test_allowed_tools_without_tools(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import ChatConfig, ChatEngine

        config = ChatConfig(enable_tools=False)
        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir, config=config)
        tools = engine._get_allowed_tools()
        assert tools == []

    def test_no_stop_hooks(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import ChatEngine

        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir)
        hooks = engine._build_hooks()
        if hooks is not None:
            assert "Stop" not in hooks
            assert "PreToolUse" in hooks

    def test_memory_store_initialized(self, run_dir: Path, project_dir: Path) -> None:
        from dd_agents.chat.engine import ChatEngine

        engine = ChatEngine(run_dir=run_dir, project_dir=project_dir)
        assert engine._memory_store is not None
        assert (project_dir / "_dd" / "forensic-dd" / "chat").is_dir()


# ===================================================================
# Tool server integration
# ===================================================================


class TestToolServerChat:
    """Tests for chat tool configuration in server.py."""

    def test_get_tools_for_chat(self) -> None:
        from dd_agents.tools.server import get_tools_for_agent

        tools = get_tools_for_agent("chat")
        assert len(tools) == 10

    def test_chat_tools_include_memory(self) -> None:
        from dd_agents.tools.server import get_tools_for_agent

        tools = get_tools_for_agent("chat")
        assert "save_memory" in tools
        assert "search_chat_memory" in tools

    def test_chat_tools_exclude_validation(self) -> None:
        from dd_agents.tools.server import get_tools_for_agent

        tools = get_tools_for_agent("chat")
        assert "validate_finding" not in tools
        assert "validate_gap" not in tools
        assert "validate_manifest" not in tools
        assert "report_progress" not in tools


# ===================================================================
# CLI
# ===================================================================


class TestChatCLI:
    """Tests for the chat CLI command."""

    def test_chat_help(self) -> None:
        from dd_agents.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["chat", "--help"])
        assert result.exit_code == 0
        assert "Interactive chat" in result.output

    def test_chat_options_present(self) -> None:
        from dd_agents.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["chat", "--help"])
        assert "--report" in result.output
        assert "--model" in result.output
        assert "--max-cost" in result.output
        assert "--no-tools" in result.output
        assert "--verbose" in result.output


# ===================================================================
# Chronicle InteractionType
# ===================================================================


class TestChronicleChat:
    """Tests for CHAT interaction type in chronicle."""

    def test_chat_interaction_type_exists(self) -> None:
        from dd_agents.knowledge.chronicle import InteractionType

        assert InteractionType.CHAT == "chat"
        assert InteractionType.CHAT.value == "chat"


# ===================================================================
# Helpers
# ===================================================================


def _sdk_available() -> bool:
    """Check if claude-agent-sdk is importable."""
    try:
        import claude_agent_sdk  # noqa: F401

        return True
    except ImportError:
        return False
