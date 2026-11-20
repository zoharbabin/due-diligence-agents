"""Screening: list coverage, list update and a single-name check. No network: downloads are patched."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from dd_agents.screening import store
from dd_agents.screening.models import ListEntry, ListSnapshot
from dd_agents.screening.sources import SOURCES

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "screening"
RAW_BY_URL = {
    SOURCES["ofac_sdn"].url: (FIXTURES / "ofac_sdn_sample.xml").read_bytes(),
    SOURCES["us_csl"].url: (FIXTURES / "csl_sample.json").read_bytes(),
    SOURCES["uk"].url: (FIXTURES / "uk_sample.xml").read_bytes(),
    SOURCES["eu"].url: (FIXTURES / "eu_sample.xml").read_bytes(),
}


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "screening"
    monkeypatch.setenv("DD_SCREENING_DIR", str(home))
    return home


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def fake(url: str, **_: Any) -> bytes:
        urls.append(url)
        return RAW_BY_URL[url]

    monkeypatch.setattr(store, "_download", fake)
    return urls


def _project(client: TestClient, room: Path) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201


def _fill_lists(entries: list[ListEntry] | None = None) -> None:
    now = datetime.now(UTC).isoformat()
    for source in SOURCES:
        store.save_snapshot(
            ListSnapshot(
                source=source,
                source_url="https://example.invalid/x",
                fetched_at=now,
                published=now[:10],
                sha256="0" * 64,
                entries=entries if (entries and source == "ofac_sdn") else [],
            )
        )


class TestStatus:
    def test_fresh_machine_shows_every_list_missing(self, client: TestClient, screening_home: Path) -> None:
        body = client.get("/api/screening").json()
        assert [(r["source"], r["status"]) for r in body["sources"]] == [
            ("ofac_sdn", "missing"),
            ("us_csl", "missing"),
            ("uk", "missing"),
            ("eu", "missing"),
        ]
        assert body["max_age_days"] == store.LIST_MAX_AGE_DAYS
        assert not screening_home.exists()

    def test_does_not_expose_the_storage_path(self, client: TestClient, screening_home: Path) -> None:
        assert str(screening_home) not in client.get("/api/screening").text

    def test_needs_the_token(self, client: TestClient) -> None:
        assert client.get("/api/screening", headers={"Authorization": "Bearer wrong"}).status_code == 401


class TestUpdate:
    def test_updates_every_list_by_default(self, client: TestClient, downloads: list[str]) -> None:
        res = client.post("/api/screening/update", json={})
        assert res.status_code == 200
        results = res.json()["results"]
        assert [(r["source"], r["ok"]) for r in results] == [
            ("ofac_sdn", True),
            ("us_csl", True),
            ("uk", True),
            ("eu", True),
        ]
        assert {r["source"]: r["entries"] for r in results} == {"ofac_sdn": 5, "us_csl": 4, "uk": 4, "eu": 3}
        rows = client.get("/api/screening").json()["sources"]
        assert {r["status"] for r in rows} == {"screened"}

    def test_limits_the_download_to_the_chosen_lists(self, client: TestClient, downloads: list[str]) -> None:
        res = client.post("/api/screening/update", json={"sources": ["uk"]})
        assert res.status_code == 200
        assert downloads == [SOURCES["uk"].url]

    def test_unknown_list_is_refused_before_any_download(self, client: TestClient, downloads: list[str]) -> None:
        assert client.post("/api/screening/update", json={"sources": ["nope"]}).status_code == 422
        assert downloads == []

    def test_a_failed_list_is_reported_and_the_others_still_run(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake(url: str, **_: Any) -> bytes:
            if url == SOURCES["uk"].url:
                raise store.StoreError("HTTP 503 from server (Unavailable)")
            return RAW_BY_URL[url]

        monkeypatch.setattr(store, "_download", fake)
        results = {r["source"]: r for r in client.post("/api/screening/update", json={}).json()["results"]}
        assert results["uk"]["ok"] is False
        assert "503" in results["uk"]["error"]
        assert results["ofac_sdn"]["ok"] and results["eu"]["ok"]

    def test_second_update_while_one_runs_gets_409(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        started, release = threading.Event(), threading.Event()

        def slow(url: str, **_: Any) -> bytes:
            started.set()
            release.wait(5)
            return RAW_BY_URL[url]

        monkeypatch.setattr(store, "_download", slow)
        first: dict[str, int] = {}
        worker = threading.Thread(
            target=lambda: first.update(code=client.post("/api/screening/update", json={"sources": ["uk"]}).status_code)
        )
        worker.start()
        assert started.wait(5)
        try:
            assert client.post("/api/screening/update", json={"sources": ["uk"]}).status_code == 409
        finally:
            release.set()
            worker.join(5)
        assert first["code"] == 200


class TestCheck:
    def test_hit_names_the_list_and_the_report_is_not_complete_when_lists_are_missing(
        self, client: TestClient, data_room: Path
    ) -> None:
        _project(client, data_room)
        _fill_lists([ListEntry(source="ofac_sdn", uid="9", name="Zelda Quintero Fakename", kind="person")])
        res = client.post(
            "/api/projects/deal/screening/check", json={"name": "Zelda Quintero Fakename", "kind": "person"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["complete"] is True
        assert body["results"][0]["hits"][0]["entry"]["source"] == "ofac_sdn"

    def test_no_hit_with_missing_lists_is_incomplete(self, client: TestClient, data_room: Path) -> None:
        _project(client, data_room)
        body = client.post(
            "/api/projects/deal/screening/check", json={"name": "Jane Doe Testington", "kind": "person"}
        ).json()
        assert body["results"][0]["hits"] == []
        assert body["complete"] is False
        assert body["gaps"]

    def test_birth_year_and_country_are_passed_on(self, client: TestClient, data_room: Path) -> None:
        _project(client, data_room)
        _fill_lists([ListEntry(source="ofac_sdn", uid="9", name="Zelda Quintero Fakename", kind="person")])
        body = client.post(
            "/api/projects/deal/screening/check",
            json={"name": "Zelda Quintero Fakename", "kind": "person", "birth_year": 1970, "country": "Testland"},
        ).json()
        target = body["results"][0]["target"]
        assert (target["birth_year"], target["country"]) == (1970, "Testland")

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "", "kind": "person"},
            {"name": "   ", "kind": "person"},
            {"name": "x" * 301, "kind": "person"},
            {"name": "A", "kind": "robot"},
            {"name": "A", "kind": "person", "birth_year": 1},
            {"name": "A", "kind": "person", "extra": 1},
        ],
    )
    def test_bad_input_is_a_422(self, client: TestClient, data_room: Path, payload: dict[str, Any]) -> None:
        _project(client, data_room)
        assert client.post("/api/projects/deal/screening/check", json=payload).status_code == 422

    def test_unknown_project_is_404(self, client: TestClient) -> None:
        res = client.post("/api/projects/nope/screening/check", json={"name": "A", "kind": "person"})
        assert res.status_code == 404
