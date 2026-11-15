"""Screening pipeline step 26 (Issue #274 phase 3).

Synthetic names only. Lists are written to a temp ``DD_SCREENING_DIR``, so no
test touches the network or the real screening folder.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from dd_agents.errors import BlockingGateError
from dd_agents.models.config import DealConfig, ScreeningConfig
from dd_agents.orchestrator.checkpoints import load_checkpoint_by_step, save_checkpoint
from dd_agents.orchestrator.engine import PipelineEngine
from dd_agents.orchestrator.state import PipelineState
from dd_agents.orchestrator.steps import _CONDITIONAL_STEPS, PipelineStep
from dd_agents.persistence.provenance import (
    compute_persona_hashes,
    compute_provenance_hash,
    screening_persona_texts,
)
from dd_agents.reporting.merge import FindingMerger
from dd_agents.screening import store
from dd_agents.screening.models import ListEntry, ListSnapshot
from dd_agents.screening.step import (
    CATEGORY,
    COVERAGE_FILE,
    NOT_COVERED,
    SCREENING_AGENT,
    SCREENING_RUN_DIR,
    TARGET_STEM,
    build_targets,
    run_screening,
)
from dd_agents.screening.user_lists import load_user_screening

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
PERSON = "Zelda Quintero Fakename"
COMPANY = "Fabricated Holdings Limited"
SUBJECT = "Imaginary Ventures Group"


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "screening-home"
    monkeypatch.setenv("DD_SCREENING_DIR", str(home))
    return home


def _save(source: str, entries: list[ListEntry], *, age_days: int = 0) -> None:
    fetched = (NOW - timedelta(days=age_days)).isoformat()
    store.save_snapshot(
        ListSnapshot(
            source=source,
            source_url="https://example.invalid/list",
            fetched_at=fetched,
            published=fetched[:10],
            sha256="0" * 64,
            entries=entries,
        )
    )


def _all_lists(*, person_year: int = 1970, org_name: str = COMPANY) -> None:
    _save(
        "ofac_sdn",
        [
            ListEntry(
                source="ofac_sdn",
                uid="11",
                name=PERSON,
                kind="person",
                birth_years=[person_year],
                programs=["TEST-PROGRAM"],
            )
        ],
    )
    _save("uk", [ListEntry(source="uk", uid="22", name=org_name, kind="organization", programs=["UK-TEST"])])
    _save("eu", [ListEntry(source="eu", uid="33", name="Someone Else Entirely", kind="person")])


def _config(**screening: Any) -> DealConfig:
    return DealConfig.model_validate(
        {
            "config_version": "1.0.0",
            "buyer": {"name": "Buyer Placeholder"},
            "target": {
                "name": COMPANY,
                "subsidiaries": ["Imaginary Subsidiary Ltd"],
                "previous_names": [{"name": "Old Fabricated Name Inc", "period": "2015-2020"}],
            },
            "key_executives": [{"name": PERSON, "title": "Chief Placeholder", "company": COMPANY}],
            "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
            "screening": {"enabled": True, **screening},
        }
    )


def _read(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _run(tmp_path: Path, config: DealConfig, subjects: list[tuple[str, str]] | None = None) -> Path:
    run_dir = tmp_path / "run"
    run_screening(
        config=config,
        subjects=subjects if subjects is not None else [(SUBJECT, "imaginary_ventures_group")],
        project_dir=tmp_path,
        run_dir=run_dir,
        run_id="run_test",
        now=NOW,
    )
    return run_dir


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestScreeningConfig:
    def test_defaults_are_off(self) -> None:
        cfg = ScreeningConfig()
        assert cfg.enabled is False
        assert cfg.people is True
        assert cfg.companies is True
        assert cfg.sources is None

    def test_deal_config_default_is_off(self, minimal_config_dict: dict[str, Any]) -> None:
        assert DealConfig.model_validate(minimal_config_dict).screening.enabled is False

    def test_unknown_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="unknown screening source"):
            ScreeningConfig(sources=["ofac_sdn", "made_up_list"])

    def test_duplicate_source_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            ScreeningConfig(sources=["uk", "uk"])

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScreeningConfig.model_validate({"enabled": True, "pep": True})

    def test_known_sources_accepted(self) -> None:
        assert ScreeningConfig(sources=["ofac_sdn", "eu"]).sources == ["ofac_sdn", "eu"]


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


class TestBuildTargets:
    def test_builds_every_kind_of_target(self) -> None:
        owned = build_targets(_config(), [(SUBJECT, "imaginary_ventures_group")])
        names = {o.target.name: o for o in owned}
        assert set(names) == {
            SUBJECT,
            COMPANY,
            "Imaginary Subsidiary Ltd",
            "Old Fabricated Name Inc",
            PERSON,
        }
        assert names[PERSON].target.kind == "person"
        assert names[COMPANY].target.kind == "organization"
        assert names[SUBJECT].stem == "imaginary_ventures_group"
        assert names[COMPANY].stem == TARGET_STEM
        assert names[PERSON].stem == TARGET_STEM

    def test_name_variants_are_screened_as_target_names(self) -> None:
        """A rebrand often lives only in the variants list (found in a live run)."""
        cfg = _config()
        cfg.target.entity_name_variants_for_contract_matching = ["New Brand Placeholder", COMPANY]
        owned = {o.target.name: o for o in build_targets(cfg, [])}
        assert owned["New Brand Placeholder"].roles == ["name variant of the target"]
        assert owned["New Brand Placeholder"].stem == TARGET_STEM
        assert COMPANY in owned  # the duplicate merged, no second entry
        assert sum(1 for o in owned.values() if o.target.name == COMPANY) == 1

    def test_duplicates_are_merged_by_normalized_name(self) -> None:
        subjects = [
            (COMPANY, "fabricated_holdings"),
            ("FABRICATED HOLDINGS, LTD.", "fabricated_holdings_2"),
        ]
        owned = build_targets(_config(), subjects)
        matching = [o for o in owned if o.target.name.lower().startswith("fabricated holdings")]
        assert len(matching) == 1
        # Subjects come first, so the name is reported under the subject.
        assert matching[0].stem == "fabricated_holdings"
        assert "target company" in matching[0].roles

    def test_people_flag_off(self) -> None:
        owned = build_targets(_config(people=False), [])
        assert all(o.target.kind == "organization" for o in owned)

    def test_companies_flag_off(self) -> None:
        owned = build_targets(_config(companies=False), [(SUBJECT, "imaginary_ventures_group")])
        assert [o.target.name for o in owned] == [PERSON]

    def test_blank_names_are_skipped(self) -> None:
        owned = build_targets(_config(), [("   ", "blank")])
        assert all(o.target.name.strip() for o in owned)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class TestFindings:
    def test_exact_hit_with_agreeing_detail_is_p0_medium(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        assert data["agent"] == SCREENING_AGENT
        assert data["subject_safe_name"] == TARGET_STEM
        by_title = {f["metadata"]["screening"]["screened_name"]: f for f in data["findings"]}
        person = by_title[PERSON]
        assert person["severity"] == "P0"
        assert person["category"] == CATEGORY
        # No birth year was given for the screened person, so nothing agrees: low.
        assert person["confidence"] == "low"
        company = by_title[COMPANY]
        assert company["severity"] == "P0"
        assert company["confidence"] == "low"

    def test_confidence_is_medium_only_when_detail_agrees(self, tmp_path: Path) -> None:
        _all_lists()
        config = _config()
        owned = build_targets(config, [])
        person = next(o for o in owned if o.target.name == PERSON)
        person.target.birth_year = 1970
        from dd_agents.screening.service import ScreeningService

        report = ScreeningService.load(tmp_path, now=NOW).screen([person.target])
        from dd_agents.screening.step import build_finding

        service = ScreeningService.load(tmp_path, now=NOW)
        finding = build_finding(person, report.results[0].hits, service, {}, "2026-11-14")
        assert finding["confidence"] == "medium"
        assert "birth year agrees" in finding["description"]

    def test_confidence_is_never_high(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        assert {f["confidence"] for f in data["findings"]} <= {"low", "medium"}

    def test_close_spelling_is_a_lower_severity(self, tmp_path: Path) -> None:
        _all_lists(org_name="Fabricated Holdingz Limited")
        run_dir = _run(tmp_path, _config(people=False))
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        finding = next(f for f in data["findings"] if f["metadata"]["screening"]["screened_name"] == COMPANY)
        assert finding["severity"] in {"P1", "P2"}
        assert finding["metadata"]["screening"]["hits"][0]["band"] in {"strong", "possible"}

    def test_text_says_possible_match_never_sanctioned(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        for finding in data["findings"]:
            text = f"{finding['title']} {finding['description']}".lower()
            assert "possible match" in text
            assert "needs review" in text
            assert "is sanctioned" not in text
            assert "is a sanctioned" not in text

    def test_citation_is_database_with_list_url(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        citation = data["findings"][0]["citations"][0]
        assert citation["source_type"] == "database"
        assert citation["source_path"]
        assert citation["exact_quote"] in {PERSON, COMPANY}
        assert "screened:" in citation["location"]

    def test_hit_on_a_data_room_entity_goes_to_its_own_file(self, tmp_path: Path) -> None:
        _save("uk", [ListEntry(source="uk", uid="9", name=SUBJECT, kind="organization")])
        _save("ofac_sdn", [])
        _save("eu", [])
        run_dir = _run(tmp_path, _config(people=False))
        folder = run_dir / "findings" / SCREENING_AGENT
        assert (folder / "imaginary_ventures_group.json").is_file()
        data = _read(folder / "imaginary_ventures_group.json")
        assert data["subject"] == SUBJECT

    def test_names_that_normalize_alike_make_one_finding(self, tmp_path: Path) -> None:
        _save("uk", [ListEntry(source="uk", uid="9", name=COMPANY, kind="organization")])
        _save("ofac_sdn", [])
        _save("eu", [])
        config = _config(people=False)
        config.target.subsidiaries = ["Fabricated Holdings Ltd."]
        run_dir = _run(tmp_path, config, subjects=[])
        data = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        # Both names normalize to the same text, so they are one target and one finding.
        assert len(data["findings"]) == 1

    def test_rerun_removes_stale_findings(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        stale = run_dir / "findings" / SCREENING_AGENT / "old_subject.json"
        stale.write_text("{}")
        _run(tmp_path, _config())
        assert not stale.exists()

    def test_user_list_hit(self, tmp_path: Path) -> None:
        _all_lists(org_name="Unrelated Registry Entry")
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "deal-watch.md").write_text(
            "---\nname: deal-watch\nkind: watchlist\nsource_url: https://example.invalid/note\nentries:\n"
            f"  - name: {SUBJECT}\n    type: organization\n    reason: Debarred by a customer\n---\nNotes.\n",
            encoding="utf-8",
        )
        run_dir = _run(tmp_path, _config(people=False))
        data = _read(run_dir / "findings" / SCREENING_AGENT / "imaginary_ventures_group.json")
        finding = data["findings"][0]
        assert finding["metadata"]["screening"]["hits"][0]["source"] == "user:deal-watch"
        assert finding["citations"][0]["source_path"] == "https://example.invalid/note"
        assert "user list" in finding["title"]


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_no_hit_still_writes_coverage_and_no_findings(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [])
        _save("uk", [])
        _save("eu", [])
        run_dir = _run(tmp_path, _config())
        assert not (run_dir / "findings" / SCREENING_AGENT).exists()
        cov = _read(run_dir / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert cov["complete"] is True
        assert cov["gaps"] == []
        assert cov["targets_with_hits"] == 0
        assert cov["targets_screened"]["person"] == 1
        assert cov["targets_screened"]["organization"] == 4
        assert cov["not_covered"] == list(NOT_COVERED)
        assert {row["source"] for row in cov["coverage"]} == {"ofac_sdn", "uk", "eu"}

    def test_missing_list_is_a_visible_gap(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [])
        run_dir = _run(tmp_path, _config())
        cov = _read(run_dir / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert cov["complete"] is False
        assert any(gap.startswith("uk: missing") for gap in cov["gaps"])
        assert cov["targets_with_hits"] == 0

    def test_stale_list_is_a_gap(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [], age_days=60)
        _save("uk", [])
        _save("eu", [])
        cov = _read(_run(tmp_path, _config()) / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert cov["complete"] is False
        assert any("ofac_sdn" in gap for gap in cov["gaps"])

    def test_broken_user_file_is_a_gap(self, tmp_path: Path) -> None:
        _all_lists()
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "bad.md").write_text("---\nname: bad\nkind: nonsense\n---\n", encoding="utf-8")
        cov = _read(_run(tmp_path, _config()) / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert cov["complete"] is False
        assert cov["user_errors"]
        assert cov["user_lists_hash"] != ""

    def test_sources_limit_the_lists_used(self, tmp_path: Path) -> None:
        _all_lists()
        cov = _read(_run(tmp_path, _config(sources=["uk"])) / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert {row["source"] for row in cov["coverage"]} == {"uk"}

    def test_info_log_has_counts_and_no_names(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        _all_lists()
        with caplog.at_level(logging.INFO, logger="dd_agents.screening.step"):
            _run(tmp_path, _config())
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "screened" in text
        for name in (PERSON, COMPANY, SUBJECT):
            assert name not in text


# ---------------------------------------------------------------------------
# Engine step and numbering
# ---------------------------------------------------------------------------


def _engine(tmp_path: Path, screening: dict[str, Any] | None) -> tuple[PipelineEngine, PipelineState]:
    raw: dict[str, Any] = {
        "config_version": "1.0.0",
        "buyer": {"name": "Buyer Placeholder"},
        "target": {"name": COMPANY},
        "deal": {"type": "acquisition", "focus_areas": ["change_of_control"]},
    }
    if screening is not None:
        raw["screening"] = screening
    config_path = tmp_path / "deal-config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    engine = PipelineEngine(tmp_path, config_path)
    state = PipelineState(project_dir=tmp_path.resolve())
    state.run_id = "run_test"
    state.run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_test"
    state.run_dir.mkdir(parents=True)
    state.deal_config = raw
    state.subject_safe_names = ["imaginary_ventures_group"]
    return engine, state


class TestEngineStep:
    async def test_skipped_when_disabled(self, tmp_path: Path) -> None:
        engine, state = _engine(tmp_path, None)
        await engine._step_26_external_screening(state)
        assert not (state.run_dir / SCREENING_RUN_DIR).exists()
        assert not (state.run_dir / "findings").exists()

    async def test_skipped_when_explicitly_off(self, tmp_path: Path) -> None:
        engine, state = _engine(tmp_path, {"enabled": False})
        await engine._step_26_external_screening(state)
        assert not (state.run_dir / SCREENING_RUN_DIR).exists()

    async def test_enabled_writes_findings_and_coverage(self, tmp_path: Path) -> None:
        _all_lists()
        engine, state = _engine(tmp_path, {"enabled": True, "people": False})
        await engine._step_26_external_screening(state)
        assert (state.run_dir / SCREENING_RUN_DIR / COVERAGE_FILE).is_file()
        assert (state.run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json").is_file()

    async def test_enabled_with_no_lists_writes_coverage_gap(self, tmp_path: Path) -> None:
        engine, state = _engine(tmp_path, {"enabled": True})
        await engine._step_26_external_screening(state)
        cov = _read(state.run_dir / SCREENING_RUN_DIR / COVERAGE_FILE)
        assert cov["complete"] is False
        assert cov["gaps"]


class TestStepNumbering:
    def test_screening_is_step_26_and_conditional(self) -> None:
        assert PipelineStep.EXTERNAL_SCREENING.step_number == 26
        assert PipelineStep.EXTERNAL_SCREENING in _CONDITIONAL_STEPS

    def test_screening_sits_between_judge_and_pre_merge(self) -> None:
        steps = list(PipelineStep)
        idx = steps.index(PipelineStep.EXTERNAL_SCREENING)
        assert steps[idx - 1].step_number == 25
        assert steps[idx + 1] is PipelineStep.PRE_MERGE_VALIDATION
        assert PipelineStep.PRE_MERGE_VALIDATION.step_number == 27

    def test_numbers_are_sequential_and_total_39(self) -> None:
        assert [s.step_number for s in PipelineStep] == list(range(1, 40))
        assert PipelineEngine.TOTAL_STEPS == 39

    def test_registry_has_a_method_for_every_step(self, tmp_path: Path) -> None:
        engine, _ = _engine(tmp_path, None)
        assert set(engine._step_registry) == set(PipelineStep)


class TestOldCheckpointRejected:
    def test_state_with_old_step_name_is_rejected(self) -> None:
        data = PipelineState(run_id="old").to_checkpoint_dict()
        data["current_step"] = "26_pre_merge_validation"
        with pytest.raises(BlockingGateError, match="older version"):
            PipelineState.from_checkpoint_dict(data)

    def test_old_completed_step_name_is_rejected(self) -> None:
        data = PipelineState(run_id="old").to_checkpoint_dict()
        data["completed_steps"] = ["01_validate_config", "30_numerical_audit"]
        with pytest.raises(BlockingGateError, match="30_numerical_audit"):
            PipelineState.from_checkpoint_dict(data)

    def test_same_number_other_name_file_is_rejected(self, tmp_path: Path) -> None:
        folder = tmp_path / "checkpoints"
        folder.mkdir()
        (folder / "checkpoint_26_pre_merge_validation.json").write_text("{}", encoding="utf-8")
        with pytest.raises(BlockingGateError, match="numbered the pipeline steps differently"):
            load_checkpoint_by_step(folder, 26)

    def test_current_checkpoint_still_loads(self, tmp_path: Path) -> None:
        state = PipelineState(run_id="new")
        state.current_step = PipelineStep.EXTERNAL_SCREENING
        save_checkpoint(state, tmp_path / "checkpoints")
        loaded = load_checkpoint_by_step(tmp_path / "checkpoints", 26)
        assert loaded.run_id == "new"

    def test_missing_checkpoint_is_still_file_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "checkpoints").mkdir()
        with pytest.raises(FileNotFoundError):
            load_checkpoint_by_step(tmp_path / "checkpoints", 26)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_off_adds_nothing(self) -> None:
        assert screening_persona_texts(None, "abc") == {}
        assert screening_persona_texts({"enabled": False}, "abc") == {}

    def test_config_change_changes_hash(self) -> None:
        def prov(cfg: dict[str, Any]) -> str:
            return compute_provenance_hash("cfg", "1", compute_persona_hashes(screening_persona_texts(cfg, "u")))

        assert prov({"enabled": True}) != prov({"enabled": True, "people": False})
        assert prov({"enabled": True}) != compute_provenance_hash("cfg", "1", {})

    def test_research_settings_change_hash(self) -> None:
        def prov(cfg: dict[str, Any]) -> str:
            return compute_provenance_hash("cfg", "1", compute_persona_hashes(screening_persona_texts(cfg, "u")))

        base = {"enabled": True}
        assert prov(base) != prov({**base, "profile_research": True})
        assert prov(base) != prov({**base, "discover_officers": True})
        assert prov({**base, "profile_research": True}) != prov(
            {**base, "profile_research": True, "research_max_targets": 5}
        )

    def test_user_list_change_changes_hash(self) -> None:
        cfg = {"enabled": True}
        a = compute_provenance_hash("cfg", "1", compute_persona_hashes(screening_persona_texts(cfg, "hash-a")))
        b = compute_provenance_hash("cfg", "1", compute_persona_hashes(screening_persona_texts(cfg, "hash-b")))
        assert a != b

    def test_engine_texts_follow_the_user_files(self, tmp_path: Path) -> None:
        engine, _ = _engine(tmp_path, {"enabled": True})
        raw = engine._read_deal_config_raw()
        before = engine._screening_persona_texts(raw)
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "w.md").write_text(
            f"---\nname: w\nkind: watchlist\nentries:\n  - name: {SUBJECT}\n---\n", encoding="utf-8"
        )
        after = engine._screening_persona_texts(raw)
        assert before["screening:user_lists"] != after["screening:user_lists"]
        assert after["screening:user_lists"] == load_user_screening(tmp_path).content_hash()

    def test_engine_texts_empty_when_off(self, tmp_path: Path) -> None:
        engine, _ = _engine(tmp_path, None)
        assert engine._screening_persona_texts(engine._read_deal_config_raw()) == {}

    async def test_resume_is_rejected_after_editing_screening_files(self, tmp_path: Path) -> None:
        from dd_agents.agents.prompt_builder import PromptBuilder
        from dd_agents.agents.registry import AgentRegistry
        from dd_agents.llm import resolve_provider
        from dd_agents.persistence.provenance import compute_config_hash

        engine, state = _engine(tmp_path, {"enabled": True})
        raw = engine._read_deal_config_raw()
        active = engine._active_agents or AgentRegistry.resolve_active()
        state.config_hash = compute_config_hash(raw)
        state.prompt_version = PromptBuilder.PROMPT_VERSION

        def current() -> str:
            texts = {
                **AgentRegistry.collect_persona_texts(active, project_dir=engine.project_dir),
                **engine._screening_persona_texts(engine._read_deal_config_raw()),
            }
            return compute_provenance_hash(
                state.config_hash,
                PromptBuilder.PROMPT_VERSION,
                compute_persona_hashes(texts),
                resolve_provider().fingerprint(),
            )

        state.provenance_hash = current()
        state.current_step = PipelineStep.JUDGE_ROUND2
        save_checkpoint(state, engine.checkpoint_dir)
        assert current() == state.provenance_hash  # control: nothing edited yet

        # An edited user list must stop the resume before any step runs.
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "w.md").write_text(
            f"---\nname: w\nkind: watchlist\nentries:\n  - name: {SUBJECT}\n---\n", encoding="utf-8"
        )
        assert current() != state.provenance_hash
        with pytest.raises(BlockingGateError, match="provenance"):
            await engine.run(resume_from_step=26)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


class TestMerge:
    def test_merge_picks_up_screening_folder_and_keeps_stem(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        merger = FindingMerger(run_id="run_test", timestamp="2026-11-14T00:00:00Z")
        merged = merger.merge_all(
            run_dir / "findings", expected_subjects=["imaginary_ventures_group"], active_agents=[]
        )
        assert TARGET_STEM in merged
        findings = merged[TARGET_STEM].findings
        assert findings
        for finding in findings:
            assert str(finding.agent) == SCREENING_AGENT
            assert finding.metadata["provenance"]["severity_source"]
            assert finding.citations
            assert finding.citations[0].source_type == "database"

    def test_merge_severity_goes_through_the_resolver(self, tmp_path: Path) -> None:
        _all_lists()
        run_dir = _run(tmp_path, _config())
        merger = FindingMerger(run_id="run_test", timestamp="2026-11-14T00:00:00Z")
        merged = merger.merge_all(run_dir / "findings", expected_subjects=[], active_agents=[])
        written = _read(run_dir / "findings" / SCREENING_AGENT / f"{TARGET_STEM}.json")
        by_title = {f["title"]: f["severity"] for f in written["findings"]}
        for finding in merged[TARGET_STEM].findings:
            assert str(finding.severity) == by_title[finding.title]

    def test_two_screened_names_on_one_entry_both_survive_merge(self, tmp_path: Path) -> None:
        _save("uk", [ListEntry(source="uk", uid="9", name=COMPANY, kind="organization")])
        _save("ofac_sdn", [])
        _save("eu", [])
        config = _config(people=False)
        config.target.subsidiaries = ["Fabricated Holdingz Limited"]
        run_dir = _run(tmp_path, config, subjects=[])
        merger = FindingMerger(run_id="run_test", timestamp="2026-11-14T00:00:00Z")
        merged = merger.merge_all(run_dir / "findings", expected_subjects=[], active_agents=[])
        assert len(merged[TARGET_STEM].findings) == 2


# ---------------------------------------------------------------------------
# The worked examples in docs/user-guide/screening.md must load
# ---------------------------------------------------------------------------


class TestDocExamples:
    @staticmethod
    def _blocks(lang: str) -> list[str]:
        import re
        from pathlib import Path as _Path

        text = (_Path(__file__).parents[2] / "docs" / "user-guide" / "screening.md").read_text(encoding="utf-8")
        return re.findall(rf"```{lang}\n(.*?)```", text, flags=re.DOTALL)

    def test_csv_watchlist_example_loads(self, tmp_path: Path) -> None:
        md = next(b for b in self._blocks("markdown") if "entries_file" in b)
        csv_text = self._blocks("csv")[0]
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "deal-watchlist.md").write_text(md, encoding="utf-8")
        (folder / "deal-watchlist.csv").write_text(csv_text, encoding="utf-8")
        cfg = load_user_screening(tmp_path)
        assert cfg.errors == []
        entries = cfg.entries()
        assert [e.name for e in entries] == [PERSON, COMPANY]
        assert entries[0].aliases == ["Z. Quintero", "Zelda Q. Fakename"]
        assert entries[0].birth_years == [1971, 1972]
        assert entries[1].countries == ["XX", "YY"]

    def test_inline_watchlist_example_loads(self, tmp_path: Path) -> None:
        md = next(b for b in self._blocks("markdown") if "inline-list" in b)
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "inline-list.md").write_text(md, encoding="utf-8")
        cfg = load_user_screening(tmp_path)
        assert cfg.errors == []
        assert [e.name for e in cfg.entries()] == [COMPANY]

    def test_deal_config_example_validates(self) -> None:
        block = next(b for b in self._blocks("json") if '"screening"' in b)
        assert json.loads("{" + block + "}")["screening"]["enabled"] is True
        ScreeningConfig.model_validate(json.loads("{" + block + "}")["screening"])
