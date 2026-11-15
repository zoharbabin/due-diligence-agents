"""ScreeningService: store + user lists + matcher with an honest coverage table (Issue #274)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from dd_agents.screening import store
from dd_agents.screening.models import ListEntry, ListSnapshot
from dd_agents.screening.service import ScreeningService, ScreenTarget

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "screening"
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


def _person(source: str = "ofac_sdn") -> ListEntry:
    return ListEntry(source=source, uid="1", name="Zelda Quintero Fakename", kind="person", birth_years=[1970])


def _org(source: str = "uk") -> ListEntry:
    return ListEntry(source=source, uid="2", name="Fabricated Holdings Limited", kind="organization")


def _write_user_list(project: Path, name: str = "watch", body: str | None = None) -> None:
    folder = project / "dd-config" / "screening"
    folder.mkdir(parents=True)
    (folder / f"{name}.md").write_text(
        body
        or (
            f"---\nname: {name}\nkind: watchlist\nentries:\n"
            "  - name: Imaginary Ventures Group\n    type: organization\n    reason: Test only\n---\nNotes.\n"
        )
    )


def _all_sources_saved() -> None:
    _save("ofac_sdn", [_person()])
    _save("uk", [_org("uk")])
    _save("eu", [ListEntry(source="eu", uid="3", name="Someone Else Entirely", kind="person")])


class TestCoverage:
    def test_all_lists_fresh_is_complete(self, tmp_path: Path) -> None:
        _all_sources_saved()
        report = ScreeningService.load(tmp_path, now=NOW).screen([])
        assert report.complete is True
        assert report.gaps == []
        assert {c.source: c.status for c in report.coverage} == {
            "ofac_sdn": "screened",
            "uk": "screened",
            "eu": "screened",
        }

    def test_missing_list_is_a_gap_not_clearance(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [_person()])
        report = ScreeningService.load(tmp_path, now=NOW).screen([ScreenTarget(name="Nobody Atall", kind="person")])
        assert report.complete is False
        assert any(g.startswith("uk: missing") for g in report.gaps)
        assert report.results[0].hits == []

    def test_stale_list_is_used_but_flagged(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [_person()], age_days=30)
        _save("uk", [_org()])
        _save("eu", [])
        report = ScreeningService.load(tmp_path, now=NOW).screen(
            [ScreenTarget(name="Zelda Quintero Fakename", kind="person")]
        )
        assert report.complete is False
        assert any(g.startswith("ofac_sdn: stale") for g in report.gaps)
        assert len(report.results[0].hits) == 1  # still screened against the old list

    def test_source_subset(self, tmp_path: Path) -> None:
        _save("ofac_sdn", [_person()])
        report = ScreeningService.load(tmp_path, source_ids=["ofac_sdn"], now=NOW).screen([])
        assert [c.source for c in report.coverage] == ["ofac_sdn"]
        assert report.complete is True


class TestMatching:
    def test_person_hit_carries_source_and_band(self, tmp_path: Path) -> None:
        _all_sources_saved()
        report = ScreeningService.load(tmp_path, now=NOW).screen(
            [ScreenTarget(name="Zelda Quintero Fakename", kind="person", birth_year=1970)]
        )
        (hit,) = report.results[0].hits
        assert hit.band == "exact"
        assert hit.entry.source == "ofac_sdn"
        assert "birth year agrees" in hit.corroboration

    def test_organization_hit(self, tmp_path: Path) -> None:
        _all_sources_saved()
        report = ScreeningService.load(tmp_path, now=NOW).screen(
            [ScreenTarget(name="Fabricated Holdings Ltd", kind="organization")]
        )
        assert [h.entry.source for h in report.results[0].hits] == ["uk"]

    def test_no_hit_on_unrelated_name(self, tmp_path: Path) -> None:
        _all_sources_saved()
        report = ScreeningService.load(tmp_path, now=NOW).screen(
            [ScreenTarget(name="Jane Doe Testington", kind="person")]
        )
        assert report.results[0].hits == []
        assert report.complete is True

    def test_one_result_per_target_in_order(self, tmp_path: Path) -> None:
        _all_sources_saved()
        targets = [ScreenTarget(name="A One", kind="person"), ScreenTarget(name="B Two", kind="organization")]
        report = ScreeningService.load(tmp_path, now=NOW).screen(targets)
        assert [r.target.name for r in report.results] == ["A One", "B Two"]


class TestUserLists:
    def test_user_entries_are_screened_and_listed_in_coverage(self, tmp_path: Path) -> None:
        _all_sources_saved()
        _write_user_list(tmp_path)
        service = ScreeningService.load(tmp_path, now=NOW)
        report = service.screen([ScreenTarget(name="Imaginary Ventures Group", kind="organization")])
        assert [h.entry.source for h in report.results[0].hits] == ["user:watch"]
        row = next(c for c in report.coverage if c.source == "user:watch")
        assert (row.status, row.entry_count) == ("screened", 1)
        assert report.complete is True

    def test_broken_user_file_is_a_gap(self, tmp_path: Path) -> None:
        _all_sources_saved()
        _write_user_list(tmp_path, "bad", body="---\nname: bad\nkind: nonsense\n---\n")
        report = ScreeningService.load(tmp_path, now=NOW).screen([])
        assert report.complete is False
        assert report.user_errors and report.user_errors[0].startswith("bad.md")
        assert any(c.source == "user:bad.md" and c.status == "failed" for c in report.coverage)

    def test_reference_notes_are_returned_not_matched(self, tmp_path: Path) -> None:
        _all_sources_saved()
        _write_user_list(
            tmp_path,
            "defs",
            body="---\nname: defs\nkind: reference\ndescription: Deal terms\n---\nOur red-flag definitions.\n",
        )
        report = ScreeningService.load(tmp_path, now=NOW).screen([])
        (note,) = report.references
        assert (note.name, note.description) == ("defs", "Deal terms")
        assert "red-flag" in note.body
        assert not any(c.source == "user:defs" for c in report.coverage)

    def test_content_hash_changes_with_user_files(self, tmp_path: Path) -> None:
        assert ScreeningService.load(tmp_path, now=NOW).user_content_hash == ""
        _write_user_list(tmp_path)
        first = ScreeningService.load(tmp_path, now=NOW).user_content_hash
        assert first
        (tmp_path / "dd-config" / "screening" / "watch.md").write_text(
            "---\nname: watch\nkind: watchlist\nentries:\n  - name: Other Name Here\n---\n"
        )
        assert ScreeningService.load(tmp_path, now=NOW).user_content_hash != first


class TestNoProject:
    def test_project_dir_none_skips_user_lists(self) -> None:
        _all_sources_saved()
        report = ScreeningService.load(None, now=NOW).screen([])
        assert report.references == [] and report.user_errors == []
