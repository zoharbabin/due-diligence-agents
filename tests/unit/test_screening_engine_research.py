"""Engine wiring of officer discovery and profile research in step 26 (Issue #274).

Runners are replaced with stubs. No agent, network or real list is used.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from dd_agents.orchestrator.engine import PipelineEngine
from dd_agents.orchestrator.state import PipelineState
from dd_agents.screening.research import LEADS_FILE, OFFICERS_FILE
from dd_agents.screening.step import COVERAGE_FILE, SCREENING_AGENT, SCREENING_RUN_DIR

if TYPE_CHECKING:
    from pathlib import Path

COMPANY = "Fabricated Holdings Limited"
OFFICER = "Rowan Pellegrino Madeup"
TODAY = "2026-11-14"


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DD_SCREENING_DIR", str(tmp_path / "screening-home"))


def _engine(tmp_path: Path, screening: dict[str, Any], *, external: bool) -> tuple[PipelineEngine, PipelineState]:
    raw: dict[str, Any] = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer Placeholder"},
        "target": {"name": COMPANY},
        "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
        "screening": {"enabled": True, **screening},
        "external_verification": {"enabled": external},
    }
    config_path = tmp_path / "deal-config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    engine = PipelineEngine(tmp_path, config_path)
    state = PipelineState(project_dir=tmp_path.resolve())
    state.run_id = "run_test"
    state.run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_test"
    state.run_dir.mkdir(parents=True)
    state.deal_config = raw
    state.subject_safe_names = ["imaginary_ventures_group"]
    text_dir = engine._text_dir(state)
    text_dir.mkdir(parents=True)
    (text_dir / "minutes.md").write_text(f"{OFFICER} was appointed Managing Director.", encoding="utf-8")
    return engine, state


class _Stub:
    """Writes *payload* to ``run_dir/screening/<file>`` when run."""

    file = ""
    payload: list[dict[str, Any]] = []
    prompts: list[str] = []
    init_args: list[dict[str, Any]] = []

    def __init__(self, project_dir: Path, run_dir: Path, run_id: str, deal_config: Any = None, **kw: Any) -> None:
        self.run_dir = run_dir
        type(self).init_args.append({"deal_config": deal_config, **kw})

    async def run(self, state: dict[str, Any], *, on_turn: Any | None = None) -> dict[str, Any]:
        type(self).prompts.append(state["prompt"])
        out = self.run_dir / SCREENING_RUN_DIR / self.file
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.payload), encoding="utf-8")
        return {"status": "success", "error": None}


def _install(monkeypatch: pytest.MonkeyPatch, officers: list[dict[str, Any]], leads: list[dict[str, Any]]) -> None:
    class Discovery(_Stub):
        file = OFFICERS_FILE
        payload = officers
        prompts: list[str] = []  # noqa: RUF012
        init_args: list[dict[str, Any]] = []  # noqa: RUF012

    class Research(_Stub):
        file = LEADS_FILE
        payload = leads
        prompts: list[str] = []  # noqa: RUF012
        init_args: list[dict[str, Any]] = []  # noqa: RUF012

    import dd_agents.agents.screening_research as mod

    monkeypatch.setattr(mod, "OfficerDiscoveryRunner", Discovery)
    monkeypatch.setattr(mod, "ProfileResearchRunner", Research)


def _officer() -> dict[str, Any]:
    return {
        "name": OFFICER,
        "title": "Managing Director",
        "company": COMPANY,
        "source_file": "minutes.md",
        "quote": f"{OFFICER} was appointed Managing Director",
    }


def _lead(name: str = OFFICER) -> dict[str, Any]:
    return {
        "target_name": name,
        "target_kind": "person",
        "category": "litigation",
        "result": "found",
        "query": f"{name} litigation",
        "source_url": "https://example.invalid/case/1",
        "summary": "A court record names a person with this name.",
        "quote": "Madeup, defendant",
        "access_date": TODAY,
    }


def _coverage(state: PipelineState) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((state.run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).read_text())
    return data


class TestOff:
    async def test_defaults_run_no_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [_officer()], [_lead()])
        engine, state = _engine(tmp_path, {}, external=True)
        await engine._step_26_external_screening(state)
        cov = _coverage(state)
        assert "officer_discovery" not in cov
        assert "profile_research" not in cov
        assert not (state.run_dir / SCREENING_RUN_DIR / OFFICERS_FILE).exists()
        assert not (state.run_dir / SCREENING_RUN_DIR / LEADS_FILE).exists()


class TestDiscovery:
    async def test_verified_officer_is_screened_and_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [_officer()], [])
        engine, state = _engine(tmp_path, {"discover_officers": True}, external=False)
        await engine._step_26_external_screening(state)
        block = _coverage(state)["officer_discovery"]
        assert block["ran"] is True
        assert block["accepted"] == 1
        assert block["rejected"] == 0
        assert "profile_research" not in _coverage(state)

    async def test_unverified_quote_is_dropped_and_counted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = {**_officer(), "quote": "text that is not in the file"}
        _install(monkeypatch, [bad], [])
        engine, state = _engine(tmp_path, {"discover_officers": True}, external=False)
        await engine._step_26_external_screening(state)
        block = _coverage(state)["officer_discovery"]
        assert block["accepted"] == 0
        assert block["rejected"] == 1

    async def test_off_when_people_screening_is_off(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [_officer()], [])
        engine, state = _engine(tmp_path, {"discover_officers": True, "people": False}, external=False)
        await engine._step_26_external_screening(state)
        assert "officer_discovery" not in _coverage(state)


class TestProfileResearch:
    async def test_lead_becomes_low_confidence_dated_finding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [_officer()], [_lead()])
        engine, state = _engine(tmp_path, {"discover_officers": True, "profile_research": True}, external=True)
        await engine._step_26_external_screening(state)
        block = _coverage(state)["profile_research"]
        assert block["ran"] is True
        assert block["found"] == 1
        files = list((state.run_dir / "findings" / SCREENING_AGENT).glob("*.json"))
        text = "".join(f.read_text() for f in files)
        assert "web_research" in text
        assert TODAY in text
        assert '"confidence": "low"' in text

    async def test_names_sent_include_the_discovered_officer_only_as_a_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [_officer()], [])
        engine, state = _engine(tmp_path, {"discover_officers": True, "profile_research": True}, external=True)
        await engine._step_26_external_screening(state)
        import dd_agents.agents.screening_research as mod

        (prompt,) = mod.ProfileResearchRunner.prompts  # type: ignore[attr-defined]
        assert OFFICER in prompt
        assert "minutes.md" not in prompt
        assert "Managing Director was appointed" not in prompt

    async def test_research_without_external_access_is_a_visible_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [], [_lead()])
        engine, state = _engine(tmp_path, {"profile_research": True}, external=False)
        await engine._step_26_external_screening(state)
        block = _coverage(state)["profile_research"]
        assert block["ran"] is False
        assert block["complete"] is False
        assert "external_verification.enabled" in block["detail"]
        import dd_agents.agents.screening_research as mod

        assert mod.ProfileResearchRunner.prompts == []  # type: ignore[attr-defined]

    async def test_incomplete_lookup_is_flagged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        unavailable = {**_lead(COMPANY), "target_kind": "organization", "result": "unavailable", "source_url": ""}
        _install(monkeypatch, [], [unavailable])
        engine, state = _engine(tmp_path, {"profile_research": True}, external=True)
        await engine._step_26_external_screening(state)
        assert _coverage(state)["profile_research"]["complete"] is False
