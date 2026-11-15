"""Name matching against list entries (Issue #274). All names are invented."""

from __future__ import annotations

import time

import pytest

from dd_agents.screening.matcher import ScreeningIndex, normalize_name
from dd_agents.screening.models import ListEntry


def _entry(
    name: str,
    *,
    uid: str = "1",
    kind: str = "person",
    aliases: list[str] | None = None,
    years: list[int] | None = None,
    countries: list[str] | None = None,
    source: str = "test_list",
) -> ListEntry:
    return ListEntry.model_validate(
        {
            "source": source,
            "uid": uid,
            "name": name,
            "kind": kind,
            "aliases": aliases or [],
            "birth_years": years or [],
            "countries": countries or [],
        }
    )


class TestNormalize:
    def test_case_diacritics_punctuation(self) -> None:
        assert normalize_name("  GARCÍA-Test,  José ", "person") == "garcia test jose"

    def test_keeps_non_latin_script(self) -> None:
        assert normalize_name("Иван Тестов", "person") == "иван тестов"
        assert normalize_name("테스트 회사", "organization")

    def test_org_legal_suffix_removed(self) -> None:
        assert normalize_name("Example Trading Co., Ltd.", "organization") == normalize_name(
            "Example Trading", "organization"
        )

    def test_person_suffix_kept(self) -> None:
        assert "co" in normalize_name("Anna Co", "person").split()

    def test_empty(self) -> None:
        assert normalize_name("  ,. ", "person") == ""


class TestPersons:
    def test_exact_ignores_order_case_diacritics(self) -> None:
        index = ScreeningIndex([_entry("GARCIA TESTER, José")])
        hits = index.search("jose garcia tester", "person")
        assert [(h.band, h.score) for h in hits] == [("exact", 100.0)]

    def test_typo_is_strong(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov")])
        hits = index.search("Alexandr Testov", "person")
        assert len(hits) == 1
        assert hits[0].band == "strong"

    def test_shared_surname_only_is_not_a_hit(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov")])
        assert index.search("Maria Testov", "person") == []

    def test_subset_of_tokens_is_possible_not_strong(self) -> None:
        index = ScreeningIndex([_entry("Alexander Ivanovich Testov")])
        hits = index.search("Alexander Testov", "person")
        assert [h.band for h in hits] == ["possible"]

    def test_single_token_needs_exact(self) -> None:
        index = ScreeningIndex([_entry("Testov")])
        assert index.search("Testow", "person") == []
        assert [h.band for h in index.search("testov", "person")] == ["exact"]

    def test_alias_match_reports_alias(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov", aliases=["Sasha Tester"])])
        hits = index.search("Sasha Tester", "person")
        assert hits[0].matched_name == "Sasha Tester"
        assert hits[0].band == "exact"

    def test_non_latin_alias(self) -> None:
        index = ScreeningIndex([_entry("Ivan Testov", aliases=["Тестов Иван"])])
        assert [h.band for h in index.search("Иван Тестов", "person")] == ["exact"]

    def test_one_hit_per_entry_with_best_score(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov", aliases=["Alexandr Testov", "A Testov"])])
        hits = index.search("Alexander Testov", "person")
        assert len(hits) == 1
        assert hits[0].band == "exact"

    def test_empty_query(self) -> None:
        assert ScreeningIndex([_entry("Alexander Testov")]).search(" , ", "person") == []


class TestKindFilter:
    def test_person_query_skips_vessels_and_organizations(self) -> None:
        index = ScreeningIndex(
            [
                _entry("Test Star", kind="vessel", uid="v"),
                _entry("Test Star", kind="organization", uid="o"),
                _entry("Test Star", kind="person", uid="p"),
            ]
        )
        assert [h.entry.uid for h in index.search("Test Star", "person")] == ["p"]

    def test_org_query_skips_persons(self) -> None:
        index = ScreeningIndex(
            [_entry("Example Trading", kind="person", uid="p"), _entry("Example Trading", kind="organization", uid="o")]
        )
        assert [h.entry.uid for h in index.search("Example Trading", "organization")] == ["o"]

    def test_unknown_kind_matches_both(self) -> None:
        index = ScreeningIndex([_entry("Example Trading", kind="unknown")])
        assert len(index.search("Example Trading", "organization")) == 1
        assert len(index.search("Example Trading", "person")) == 1


class TestOrganizations:
    def test_legal_suffix_variants_are_exact(self) -> None:
        index = ScreeningIndex([_entry("Example Trading Company Limited", kind="organization")])
        hits = index.search("Example Trading Co., Ltd.", "organization")
        assert [h.band for h in hits] == ["exact"]

    def test_similar_name_is_strong_or_possible(self) -> None:
        index = ScreeningIndex([_entry("Example Trading Holdings", kind="organization")])
        hits = index.search("Example Tradng Holdings", "organization")
        assert hits
        assert hits[0].band in ("strong", "possible")

    def test_unrelated_not_matched(self) -> None:
        index = ScreeningIndex([_entry("Example Trading Holdings", kind="organization")])
        assert index.search("Northern Lights Bakery", "organization") == []


class TestCorroboration:
    def test_matching_birth_year_noted(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov", years=[1970])])
        hit = index.search("Alexander Testov", "person", birth_year=1970)[0]
        assert hit.band == "exact"
        assert "birth year agrees" in hit.corroboration

    def test_different_birth_year_lowers_band_one_step(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov", years=[1970])])
        hit = index.search("Alexander Testov", "person", birth_year=1985)[0]
        assert hit.band == "strong"
        assert "birth year differs" in hit.corroboration

    def test_possible_stays_possible_when_year_differs(self) -> None:
        index = ScreeningIndex([_entry("Alexander Ivanovich Testov", years=[1970])])
        hit = index.search("Alexander Testov", "person", birth_year=1985)[0]
        assert hit.band == "possible"

    def test_no_year_on_entry_no_note(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov")])
        hit = index.search("Alexander Testov", "person", birth_year=1970)[0]
        assert hit.corroboration == []

    def test_country_agreement_noted_without_changing_band(self) -> None:
        index = ScreeningIndex([_entry("Alexander Testov", countries=["Exampleland"])])
        hit = index.search("Alexander Testov", "person", country="exampleland")[0]
        assert hit.band == "exact"
        assert "country agrees" in hit.corroboration


class TestOrderingAndScale:
    def test_sorted_best_first_and_limited(self) -> None:
        index = ScreeningIndex(
            [
                _entry("Alexander Testov", uid="a"),
                _entry("Alexandr Testov", uid="b"),
                _entry("Alexandra Testova", uid="c"),
            ]
        )
        hits = index.search("Alexander Testov", "person", limit=2)
        assert len(hits) == 2
        assert hits[0].entry.uid == "a"
        assert hits[0].score >= hits[1].score

    def test_large_index_is_fast(self) -> None:
        entries = [_entry(f"Given{i} Family{i % 997}", uid=str(i)) for i in range(30000)]
        index = ScreeningIndex(entries)
        start = time.perf_counter()
        index.search("Given12345 Family123", "person")
        assert time.perf_counter() - start < 1.0

    @pytest.mark.parametrize("query", ["", "   ", "..."])
    def test_blank_queries(self, query: str) -> None:
        assert ScreeningIndex([_entry("Alexander Testov")]).search(query, "person") == []
