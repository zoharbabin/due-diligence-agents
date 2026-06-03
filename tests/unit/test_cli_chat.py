"""CLI tests for the `dd-agents chat` command headless mode (F2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from dd_agents.chat import ChatResponse
from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def _make_run_dir(tmp_path: Path) -> Path:
    """Create a minimal pipeline run directory."""
    run_dir = tmp_path / "run"
    (run_dir / "findings" / "merged").mkdir(parents=True)
    return run_dir


def test_chat_question_headless_exit_zero(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    canned = ChatResponse(text="The top risk is change-of-control.")

    fake_engine = MagicMock()

    async def _ask(*_a: Any, **_kw: Any) -> ChatResponse:
        return canned

    async def _close(*_a: Any, **_kw: Any) -> None:
        return None

    fake_engine.ask.side_effect = _ask
    fake_engine.close.side_effect = _close

    with patch("dd_agents.chat.ChatEngine", return_value=fake_engine):
        result = CliRunner().invoke(
            main,
            ["chat", "--report", str(run_dir), "--question", "hi"],
        )

    assert result.exit_code == 0, result.output
    assert "The top risk is change-of-control." in result.output


def test_chat_question_does_not_enter_interactive_loop(tmp_path: Path) -> None:
    run_dir = _make_run_dir(tmp_path)
    fake_engine = MagicMock()

    async def _ask(*_a: Any, **_kw: Any) -> ChatResponse:
        return ChatResponse(text="answer")

    async def _close(*_a: Any, **_kw: Any) -> None:
        return None

    fake_engine.ask.side_effect = _ask
    fake_engine.close.side_effect = _close

    # If the interactive loop were entered, PromptSession would be constructed.
    with (
        patch("dd_agents.chat.ChatEngine", return_value=fake_engine),
        patch("prompt_toolkit.PromptSession") as mock_session,
    ):
        result = CliRunner().invoke(
            main,
            ["chat", "--report", str(run_dir), "-q", "hi"],
        )

    assert result.exit_code == 0, result.output
    mock_session.assert_not_called()
    fake_engine.ask.assert_called_once()
