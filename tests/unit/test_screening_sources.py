"""List adapters parse synthetic fixtures that mirror the real file structure (Issue #274).

Fixtures live in ``tests/fixtures/screening/``. All names in them are invented.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from dd_agents.screening.sources import SOURCES, Source, SourceParseError, csl, eu, ofac, uk
from dd_agents.screening.sources.base import birth_years, iso_date, iso_date_prefix, short_remarks

if TYPE_CHECKING:
    from dd_agents.screening.models import ListEntry

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "screening"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _by_uid(entries: list[ListEntry]) -> dict[str, ListEntry]:
    return {e.uid: e for e in entries}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registry_ids(self) -> None:
        assert set(SOURCES) == {"ofac_sdn", "us_csl", "uk", "eu"}

    @pytest.mark.parametrize("source", list(SOURCES.values()), ids=list(SOURCES))
    def test_source_shape(self, source: Source) -> None:
        assert source.url.startswith("https://")
        assert source.label
        assert callable(source.parse)
        assert source.source_id in SOURCES

    def test_module_constants_match_registry(self) -> None:
        for module in (ofac, csl, uk, eu):
            assert SOURCES[module.SOURCE_ID].url == module.URL


# ---------------------------------------------------------------------------
# OFAC
# ---------------------------------------------------------------------------


class TestOfac:
    def test_published_date_and_count(self) -> None:
        entries, published = ofac.parse(_load("ofac_sdn_sample.xml"))
        assert published == "2026-11-13"
        assert len(entries) == 5
        assert all(e.source == "ofac_sdn" for e in entries)

    def test_person_with_aliases_and_mixed_precision_birth_dates(self) -> None:
        person = _by_uid(ofac.parse(_load("ofac_sdn_sample.xml"))[0])["90001"]
        assert person.kind == "person"
        assert person.name == "Test Person ALPHA"
        assert person.aliases == ["Tester ALFA", "Тест Персона Альфа", "ONLYLAST"]
        # full date, month+year, circa, range expanded, unparseable ignored
        assert person.birth_years == [1948, 1949, 1952, 1955, 1956, 1957]
        assert person.countries == ["Examplestan", "Testland"]
        assert person.programs == ["TESTPROG1", "TESTPROG2"]
        assert person.url == "https://sanctionssearch.ofac.treas.gov/Details.aspx?id=90001"
        assert person.remarks == "Director of Example Holdings; Synthetic record for unit tests."
        assert person.listed_on == ""

    def test_organization_vessel_aircraft(self) -> None:
        by_uid = _by_uid(ofac.parse(_load("ofac_sdn_sample.xml"))[0])
        assert by_uid["90002"].kind == "organization"
        assert by_uid["90002"].aliases == ["EXAMPLE TRADING COMPANY LIMITED"]
        assert by_uid["90003"].kind == "vessel"
        assert by_uid["90004"].kind == "aircraft"
        assert by_uid["90004"].remarks == "(Linked To: EXAMPLE TRADING CO)"

    def test_missing_optional_fields(self) -> None:
        bare = _by_uid(ofac.parse(_load("ofac_sdn_sample.xml"))[0])["90005"]
        assert bare.aliases == []
        assert bare.birth_years == []
        assert bare.countries == []
        assert bare.programs == []
        assert bare.remarks == ""

    def test_missing_publish_date_gives_empty_string(self) -> None:
        raw = b"<sdnList><sdnEntry><uid>1</uid><lastName>X CO</lastName><sdnType>Entity</sdnType></sdnEntry></sdnList>"
        entries, published = ofac.parse(raw)
        assert published == ""
        assert entries[0].name == "X CO"

    @pytest.mark.parametrize(
        "raw",
        [
            b"",
            b"not xml at all",
            b"<sdnList><sdnEntry><uid>1</uid>",  # truncated
            b"<other/>",  # wrong root
            b"<sdnList></sdnList>",  # no entries
            b"<sdnList><sdnEntry><uid>1</uid><sdnType>Entity</sdnType></sdnEntry></sdnList>",  # no name
            b"<sdnList><sdnEntry><lastName>X</lastName></sdnEntry></sdnList>",  # no uid
        ],
        ids=["empty", "not-xml", "truncated", "wrong-root", "no-entries", "no-name", "no-uid"],
    )
    def test_malformed_input_raises(self, raw: bytes) -> None:
        with pytest.raises(SourceParseError):
            ofac.parse(raw)


# ---------------------------------------------------------------------------
# US Consolidated Screening List
# ---------------------------------------------------------------------------


class TestCsl:
    def test_sdn_records_left_out_and_date_from_kept_lists(self) -> None:
        entries, published = csl.parse(_load("csl_sample.json"))
        assert len(entries) == 4
        assert "tst-sdn-0001" not in _by_uid(entries)
        # the newest source_last_updated among the kept lists, not the SDN's
        assert published == "2026-10-02"
        assert all(e.source == "us_csl" for e in entries)

    def test_entity_list_record(self) -> None:
        entry = _by_uid(csl.parse(_load("csl_sample.json"))[0])["tst-el-0001"]
        assert entry.name == "Example Microelectronics Co., Ltd."
        assert entry.aliases == ["Example Micro"]
        assert entry.kind == "unknown"  # BIS lists do not say whether a party is a person
        assert entry.countries == ["TL", "EX"]
        assert entry.programs == ["Entity List (EL)"]
        assert entry.listed_on == "2024-05-09"
        assert entry.remarks == "99 FR 12345"
        assert entry.url.startswith("https://www.bis.gov/")

    def test_military_end_user_unverified_and_sectoral(self) -> None:
        by_uid = _by_uid(csl.parse(_load("csl_sample.json"))[0])
        assert by_uid["tst-meu-0001"].programs == ["Military End User (MEU) List"]
        assert by_uid["tst-meu-0001"].url == "https://www.bis.gov/regulations/ear/744#supplement-7-744"
        assert by_uid["tst-uvl-0001"].programs == ["Unverified List (UVL)"]
        assert by_uid["tst-uvl-0001"].countries == []
        ssi = by_uid["tst-ssi-0001"]
        assert ssi.kind == "organization"
        assert ssi.programs == ["Sectoral Sanctions Identifications List (SSI)", "TESTPROG-EO"]

    @pytest.mark.parametrize(
        "raw",
        [
            b"",
            b"not json",
            b"[]",
            b'{"results": []}',
            b'{"results": [{"source": "Entity List (EL) - Bureau of Industry and Security", "id": "1"}]}',
            b'{"results": [{"source": "Specially Designated Nationals (SDN) - Treasury Department", '
            b'"id": "1", "name": "X"}]}',
        ],
        ids=["empty", "not-json", "wrong-shape", "no-entries", "no-name", "sdn-only"],
    )
    def test_malformed_input_raises(self, raw: bytes) -> None:
        with pytest.raises(SourceParseError):
            csl.parse(raw)


# ---------------------------------------------------------------------------
# UK
# ---------------------------------------------------------------------------


class TestUk:
    def test_published_date_and_count(self) -> None:
        entries, published = uk.parse(_load("uk_sample.xml"))
        assert published == "2026-11-12"
        assert len(entries) == 4

    def test_person(self) -> None:
        person = _by_uid(uk.parse(_load("uk_sample.xml"))[0])["TST0001"]
        assert person.kind == "person"
        assert person.name == "Test Person Alpha"
        # alias, "Primary name variation" and the non-Latin script name
        assert person.aliases == ["Tester Alfa", "Test Alpha-Variant", "Тест Персона Альфа"]
        assert person.birth_years == [1945, 1950, 1951, 1960]
        assert person.countries == ["Testland", "Examplestan"]
        assert person.programs == ["The Testland (Sanctions) Regulations 2020"]
        assert person.listed_on == "2012-06-29"
        assert person.remarks == "Synthetic record for unit tests."

    def test_entity_name_type_case_is_ignored(self) -> None:
        entity = _by_uid(uk.parse(_load("uk_sample.xml"))[0])["TST0002"]
        assert entity.kind == "organization"
        assert entity.name == "EXAMPLE TRADING CO"
        assert entity.aliases == ["Example Trading Company"]

    def test_ship_is_vessel(self) -> None:
        ship = _by_uid(uk.parse(_load("uk_sample.xml"))[0])["TST0003"]
        assert ship.kind == "vessel"
        assert ship.aliases == ["Example_Star"]
        assert ship.listed_on == "2017-10-03"

    def test_missing_optional_fields(self) -> None:
        bare = _by_uid(uk.parse(_load("uk_sample.xml"))[0])["TST0004"]
        assert (bare.aliases, bare.birth_years, bare.countries, bare.programs) == ([], [], [], [])
        assert bare.listed_on == ""

    @pytest.mark.parametrize(
        "raw",
        [
            b"",
            b"<Designations><Designation>",
            b"<Wrong/>",
            b"<Designations></Designations>",
            b"<Designations><Designation><UniqueID>1</UniqueID><Names/></Designation></Designations>",
            b"<Designations><Designation><Names><Name><Name6>X</Name6><NameType>Primary Name</NameType></Name>"
            b"</Names></Designation></Designations>",
        ],
        ids=["empty", "truncated", "wrong-root", "no-entries", "no-primary-name", "no-uid"],
    )
    def test_malformed_input_raises(self, raw: bytes) -> None:
        with pytest.raises(SourceParseError):
            uk.parse(raw)


# ---------------------------------------------------------------------------
# EU
# ---------------------------------------------------------------------------


class TestEu:
    def test_published_date_and_count(self) -> None:
        entries, published = eu.parse(_load("eu_sample.xml"))
        assert published == "2026-10-23"
        assert len(entries) == 3

    def test_person(self) -> None:
        person = _by_uid(eu.parse(_load("eu_sample.xml"))[0])["EU.0.01"]
        assert person.kind == "person"
        assert person.name == "Test Person Alpha"
        # non-Latin alias kept as published; alias built from name parts when wholeName is empty
        assert person.aliases == ["Тест Персона Альфа", "Tester Alfa"]
        # birthdate attribute, year-only attribute, year range, empty birthdate ignored
        assert person.birth_years == [1937, 1940, 1953, 1954, 1955]
        assert person.countries == ["Examplestan", "Testland"]
        assert person.programs == ["TSTA", "TSTB"]
        assert person.listed_on == "2012-06-29"
        assert person.url == "https://eur-lex.example.test/new"
        assert person.remarks == "Synthetic record for unit tests."

    def test_primary_name_prefers_default_language(self) -> None:
        entity = _by_uid(eu.parse(_load("eu_sample.xml"))[0])["EU.0.02"]
        assert entity.kind == "organization"
        assert entity.name == "Example Trading Co"
        assert entity.aliases == ["Εταιρεία Παράδειγμα"]

    def test_missing_optional_fields(self) -> None:
        bare = _by_uid(eu.parse(_load("eu_sample.xml"))[0])["EU.0.03"]
        assert (bare.aliases, bare.birth_years, bare.countries, bare.programs) == ([], [], [], [])
        assert bare.url == ""
        assert bare.listed_on == ""

    @pytest.mark.parametrize(
        "raw",
        [
            b"",
            b"<export>",
            b"<other/>",
            b"<export></export>",
            b'<export><sanctionEntity logicalId="1"><nameAlias wholeName="" firstName="" lastName=""/>'
            b"</sanctionEntity></export>",
            b'<export><sanctionEntity><nameAlias wholeName="X"/></sanctionEntity></export>',
        ],
        ids=["empty", "truncated", "wrong-root", "no-entries", "no-name", "no-uid"],
    )
    def test_malformed_input_raises(self, raw: bytes) -> None:
        with pytest.raises(SourceParseError):
            eu.parse(raw)


# ---------------------------------------------------------------------------
# XML safety (shared by all adapters)
# ---------------------------------------------------------------------------


class TestXmlSafety:
    ENTITY_BOMB = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        b"<sdnList><sdnEntry><uid>1</uid><lastName>&b;</lastName><sdnType>Entity</sdnType></sdnEntry></sdnList>"
    )
    EXTERNAL_ENTITY = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]>'
        b"<sdnList><sdnEntry><uid>1</uid><lastName>&e;</lastName><sdnType>Entity</sdnType></sdnEntry></sdnList>"
    )

    @pytest.mark.parametrize("raw", [ENTITY_BOMB, EXTERNAL_ENTITY], ids=["entity-expansion", "external-entity"])
    def test_dtd_and_entities_are_rejected(self, raw: bytes) -> None:
        with pytest.raises(SourceParseError, match="Forbidden XML construct"):
            ofac.parse(raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            (["10 Dec 1948"], [1948]),
            (["Dec 1948"], [1948]),
            (["circa 1948"], [1948]),
            (["dd/mm/1948"], [1948]),
            (["1948"], [1948]),
            (["1948 to 1950"], [1948, 1949, 1950]),
            (["01 Jan 1950 to 31 Dec 1951"], [1950, 1951]),
            (["1950 to 1999"], [1950, 1999]),  # span too wide to expand
            (["unknown", "", "12345", "1066"], []),
            (["1948", "1948 "], [1948]),
        ],
    )
    def test_birth_years(self, values: list[str], expected: list[int]) -> None:
        assert birth_years(values) == expected

    def test_iso_date(self) -> None:
        assert iso_date("11/13/2026", "mdy") == "2026-11-13"
        assert iso_date("12/11/2026", "dmy") == "2026-11-12"
        assert iso_date("2026-11-12", "ymd") == "2026-11-12"
        assert iso_date("31/02/2026", "dmy") == ""
        assert iso_date("not a date", "dmy") == ""
        assert iso_date(None, "dmy") == ""

    def test_iso_date_prefix(self) -> None:
        assert iso_date_prefix("2026-10-23T17:05:43.888+02:00") == "2026-10-23"
        assert iso_date_prefix("") == ""
        assert iso_date_prefix("2026-13-40") == ""

    def test_short_remarks_truncates(self) -> None:
        text = short_remarks("a" * 500)
        assert len(text) == 300
        assert text.endswith("...")
        assert short_remarks("a", "", None, "b") == "a; b"
