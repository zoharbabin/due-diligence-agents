"""Judge claim verification with web research (Issue #274, phase 2).

No network and no real MCP server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from dd_agents.agents.judge import JudgeAgent
from dd_agents.models.audit import WebCheck
from dd_agents.models.config import DealConfig

if TYPE_CHECKING:
    from pathlib import Path


def _deal(*, web: bool, external: bool) -> DealConfig:
    raw: dict[str, Any] = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer A"},
        "target": {"name": "Subject A"},
        "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
        "judge": {"web_research_enabled": web},
        "external_verification": {"enabled": external},
    }
    return DealConfig.model_validate(raw)


def _judge(tmp_path: Path, deal: DealConfig | None) -> JudgeAgent:
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    return JudgeAgent(tmp_path, run_dir, "run_1", deal_config=deal)


def _check(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "finding_id": "forensic-dd_legal_subject_a_0001",
        "agent": "legal",
        "analysis_unit": "subject_a",
        "query": "Subject A litigation",
        "source_url": "https://example.invalid/case/1",
        "access_date": "2026-11-14",
        "result": "corroborates",
    }
    base.update(over)
    return base


class TestAccess:
    def test_default_judge_has_no_external_access(self, tmp_path: Path) -> None:
        assert _judge(tmp_path, None).get_external_access() is None
        assert _judge(tmp_path, _deal(web=False, external=False)).get_external_access() is None

    def test_flag_off_with_external_on_gives_nothing(self, tmp_path: Path) -> None:
        assert _judge(tmp_path, _deal(web=False, external=True)).get_external_access() is None

    def test_flag_on_with_external_on_gives_allowlisted_tools(self, tmp_path: Path) -> None:
        access = _judge(tmp_path, _deal(web=True, external=True)).get_external_access()
        assert access is not None
        assert access.tool_names
        assert all(name.startswith("mcp__web-researcher__") for name in access.tool_names)
        assert not any(name.endswith("archive_source") for name in access.tool_names)

    def test_flag_on_with_external_off_warns_and_gives_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            access = _judge(tmp_path, _deal(web=True, external=False)).get_external_access()
        assert access is None
        assert "external_verification" in caplog.text


class TestPrompt:
    def test_flag_off_prompt_is_unchanged(self, tmp_path: Path) -> None:
        plain = _judge(tmp_path, None).build_prompt({})
        off = _judge(tmp_path, _deal(web=False, external=True)).build_prompt({})
        assert plain == off
        assert "WEB VERIFICATION" not in plain

    def test_flag_on_adds_section_before_output(self, tmp_path: Path) -> None:
        plain = _judge(tmp_path, None).build_prompt({})
        prompt = _judge(tmp_path, _deal(web=True, external=True)).build_prompt({})
        assert "## WEB VERIFICATION" in prompt
        assert prompt.index("## WEB VERIFICATION") < prompt.index("## OUTPUT")
        assert "web_checks.json" in prompt
        assert "access_date" in prompt
        assert "not clearance" in prompt.lower()
        # Only the new section differs.
        assert prompt.replace(prompt[prompt.index("## WEB VERIFICATION") : prompt.index("## OUTPUT")], "") == plain

    def test_section_forbids_sending_document_text(self, tmp_path: Path) -> None:
        prompt = _judge(tmp_path, _deal(web=True, external=True)).build_prompt({})
        assert "entity names" in prompt
        assert "never send" in prompt.lower()

    def test_flag_on_without_external_leaves_prompt_unchanged(self, tmp_path: Path) -> None:
        plain = _judge(tmp_path, None).build_prompt({})
        assert _judge(tmp_path, _deal(web=True, external=False)).build_prompt({}) == plain


class TestWebCheck:
    def test_valid_check_defaults_to_low_confidence(self) -> None:
        check = WebCheck.model_validate(_check())
        assert check.confidence == "low"
        assert check.corroborated_by_data_room is False

    def test_access_date_is_required(self) -> None:
        with pytest.raises(ValidationError):
            WebCheck.model_validate(_check(access_date=""))
        raw = _check()
        del raw["access_date"]
        with pytest.raises(ValidationError):
            WebCheck.model_validate(raw)

    def test_higher_confidence_needs_data_room_corroboration(self) -> None:
        with pytest.raises(ValidationError):
            WebCheck.model_validate(_check(confidence="medium"))
        ok = WebCheck.model_validate(_check(confidence="medium", corroborated_by_data_room=True))
        assert ok.confidence == "medium"

    def test_unavailable_result_is_allowed_without_url(self) -> None:
        check = WebCheck.model_validate(_check(result="unavailable", source_url=""))
        assert check.result == "unavailable"

    def test_unknown_result_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WebCheck.model_validate(_check(result="cleared"))
