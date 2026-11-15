"""Officer discovery and public-source profile research (Issue #274, phase 3b).

Synthetic names only. The agents are stubbed: no LLM call, no network, no MCP server.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from dd_agents.models.config import DealConfig, ScreeningConfig
from dd_agents.screening.research import (
    LEADS_FILE,
    OFFICERS_FILE,
    OfficerCandidate,
    ProfileLead,
    apply_leads,
    read_records,
    run_officer_discovery,
    run_profile_research,
    select_research_targets,
    verify_officers,
)
from dd_agents.screening.step import COVERAGE_FILE, SCREENING_AGENT, SCREENING_RUN_DIR, TARGET_STEM, build_targets

if TYPE_CHECKING:
    from pathlib import Path

PERSON = "Zelda Quintero Fakename"
OFFICER = "Imogen Placeholder Brandt"
COMPANY = "Fabricated Holdings Limited"
TODAY = "2026-11-14"


def _config(**screening: Any) -> DealConfig:
    return DealConfig.model_validate(
        {
            "config_version": "1.0.0",
            "buyer": {"name": "Buyer Placeholder"},
            "target": {"name": COMPANY},
            "key_executives": [{"name": PERSON, "title": "Chief Placeholder", "company": COMPANY}],
            "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
            "external_verification": {"enabled": True},
            "screening": {"enabled": True, "profile_research": True, **screening},
        }
    )


def _lead(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "target_name": PERSON,
        "target_kind": "person",
        "category": "litigation",
        "result": "found",
        "query": f"{PERSON} litigation",
        "source_url": "https://example.invalid/case/9",
        "summary": "A court record names a person with this name as a defendant.",
        "quote": "Quintero Fakename, defendant",
        "access_date": TODAY,
    }
    base.update(over)
    return base


class FakeRunner:
    """Stands in for an agent runner. Writes what the test gives it."""

    def __init__(self, output: Path, payload: list[dict[str, Any]] | str | None, status: str = "success") -> None:
        self.output = output
        self.payload = payload
        self.status = status
        self.prompt = ""

    async def run(self, state: dict[str, Any], *, on_turn: Any | None = None) -> dict[str, Any]:
        self.prompt = state["prompt"]
        if self.payload is not None:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
            self.output.write_text(text, encoding="utf-8")
        return {"status": self.status, "error": None if self.status == "success" else "boom"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_off_by_default(self) -> None:
        cfg = ScreeningConfig()
        assert (cfg.discover_officers, cfg.profile_research) == (False, False)

    @pytest.mark.parametrize("bad", [0, 201])
    def test_cap_bounds(self, bad: int) -> None:
        with pytest.raises(ValidationError):
            ScreeningConfig(research_max_targets=bad)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


class TestRecords:
    def test_found_lead_needs_source_summary_quote(self) -> None:
        for field in ("source_url", "summary", "quote"):
            with pytest.raises(ValidationError):
                ProfileLead.model_validate(_lead(**{field: ""}))

    def test_access_date_must_be_a_date(self) -> None:
        with pytest.raises(ValidationError):
            ProfileLead.model_validate(_lead(access_date="today"))

    def test_no_result_lead_needs_no_source(self) -> None:
        lead = ProfileLead.model_validate(_lead(result="no_result", source_url="", summary="", quote=""))
        assert lead.result == "no_result"

    def test_unknown_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProfileLead.model_validate(_lead(category="cleared"))

    def test_null_optional_fields_are_empty_strings(self) -> None:
        lead = ProfileLead.model_validate(
            _lead(result="no_result", source_url=None, summary=None, quote=None, query=None)
        )
        assert (lead.source_url, lead.quote, lead.summary, lead.query) == ("", "", "", "")

    def test_null_officer_title_and_company_are_empty(self) -> None:
        cand = OfficerCandidate.model_validate(
            {"name": OFFICER, "title": None, "company": None, "source_file": "a.md", "quote": f"{OFFICER} signed"}
        )
        assert (cand.title, cand.company) == ("", "")

    def test_prompts_name_every_record_field_and_category(self) -> None:
        """The agents only know the record shape from their prompt. Keep the two in sync."""
        from typing import get_args

        from dd_agents.agents.prompts.loader import load_named_prompt
        from dd_agents.screening.research import ResearchCategory

        research = load_named_prompt("screening", "profile_research")
        for name in ProfileLead.model_fields:
            assert f"`{name}`" in research, name
        for category in get_args(ResearchCategory):
            assert f"`{category}`" in research, category
        discovery = load_named_prompt("screening", "officer_discovery")
        for name in OfficerCandidate.model_fields:
            assert f"`{name}`" in discovery, name

    def test_read_records_counts_invalid_entries(self, tmp_path: Path) -> None:
        path = tmp_path / LEADS_FILE
        path.write_text(json.dumps([_lead(), {"target_name": "x"}, "junk"]), encoding="utf-8")
        records, invalid = read_records(path, ProfileLead)
        assert len(records) == 1
        assert invalid == 2

    @pytest.mark.parametrize("content", ["not json", '{"a": 1}', ""])
    def test_read_records_bad_file_is_empty_and_flagged(self, tmp_path: Path, content: str) -> None:
        path = tmp_path / LEADS_FILE
        path.write_text(content, encoding="utf-8")
        assert read_records(path, ProfileLead) == ([], 1)

    def test_read_records_missing_file(self, tmp_path: Path) -> None:
        assert read_records(tmp_path / "nope.json", ProfileLead) == ([], 0)


# ---------------------------------------------------------------------------
# Officer verification
# ---------------------------------------------------------------------------


def _candidate(**over: Any) -> OfficerCandidate:
    base: dict[str, Any] = {
        "name": OFFICER,
        "title": "Managing Director",
        "company": COMPANY,
        "source_file": "board_minutes.md",
        "quote": f"{OFFICER} was appointed Managing Director",
    }
    base.update(over)
    return OfficerCandidate.model_validate(base)


class TestVerifyOfficers:
    def _text(self, tmp_path: Path, body: str) -> Path:
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        (text_dir / "board_minutes.md").write_text(body, encoding="utf-8")
        return text_dir

    def test_quote_in_file_is_accepted(self, tmp_path: Path) -> None:
        text_dir = self._text(tmp_path, f"Minutes.\n{OFFICER} was appointed\nManaging Director on 1 May.")
        accepted, rejected = verify_officers([_candidate()], text_dir)
        assert [c.name for c in accepted] == [OFFICER]
        assert rejected == 0

    def test_quote_not_in_file_is_dropped(self, tmp_path: Path) -> None:
        text_dir = self._text(tmp_path, "Nothing about anyone here.")
        assert verify_officers([_candidate()], text_dir) == ([], 1)

    def test_name_must_be_inside_the_quote(self, tmp_path: Path) -> None:
        text_dir = self._text(tmp_path, "The Managing Director signed.")
        accepted, rejected = verify_officers([_candidate(quote="The Managing Director signed.")], text_dir)
        assert accepted == []
        assert rejected == 1

    def test_missing_file_is_dropped(self, tmp_path: Path) -> None:
        text_dir = self._text(tmp_path, "x")
        assert verify_officers([_candidate(source_file="other.md")], text_dir) == ([], 1)

    @pytest.mark.parametrize("path", ["../secret.md", "/etc/hosts", "a/../../b.md"])
    def test_path_escape_is_dropped(self, tmp_path: Path, path: str) -> None:
        text_dir = self._text(tmp_path, "x")
        assert verify_officers([_candidate(source_file=path)], text_dir) == ([], 1)

    def test_duplicates_collapse(self, tmp_path: Path) -> None:
        text_dir = self._text(tmp_path, f"{OFFICER} was appointed Managing Director")
        accepted, _ = verify_officers([_candidate(), _candidate()], text_dir)
        assert len(accepted) == 1


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


class TestSelectTargets:
    def test_target_and_executives_come_first_and_cap_applies(self) -> None:
        subjects = [(f"Entity {i} Placeholder", f"entity_{i}") for i in range(10)]
        owned = build_targets(_config(), subjects)
        picked = select_research_targets(owned, 3)
        assert len(picked) == 3
        # The target company and its one executive fill the first two slots.
        assert [o.stem for o in picked[:2]] == [TARGET_STEM, TARGET_STEM]

    def test_extra_people_are_screened_with_a_role(self) -> None:
        owned = build_targets(_config(), [], extra_people=[(OFFICER, "officer found in board_minutes.md")])
        found = [o for o in owned if o.target.name == OFFICER]
        assert found
        assert found[0].target.kind == "person"
        assert found[0].stem == TARGET_STEM


# ---------------------------------------------------------------------------
# Applying leads
# ---------------------------------------------------------------------------


class TestApplyLeads:
    def _owned(self) -> list[Any]:
        return build_targets(_config(), [])

    def test_found_lead_becomes_low_confidence_dated_web_finding(self, tmp_path: Path) -> None:
        owned = self._owned()
        outcome = apply_leads(tmp_path, owned, [ProfileLead.model_validate(_lead())])
        data = json.loads((tmp_path / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json").read_text())
        (finding,) = data["findings"]
        assert outcome.found == 1
        assert finding["confidence"] == "low"
        assert finding["severity"] == "P2"
        (citation,) = finding["citations"]
        assert citation["source_type"] == "web_research"
        assert citation["access_date"] == TODAY
        assert citation["source_path"] == "https://example.invalid/case/9"
        assert "needs review" in finding["title"].lower()
        assert "not clearance" not in finding["description"].lower() or "lead" in finding["description"].lower()
        assert finding["metadata"]["profile_research"]["category"] == "litigation"

    def test_appends_to_existing_screening_file(self, tmp_path: Path) -> None:
        owned = self._owned()
        folder = tmp_path / "findings" / SCREENING_AGENT
        folder.mkdir(parents=True)
        (folder / f"{TARGET_STEM}.json").write_text(
            json.dumps(
                {"agent": SCREENING_AGENT, "subject": "x", "subject_safe_name": TARGET_STEM, "findings": [{"id": 1}]}
            )
        )
        apply_leads(tmp_path, owned, [ProfileLead.model_validate(_lead())])
        data = json.loads((folder / f"{TARGET_STEM}.json").read_text())
        assert len(data["findings"]) == 2
        assert data["findings"][0] == {"id": 1}

    def test_unknown_target_is_dropped_and_counted(self, tmp_path: Path) -> None:
        lead = ProfileLead.model_validate(_lead(target_name="Somebody Invented Entirely"))
        outcome = apply_leads(tmp_path, self._owned(), [lead])
        assert outcome.found == 0
        assert outcome.unmatched == 1
        assert not (tmp_path / "findings").exists()

    def test_target_without_any_record_is_not_researched(self, tmp_path: Path) -> None:
        owned = self._owned()
        lead = ProfileLead.model_validate(_lead(result="no_result", source_url="", summary="", quote=""))
        outcome = apply_leads(tmp_path, owned, [lead])
        assert outcome.no_result == 1
        assert COMPANY in outcome.not_researched
        assert PERSON not in outcome.not_researched

    def test_unavailable_counts_and_is_not_clearance(self, tmp_path: Path) -> None:
        lead = ProfileLead.model_validate(_lead(result="unavailable", source_url="", summary="", quote=""))
        outcome = apply_leads(tmp_path, self._owned(), [lead])
        assert outcome.unavailable == 1
        assert outcome.complete is False

    def test_leads_per_target_are_capped(self, tmp_path: Path) -> None:
        leads = [ProfileLead.model_validate(_lead(source_url=f"https://example.invalid/{i}")) for i in range(9)]
        outcome = apply_leads(tmp_path, self._owned(), leads)
        assert outcome.found == 5


# ---------------------------------------------------------------------------
# Orchestration with stub runners
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunProfileResearch:
    async def test_end_to_end_with_stub(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        owned = build_targets(_config(), [])
        records = [
            _lead(),
            _lead(
                target_name=COMPANY, target_kind="organization", result="no_result", source_url="", summary="", quote=""
            ),
        ]
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / LEADS_FILE, records)
        outcome = await run_profile_research(runner=runner, owned=owned, run_dir=run_dir, today=TODAY)
        assert outcome is not None
        assert (outcome.found, outcome.no_result) == (1, 1)
        coverage = json.loads((run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).read_text())
        block = coverage["profile_research"]
        assert block["ran"] is True
        assert block["found"] == 1
        assert block["complete"] is True

    async def test_prompt_has_names_only_and_wraps_them(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        owned = build_targets(_config(), [])
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / LEADS_FILE, [])
        await run_profile_research(runner=runner, owned=owned, run_dir=run_dir, today=TODAY)
        assert PERSON in runner.prompt
        assert "UNTRUSTED" in runner.prompt.upper()
        assert TODAY in runner.prompt

    async def test_agent_failure_is_an_incomplete_screen_not_an_error(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        owned = build_targets(_config(), [])
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / LEADS_FILE, None, status="timeout")
        outcome = await run_profile_research(runner=runner, owned=owned, run_dir=run_dir, today=TODAY)
        assert outcome is not None
        assert outcome.complete is False
        block = json.loads((run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).read_text())["profile_research"]
        assert block["ran"] is False
        assert block["complete"] is False
        assert "timeout" in block["detail"]

    async def test_garbage_output_is_flagged(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        owned = build_targets(_config(), [])
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / LEADS_FILE, "not json")
        outcome = await run_profile_research(runner=runner, owned=owned, run_dir=run_dir, today=TODAY)
        assert outcome is not None
        assert outcome.invalid == 1
        assert outcome.complete is False

    async def test_stale_output_file_is_removed_before_the_run(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        out = run_dir / SCREENING_RUN_DIR / LEADS_FILE
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps([_lead()]))
        owned = build_targets(_config(), [])
        runner = FakeRunner(out, None)
        outcome = await run_profile_research(runner=runner, owned=owned, run_dir=run_dir, today=TODAY)
        assert outcome is not None
        assert outcome.found == 0


@pytest.mark.asyncio
class TestRunOfficerDiscovery:
    async def test_accepted_and_rejected(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        run_dir = tmp_path / "run"
        text_dir = tmp_path / "text"
        text_dir.mkdir()
        (text_dir / "board_minutes.md").write_text(f"{OFFICER} was appointed Managing Director", encoding="utf-8")
        good = {
            "name": OFFICER,
            "title": "Managing Director",
            "company": COMPANY,
            "source_file": "board_minutes.md",
            "quote": f"{OFFICER} was appointed Managing Director",
        }
        bad = {**good, "name": "Invented Person Nowhere", "quote": "Invented Person Nowhere is a director"}
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / OFFICERS_FILE, [good, bad])
        with caplog.at_level(logging.INFO):
            result = await run_officer_discovery(runner=runner, text_dir=text_dir, run_dir=run_dir)
        assert [c.name for c in result.accepted] == [OFFICER]
        assert result.rejected == 1
        result.write_coverage(run_dir)
        block = json.loads((run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).read_text())["officer_discovery"]
        assert block["accepted"] == 1
        assert block["rejected"] == 1
        assert OFFICER not in caplog.text

    async def test_failed_agent_gives_no_officers_and_a_note(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run"
        runner = FakeRunner(run_dir / SCREENING_RUN_DIR / OFFICERS_FILE, None, status="error")
        result = await run_officer_discovery(runner=runner, text_dir=tmp_path, run_dir=run_dir)
        assert result.accepted == []
        result.write_coverage(run_dir)
        block = json.loads((run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).read_text())["officer_discovery"]
        assert block["ran"] is False


class TestHooksForResearchAgents:
    def test_stop_guard_can_be_switched_off(self, tmp_path: Path) -> None:
        from dd_agents.hooks.factory import build_hooks_for_agent

        on = build_hooks_for_agent("x", tmp_path, tmp_path, 1)
        off = build_hooks_for_agent("x", tmp_path, tmp_path, 1, coverage_stop_guard=False)
        assert on is not None and off is not None
        assert "Stop" in on
        assert "Stop" not in off
        assert "PreToolUse" in off

    def test_research_runners_do_not_use_the_coverage_guard(self) -> None:
        from dd_agents.agents.screening_research import OfficerDiscoveryRunner, ProfileResearchRunner

        assert OfficerDiscoveryRunner.coverage_stop_guard is False
        assert ProfileResearchRunner.coverage_stop_guard is False
