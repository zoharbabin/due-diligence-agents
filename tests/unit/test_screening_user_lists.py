"""User watchlists and reference notes under dd-config/screening/ (Issue #274)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dd_agents.screening.user_lists import MAX_ENTRIES_PER_FILE, load_user_screening

if TYPE_CHECKING:
    from pathlib import Path


def _write(project: Path, name: str, text: str) -> Path:
    folder = project / "dd-config" / "screening"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


WATCHLIST = """---
name: seller-concerns
kind: watchlist
description: Parties the buyer flagged before signing
entries:
  - name: Example Holdings Ltd
    type: organization
    aliases: [Example Hldgs, Beispiel Holding]
    countries: [Exampleland]
    reason: Former parent, open dispute
  - name: Test Person Alpha
    type: person
    birth_years: [1971]
    programs: [internal]
---
Notes for the reviewer.
"""


class TestLoading:
    def test_no_folder_means_empty_config(self, tmp_path: Path) -> None:
        cfg = load_user_screening(tmp_path)
        assert cfg.lists == []
        assert cfg.errors == []
        assert cfg.entries() == []

    def test_watchlist_entries(self, tmp_path: Path) -> None:
        _write(tmp_path, "seller.md", WATCHLIST)
        cfg = load_user_screening(tmp_path)
        assert cfg.errors == []
        entries = cfg.entries()
        assert [e.name for e in entries] == ["Example Holdings Ltd", "Test Person Alpha"]
        assert entries[0].source == "user:seller-concerns"
        assert entries[0].kind == "organization"
        assert entries[0].aliases == ["Example Hldgs", "Beispiel Holding"]
        assert entries[0].remarks == "Former parent, open dispute"
        assert entries[1].birth_years == [1971]
        assert len({e.uid for e in entries}) == 2

    def test_csv_entries_file(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "big.md",
            "---\nname: big-list\nkind: watchlist\nentries_file: big.csv\n---\n",
        )
        _write(
            tmp_path,
            "big.csv",
            "name,type,aliases,birth_years,countries,programs,reason,url,listed_on\n"
            "Example Trading Co,organization,Ex Trading;Exemplar Trading,,Exampleland,,Seen in audit,,2026-01-02\n"
            "Test Person Beta,person,,1980;1981,,,,,\n",
        )
        entries = load_user_screening(tmp_path).entries()
        assert [e.name for e in entries] == ["Example Trading Co", "Test Person Beta"]
        assert entries[0].aliases == ["Ex Trading", "Exemplar Trading"]
        assert entries[0].listed_on == "2026-01-02"
        assert entries[1].birth_years == [1980, 1981]

    def test_reference_note_has_body_and_no_entries(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "defs.md",
            "---\nname: sector-rules\nkind: reference\n---\nTreat any party in the arms trade as high risk.\n",
        )
        cfg = load_user_screening(tmp_path)
        assert cfg.errors == []
        assert cfg.entries() == []
        assert [r.name for r in cfg.references()] == ["sector-rules"]
        assert "arms trade" in cfg.references()[0].body

    def test_default_kind_is_watchlist(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.md", "---\nname: a\nentries:\n  - name: Test Person Gamma\n---\n")
        assert len(load_user_screening(tmp_path).entries()) == 1


class TestErrors:
    def test_bad_file_is_reported_and_others_still_load(self, tmp_path: Path) -> None:
        _write(tmp_path, "good.md", WATCHLIST)
        _write(tmp_path, "bad.md", "---\nname: bad\nkind: nonsense\n---\n")
        cfg = load_user_screening(tmp_path)
        assert len(cfg.entries()) == 2
        assert len(cfg.errors) == 1
        assert "bad.md" in cfg.errors[0]

    @pytest.mark.parametrize(
        "text",
        [
            "---\nname: x\nunknown_key: 1\n---\n",
            "---\nname: x\nentries:\n  - type: person\n---\n",
            "---\nname: x\nentries:\n  - name: A B\n    type: alien\n---\n",
            "---\nname: x\nentries:\n  - name: A B\n    surprise: 1\n---\n",
            "---\nname: x\nentries:\n  - name: A B\n    birth_years: [abc]\n---\n",
            "---\nkind: watchlist\n---\n",
            "---\nname: has space\n---\n",
            "---\nname: x\n",
            "---\nname: x\nentries: not-a-list\n---\n",
        ],
    )
    def test_invalid_front_matter(self, tmp_path: Path, text: str) -> None:
        _write(tmp_path, "f.md", text)
        cfg = load_user_screening(tmp_path)
        assert cfg.entries() == []
        assert cfg.errors

    def test_duplicate_list_names(self, tmp_path: Path) -> None:
        _write(tmp_path, "a.md", WATCHLIST)
        _write(tmp_path, "b.md", WATCHLIST)
        cfg = load_user_screening(tmp_path)
        assert any("duplicate" in e.lower() for e in cfg.errors)

    def test_entries_file_cannot_leave_the_folder(self, tmp_path: Path) -> None:
        (tmp_path / "secret.csv").write_text("name\nOutside Person\n", encoding="utf-8")
        _write(tmp_path, "x.md", "---\nname: x\nentries_file: ../../secret.csv\n---\n")
        cfg = load_user_screening(tmp_path)
        assert cfg.entries() == []
        assert cfg.errors

    def test_missing_csv(self, tmp_path: Path) -> None:
        _write(tmp_path, "x.md", "---\nname: x\nentries_file: nope.csv\n---\n")
        assert load_user_screening(tmp_path).errors

    def test_csv_without_name_column(self, tmp_path: Path) -> None:
        _write(tmp_path, "x.md", "---\nname: x\nentries_file: x.csv\n---\n")
        _write(tmp_path, "x.csv", "title\nAlpha\n")
        assert load_user_screening(tmp_path).errors

    def test_entry_cap(self, tmp_path: Path) -> None:
        rows = "\n".join(f"Person {i}" for i in range(MAX_ENTRIES_PER_FILE + 1))
        _write(tmp_path, "x.md", "---\nname: x\nentries_file: x.csv\n---\n")
        _write(tmp_path, "x.csv", "name\n" + rows + "\n")
        cfg = load_user_screening(tmp_path)
        assert cfg.entries() == []
        assert any("entries" in e for e in cfg.errors)

    def test_non_screening_files_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path, "notes.txt", "hello")
        assert load_user_screening(tmp_path).errors == []


class TestHash:
    def test_stable_and_sensitive_to_content(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "a.md", WATCHLIST)
        first = load_user_screening(tmp_path).content_hash()
        assert first == load_user_screening(tmp_path).content_hash()
        path.write_text(WATCHLIST.replace("Alpha", "Alphb"), encoding="utf-8")
        assert load_user_screening(tmp_path).content_hash() != first

    def test_csv_change_changes_hash(self, tmp_path: Path) -> None:
        _write(tmp_path, "x.md", "---\nname: x\nentries_file: x.csv\n---\n")
        csv_path = _write(tmp_path, "x.csv", "name\nAlpha Beta\n")
        first = load_user_screening(tmp_path).content_hash()
        csv_path.write_text("name\nAlpha Betb\n", encoding="utf-8")
        assert load_user_screening(tmp_path).content_hash() != first

    def test_empty_config_hash_is_empty(self, tmp_path: Path) -> None:
        assert load_user_screening(tmp_path).content_hash() == ""
