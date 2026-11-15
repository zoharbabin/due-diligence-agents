"""``dd-agents screening update|status`` (Issue #274). No network: downloads are patched."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dd_agents.cli import main
from dd_agents.screening import store
from dd_agents.screening.models import ListEntry, ListSnapshot
from dd_agents.screening.sources import SOURCES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "screening"
RAW_BY_URL = {
    SOURCES["ofac_sdn"].url: (FIXTURES / "ofac_sdn_sample.xml").read_bytes(),
    SOURCES["uk"].url: (FIXTURES / "uk_sample.xml").read_bytes(),
    SOURCES["eu"].url: (FIXTURES / "eu_sample.xml").read_bytes(),
}
# The names inside the synthetic fixtures. The CLI must never print them.
FIXTURE_NAMES = ["Test Person", "Alpha", "ALPHA", "EXAMPLE TRADING", "Example Trading", "Example Star", "Bare Minimum"]


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "screening"
    monkeypatch.setenv("DD_SCREENING_DIR", str(home))
    return home


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve the fixtures instead of the network. Returns the URLs requested."""
    urls: list[str] = []

    def fake(url: str, **_: Any) -> bytes:
        urls.append(url)
        return RAW_BY_URL[url]

    monkeypatch.setattr(store, "_download", fake)
    return urls


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(main, ["screening", *args])


class TestUpdate:
    def test_updates_all_sources_by_default(self, downloads: list[str], screening_home: Path) -> None:
        result = _invoke("update", "--json")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [r["source"] for r in data["results"]] == ["ofac_sdn", "uk", "eu"]
        assert all(r["ok"] for r in data["results"])
        assert {r["source"]: r["entries"] for r in data["results"]} == {"ofac_sdn": 5, "uk": 4, "eu": 3}
        assert {r["source"]: r["published"] for r in data["results"]} == {
            "ofac_sdn": "2026-11-13",
            "uk": "2026-11-12",
            "eu": "2026-10-23",
        }
        assert data["screening_dir"] == str(screening_home)
        assert sorted(p.name for p in (screening_home / "lists").iterdir()) == ["eu.json", "ofac_sdn.json", "uk.json"]

    def test_source_option_limits_the_download(self, downloads: list[str]) -> None:
        result = _invoke("update", "--source", "uk", "--source", "eu", "--json")
        assert result.exit_code == 0, result.output
        assert downloads == [SOURCES["uk"].url, SOURCES["eu"].url]
        assert [r["source"] for r in json.loads(result.output)["results"]] == ["uk", "eu"]

    def test_unknown_source_is_a_usage_error(self, downloads: list[str]) -> None:
        result = _invoke("update", "--source", "nope")
        assert result.exit_code == 2
        assert downloads == []

    def test_is_idempotent(self, downloads: list[str], screening_home: Path) -> None:
        assert _invoke("update", "--source", "uk").exit_code == 0
        first = (screening_home / "lists" / "uk.json").read_bytes()
        assert _invoke("update", "--source", "uk").exit_code == 0
        assert [p.name for p in (screening_home / "lists").iterdir()] == ["uk.json"]
        loaded = json.loads((screening_home / "lists" / "uk.json").read_text(encoding="utf-8"))
        assert loaded["source"] == json.loads(first)["source"]
        assert len(loaded["entries"]) == 4

    def test_table_output_has_counts_and_dates_but_no_names(self, downloads: list[str]) -> None:
        result = _invoke("update")
        assert result.exit_code == 0, result.output
        for source_id in SOURCES:
            assert source_id in result.output
        assert "2026-11-13" in result.output
        for name in FIXTURE_NAMES:
            assert name not in result.output

    def test_failed_source_gives_nonzero_exit_and_keeps_good_data(
        self, downloads: list[str], monkeypatch: pytest.MonkeyPatch, screening_home: Path
    ) -> None:
        assert _invoke("update", "--source", "uk").exit_code == 0
        before = (screening_home / "lists" / "uk.json").read_bytes()

        def fake(url: str, **_: Any) -> bytes:
            if url == SOURCES["uk"].url:
                raise store.StoreError("HTTP 503 from server (Unavailable)")
            return RAW_BY_URL[url]

        monkeypatch.setattr(store, "_download", fake)
        result = _invoke("update", "--json")
        assert result.exit_code == 1
        by_source = {r["source"]: r for r in json.loads(result.output)["results"]}
        assert by_source["uk"]["ok"] is False
        assert "503" in by_source["uk"]["error"]
        assert by_source["ofac_sdn"]["ok"] and by_source["eu"]["ok"]  # others still ran
        assert (screening_home / "lists" / "uk.json").read_bytes() == before

    def test_failure_text_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def down(url: str, **_: Any) -> bytes:
            raise store.StoreError("Network error: [boom]")

        monkeypatch.setattr(store, "_download", down)
        result = _invoke("update", "--source", "eu")
        assert result.exit_code == 1
        assert "failed" in result.output
        assert "[boom]" in result.output  # rich markup in the message is not swallowed

    def test_unparseable_download_is_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "_download", lambda url, **_: b"<html>blocked</html>")
        result = _invoke("update", "--source", "ofac_sdn", "--json")
        assert result.exit_code == 1
        assert json.loads(result.output)["results"][0]["ok"] is False


class TestStatus:
    def test_all_missing_on_a_fresh_machine(self, screening_home: Path) -> None:
        result = _invoke("status", "--json")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [(r["source"], r["status"]) for r in data["sources"]] == [
            ("ofac_sdn", "missing"),
            ("uk", "missing"),
            ("eu", "missing"),
        ]
        assert data["max_age_days"] == store.LIST_MAX_AGE_DAYS
        assert not screening_home.exists()  # read-only: not even the directory is created

    def test_after_update(self, downloads: list[str]) -> None:
        assert _invoke("update").exit_code == 0
        result = _invoke("status", "--json")
        rows = {r["source"]: r for r in json.loads(result.output)["sources"]}
        assert {k: v["status"] for k, v in rows.items()} == {"ofac_sdn": "screened", "uk": "screened", "eu": "screened"}
        assert rows["ofac_sdn"]["entry_count"] == 5
        assert rows["uk"]["list_date"] == "2026-11-12"

    def test_stale_row(self, screening_home: Path) -> None:
        old = datetime.now(UTC) - timedelta(days=store.LIST_MAX_AGE_DAYS + 3)
        store.save_snapshot(
            ListSnapshot(
                source="uk",
                source_url=SOURCES["uk"].url,
                fetched_at=old.isoformat(timespec="seconds"),
                sha256="0" * 64,
                entries=[ListEntry(source="uk", uid="1", name="Test Entry")],
            )
        )
        result = _invoke("status", "--json")
        rows = {r["source"]: r for r in json.loads(result.output)["sources"]}
        assert rows["uk"]["status"] == "stale"
        assert rows["uk"]["entry_count"] == 1
        assert rows["eu"]["status"] == "missing"

    def test_table_output_never_prints_entry_names(self, downloads: list[str]) -> None:
        _invoke("update")
        result = _invoke("status")
        assert result.exit_code == 0, result.output
        assert "screened" in result.output
        for name in FIXTURE_NAMES:
            assert name not in result.output

    def test_status_writes_nothing_and_makes_no_requests(self, downloads: list[str], screening_home: Path) -> None:
        _invoke("update")
        before = {p.name: p.read_bytes() for p in (screening_home / "lists").iterdir()}
        downloads.clear()
        _invoke("status")
        _invoke("status", "--json")
        assert downloads == []
        assert {p.name: p.read_bytes() for p in (screening_home / "lists").iterdir()} == before

    def test_help_lists_both_commands(self) -> None:
        result = CliRunner().invoke(main, ["screening", "--help"])
        assert result.exit_code == 0
        assert "update" in result.output
        assert "status" in result.output


# ---------------------------------------------------------------------------
# check / validate (PR 6)
# ---------------------------------------------------------------------------


def _save_snapshot(source: str, entries: list[ListEntry]) -> None:
    now = datetime.now(UTC).isoformat()
    store.save_snapshot(
        ListSnapshot(
            source=source,
            source_url="https://example.invalid/x",
            fetched_at=now,
            published=now[:10],
            sha256="0" * 64,
            entries=entries,
        )
    )


def _fill_all_lists(extra: list[ListEntry] | None = None) -> None:
    _save_snapshot("ofac_sdn", extra or [])
    _save_snapshot("uk", [])
    _save_snapshot("eu", [])


class TestCheck:
    def test_hit_exits_1_and_names_the_list(self, tmp_path: Path) -> None:
        _fill_all_lists([ListEntry(source="ofac_sdn", uid="9", name="Zelda Quintero Fakename", kind="person")])
        result = _invoke(
            "check", "Zelda Quintero Fakename", "--type", "person", "--project-dir", str(tmp_path), "--json"
        )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["complete"] is True
        assert data["results"][0]["hits"][0]["entry"]["source"] == "ofac_sdn"

    def test_no_hit_full_coverage_exits_0_without_saying_clear(self, tmp_path: Path) -> None:
        _fill_all_lists()
        result = _invoke("check", "Jane Doe Testington", "--type", "person", "--project-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        assert "not a clearance" in result.output.lower()

    def test_no_hit_with_missing_lists_exits_2(self, tmp_path: Path) -> None:
        result = _invoke("check", "Jane Doe Testington", "--project-dir", str(tmp_path), "--json")
        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["complete"] is False
        assert len(data["gaps"]) == 3

    def test_type_is_required_choice(self, tmp_path: Path) -> None:
        result = _invoke("check", "X Y", "--type", "bogus", "--project-dir", str(tmp_path))
        assert result.exit_code == 2


class TestValidate:
    def test_ok(self, tmp_path: Path) -> None:
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "watch.md").write_text(
            "---\nname: watch\nkind: watchlist\nentries:\n  - name: Imaginary Ventures Group\n---\n"
        )
        result = _invoke("validate", "--project-dir", str(tmp_path), "--json")
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["errors"] == []
        assert data["lists"][0]["entries"] == 1

    def test_errors_exit_1(self, tmp_path: Path) -> None:
        folder = tmp_path / "dd-config" / "screening"
        folder.mkdir(parents=True)
        (folder / "bad.md").write_text("---\nname: bad\nkind: nonsense\n---\n")
        result = _invoke("validate", "--project-dir", str(tmp_path), "--json")
        assert result.exit_code == 1
        assert json.loads(result.output)["errors"][0].startswith("bad.md")

    def test_no_folder_is_ok(self, tmp_path: Path) -> None:
        result = _invoke("validate", "--project-dir", str(tmp_path))
        assert result.exit_code == 0
