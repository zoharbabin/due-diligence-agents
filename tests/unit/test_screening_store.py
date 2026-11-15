"""Local store for sanctions lists: download rules, atomic writes, coverage (Issue #274).

No test touches the network. ``store._download`` is patched, or a fake opener is passed in.
"""

from __future__ import annotations

import hashlib
import io
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dd_agents.screening import store
from dd_agents.screening.models import ListEntry, ListSnapshot
from dd_agents.screening.sources import SOURCES, SourceParseError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "screening"
NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def screening_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "screening"
    monkeypatch.setenv("DD_SCREENING_DIR", str(home))
    return home


def _snapshot(
    source: str = "uk", fetched_at: datetime = NOW, published: str = "2026-11-12", n: int = 2
) -> ListSnapshot:
    return ListSnapshot(
        source=source,
        source_url="https://example.test/list.xml",
        fetched_at=fetched_at.isoformat(timespec="seconds"),
        published=published,
        sha256="0" * 64,
        entries=[ListEntry(source=source, uid=str(i), name=f"Test Entry {i}") for i in range(n)],
    )


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}


class FakeOpener:
    """Stands in for ``OpenerDirector``. Records the request it was given."""

    def __init__(
        self, body: bytes = b"", headers: dict[str, str] | None = None, error: Exception | None = None
    ) -> None:
        self.body = body
        self.headers = headers
        self.error = error
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def open(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return FakeResponse(self.body, self.headers)


# ---------------------------------------------------------------------------
# Paths and snapshots
# ---------------------------------------------------------------------------


class TestPaths:
    def test_dir_from_env(self, screening_home: Path) -> None:
        assert store.screening_dir() == screening_home

    def test_default_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DD_SCREENING_DIR")
        assert store.screening_dir() == Path("~/.dd-agents/screening").expanduser()

    def test_blank_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DD_SCREENING_DIR", "   ")
        assert store.screening_dir() == Path("~/.dd-agents/screening").expanduser()

    def test_snapshot_path_layout(self, screening_home: Path) -> None:
        assert store.snapshot_path("ofac_sdn") == screening_home / "lists" / "ofac_sdn.json"

    @pytest.mark.parametrize("bad", ["", "../x", "a/b", "UK", "user:x", "a b", "é"])
    def test_invalid_source_id_rejected(self, bad: str) -> None:
        with pytest.raises(store.StoreError, match="Invalid source id"):
            store.snapshot_path(bad)


class TestSnapshotIo:
    def test_round_trip(self) -> None:
        snap = _snapshot()
        path = store.save_snapshot(snap)
        assert path == store.snapshot_path("uk")
        assert store.load_snapshot("uk") == snap

    def test_never_downloaded_is_none(self) -> None:
        assert store.load_snapshot("uk") is None

    def test_corrupt_file_raises(self, screening_home: Path) -> None:
        (screening_home / "lists").mkdir(parents=True)
        (screening_home / "lists" / "uk.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(store.StoreError, match="not valid"):
            store.load_snapshot("uk")

    def test_snapshot_for_another_source_raises(self) -> None:
        store.snapshot_path("uk").parent.mkdir(parents=True)
        store.snapshot_path("uk").write_text(_snapshot(source="eu").model_dump_json(), encoding="utf-8")
        with pytest.raises(store.StoreError, match="belongs to source"):
            store.load_snapshot("uk")

    def test_save_replaces_in_one_step_and_leaves_no_temp_files(self, screening_home: Path) -> None:
        store.save_snapshot(_snapshot(n=1))
        store.save_snapshot(_snapshot(n=3))
        loaded = store.load_snapshot("uk")
        assert loaded is not None
        assert len(loaded.entries) == 3
        assert sorted(p.name for p in (screening_home / "lists").iterdir()) == ["uk.json"]

    def test_failed_write_keeps_old_snapshot_and_cleans_up(
        self, screening_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store.save_snapshot(_snapshot(n=1))
        before = store.snapshot_path("uk").read_bytes()

        def boom(src: Any, dst: Any) -> None:
            raise OSError("disk full")

        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", boom)
            with pytest.raises(store.StoreError, match="Could not write"):
                store.save_snapshot(_snapshot(n=5))

        assert store.snapshot_path("uk").read_bytes() == before
        assert sorted(p.name for p in (screening_home / "lists").iterdir()) == ["uk.json"]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class TestDownload:
    @pytest.mark.parametrize(
        "url", ["http://example.test/a.xml", "file:///etc/passwd", "ftp://example.test/a", "//example.test/a", "a.xml"]
    )
    def test_non_https_rejected_before_any_request(self, url: str) -> None:
        opener = FakeOpener(b"data")
        with pytest.raises(store.StoreError, match="Only HTTPS"):
            store._download(url, opener=opener)  # type: ignore[arg-type]
        assert opener.requests == []

    def test_returns_body_and_sends_user_agent_and_timeout(self) -> None:
        opener = FakeOpener(b"<x/>")
        body = store._download("https://example.test/a.xml", opener=opener, timeout=7)  # type: ignore[arg-type]
        assert body == b"<x/>"
        assert opener.timeouts == [7]
        request = opener.requests[0]
        assert request.get_header("User-agent") == store.USER_AGENT
        assert "dd-agents" in store.USER_AGENT
        assert request.get_header("Accept-encoding") == "identity"

    def test_size_cap_on_declared_length(self) -> None:
        opener = FakeOpener(b"x", headers={"Content-Length": "5000"})
        with pytest.raises(store.StoreError, match="larger than"):
            store._download("https://example.test/a", opener=opener, max_bytes=1000)  # type: ignore[arg-type]

    def test_size_cap_on_streamed_body_without_length(self) -> None:
        opener = FakeOpener(b"x" * 3 * 1024 * 1024)
        with pytest.raises(store.StoreError, match="larger than"):
            store._download("https://example.test/a", opener=opener, max_bytes=2 * 1024 * 1024)  # type: ignore[arg-type]

    def test_body_exactly_at_cap_is_accepted(self) -> None:
        opener = FakeOpener(b"x" * 100)
        assert len(store._download("https://example.test/a", opener=opener, max_bytes=100)) == 100  # type: ignore[arg-type]

    def test_http_error_becomes_store_error(self) -> None:
        err = urllib.error.HTTPError("https://example.test/a", 403, "Forbidden", None, None)  # type: ignore[arg-type]
        with pytest.raises(store.StoreError, match="HTTP 403"):
            store._download("https://example.test/a", opener=FakeOpener(error=err))  # type: ignore[arg-type]

    def test_network_error_becomes_store_error(self) -> None:
        with pytest.raises(store.StoreError, match="Network error: boom"):
            store._download("https://example.test/a", opener=FakeOpener(error=urllib.error.URLError("boom")))  # type: ignore[arg-type]

    def test_timeout_becomes_store_error(self) -> None:
        with pytest.raises(store.StoreError, match="Network error"):
            store._download("https://example.test/a", opener=FakeOpener(error=TimeoutError("timed out")))  # type: ignore[arg-type]

    def test_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ticks = iter([0.0, 10.0, 20.0, 30.0])
        monkeypatch.setattr(store.time, "monotonic", lambda: next(ticks))
        opener = FakeOpener(b"x" * (3 * 1024 * 1024))
        with pytest.raises(store.StoreError, match="took longer"):
            store._download("https://example.test/a", opener=opener, deadline=5)  # type: ignore[arg-type]


class TestRedirects:
    def _redirect(self, newurl: str) -> urllib.request.Request | None:
        handler = store._HttpsOnlyRedirectHandler()
        request = urllib.request.Request("https://example.test/a")
        return handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, newurl)  # type: ignore[arg-type]

    def test_https_redirect_is_followed(self) -> None:
        followed = self._redirect("https://other.example.test/b")
        assert followed is not None
        assert followed.full_url == "https://other.example.test/b"

    @pytest.mark.parametrize("newurl", ["http://other.example.test/b", "file:///etc/passwd", "ftp://x/y"])
    def test_non_https_redirect_is_refused(self, newurl: str) -> None:
        with pytest.raises(urllib.error.HTTPError, match="non-HTTPS"):
            self._redirect(newurl)

    def test_tls_context_verifies_certificates_and_host_names(self) -> None:
        context = store._tls_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_tls_context_falls_back_to_system_store_without_certifi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "certifi", None)  # makes "import certifi" raise ImportError
        context = store._tls_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_real_opener_has_no_plain_http_or_file_handlers(self) -> None:
        opener = store._build_opener()
        names = {type(h).__name__ for h in opener.handlers}
        assert "HTTPSHandler" in names
        assert not names & {"HTTPHandler", "FileHandler", "FTPHandler", "DataHandler"}


# ---------------------------------------------------------------------------
# fetch and update
# ---------------------------------------------------------------------------

UK_RAW = (FIXTURES / "uk_sample.xml").read_bytes()


@pytest.fixture
def uk_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def fake(url: str, **_: Any) -> bytes:
        urls.append(url)
        return UK_RAW

    monkeypatch.setattr(store, "_download", fake)
    return urls


class TestFetch:
    def test_builds_snapshot_from_download(self, uk_download: list[str]) -> None:
        snap = store.fetch("uk", now=NOW)
        assert uk_download == [SOURCES["uk"].url]
        assert snap.source == "uk"
        assert snap.source_url == SOURCES["uk"].url
        assert snap.published == "2026-11-12"
        assert snap.fetched_at == "2026-11-14T12:00:00+00:00"
        assert snap.sha256 == hashlib.sha256(UK_RAW).hexdigest()
        assert len(snap.entries) == 4

    def test_fetch_writes_nothing(self, uk_download: list[str], screening_home: Path) -> None:
        store.fetch("uk", now=NOW)
        assert not screening_home.exists()

    def test_unknown_source(self) -> None:
        with pytest.raises(store.StoreError, match="Unknown source"):
            store.fetch("nope")

    def test_parse_failure_is_store_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "_download", lambda url, **_: b"<broken")
        with pytest.raises(store.StoreError, match="Could not parse the uk file"):
            store.fetch("uk")

    def test_registry_parse_error_is_wrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def bad(raw: bytes) -> Any:
            raise SourceParseError("odd")

        monkeypatch.setitem(SOURCES, "uk", SOURCES["uk"].__class__(**{**SOURCES["uk"].__dict__, "parse": bad}))
        monkeypatch.setattr(store, "_download", lambda url, **_: b"x")
        with pytest.raises(store.StoreError, match="odd"):
            store.fetch("uk")


class TestUpdate:
    def test_writes_snapshot(self, uk_download: list[str]) -> None:
        snap = store.update("uk", now=NOW)
        assert store.load_snapshot("uk") == snap

    def test_is_idempotent(self, uk_download: list[str], screening_home: Path) -> None:
        first = store.update("uk", now=NOW)
        second = store.update("uk", now=NOW)
        assert first == second
        assert sorted(p.name for p in (screening_home / "lists").iterdir()) == ["uk.json"]

    def test_download_failure_keeps_good_snapshot(
        self, uk_download: list[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store.update("uk", now=NOW)
        before = store.snapshot_path("uk").read_bytes()

        def down(url: str, **_: Any) -> bytes:
            raise store.StoreError("HTTP 503 from server (Unavailable)")

        monkeypatch.setattr(store, "_download", down)
        with pytest.raises(store.StoreError, match="503"):
            store.update("uk", now=NOW + timedelta(days=1))
        assert store.snapshot_path("uk").read_bytes() == before

    def test_parse_failure_keeps_good_snapshot(self, uk_download: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        store.update("uk", now=NOW)
        before = store.snapshot_path("uk").read_bytes()
        monkeypatch.setattr(store, "_download", lambda url, **_: b"<html>Service unavailable</html>")
        with pytest.raises(store.StoreError, match="Could not parse"):
            store.update("uk", now=NOW + timedelta(days=1))
        assert store.snapshot_path("uk").read_bytes() == before

    def test_write_failure_keeps_good_snapshot(self, uk_download: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        store.update("uk", now=NOW)
        before = store.snapshot_path("uk").read_bytes()

        def boom(*_: Any) -> None:
            raise OSError("disk full")

        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", boom)
            with pytest.raises(store.StoreError):
                store.update("uk", now=NOW + timedelta(days=1))
        assert store.snapshot_path("uk").read_bytes() == before

    def test_failure_note_then_success_clears_it(self, uk_download: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        good = store._download
        monkeypatch.setattr(store, "_download", lambda url, **_: (_ for _ in ()).throw(store.StoreError("HTTP 500")))
        with pytest.raises(store.StoreError):
            store.update("uk", now=NOW)
        assert store._load_failure("uk") is not None

        monkeypatch.setattr(store, "_download", good)
        store.update("uk", now=NOW)
        assert store._load_failure("uk") is None

    def test_unknown_source_writes_no_failure_note(self, screening_home: Path) -> None:
        with pytest.raises(store.StoreError, match="Unknown source"):
            store.update("nope")
        assert not screening_home.exists()


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_missing(self) -> None:
        [row] = store.coverage(["uk"], NOW)
        assert row.status == "missing"
        assert row.entry_count == 0
        assert "dd-agents screening update" in row.detail

    def test_screened_uses_published_date(self) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW - timedelta(days=1), published="2026-11-12"))
        [row] = store.coverage(["uk"], NOW)
        assert (row.status, row.list_date, row.entry_count) == ("screened", "2026-11-12", 2)

    def test_list_date_falls_back_to_download_date(self) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW - timedelta(days=1), published=""))
        [row] = store.coverage(["uk"], NOW)
        assert row.list_date == "2026-11-13"

    def test_age_limit_constant(self) -> None:
        assert store.LIST_MAX_AGE_DAYS == 7

    def test_staleness_boundary(self) -> None:
        limit = timedelta(days=store.LIST_MAX_AGE_DAYS)
        store.save_snapshot(_snapshot(fetched_at=NOW - limit))
        assert store.coverage(["uk"], NOW)[0].status == "screened"  # exactly at the limit
        assert store.coverage(["uk"], NOW + timedelta(seconds=1))[0].status == "stale"

    def test_custom_max_age(self) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW - timedelta(days=3)))
        assert store.coverage(["uk"], NOW, max_age_days=3)[0].status == "screened"
        assert store.coverage(["uk"], NOW, max_age_days=2)[0].status == "stale"

    def test_stale_row_keeps_counts_and_says_how_old(self) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW - timedelta(days=30)))
        [row] = store.coverage(["uk"], NOW)
        assert row.status == "stale"
        assert row.entry_count == 2
        assert "30 days ago" in row.detail

    def test_naive_now_is_treated_as_utc(self) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW))
        assert store.coverage(["uk"], NOW.replace(tzinfo=None))[0].status == "screened"

    def test_failed_when_no_snapshot_and_update_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "_download", lambda url, **_: (_ for _ in ()).throw(store.StoreError("HTTP 403")))
        with pytest.raises(store.StoreError):
            store.update("uk", now=NOW)
        [row] = store.coverage(["uk"], NOW)
        assert row.status == "failed"
        assert "HTTP 403" in row.detail

    def test_failed_when_stored_file_is_unreadable(self, screening_home: Path) -> None:
        (screening_home / "lists").mkdir(parents=True)
        (screening_home / "lists" / "uk.json").write_text("garbage", encoding="utf-8")
        [row] = store.coverage(["uk"], NOW)
        assert row.status == "failed"

    def test_good_snapshot_survives_later_failed_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store.save_snapshot(_snapshot(fetched_at=NOW - timedelta(days=1)))
        monkeypatch.setattr(store, "_download", lambda url, **_: (_ for _ in ()).throw(store.StoreError("HTTP 500")))
        with pytest.raises(store.StoreError):
            store.update("uk", now=NOW)
        [row] = store.coverage(["uk"], NOW)
        assert row.status == "screened"
        assert row.entry_count == 2
        assert "Last update failed" in row.detail

    def test_one_row_per_source_in_order(self) -> None:
        store.save_snapshot(_snapshot(source="eu"))
        rows = store.coverage(["uk", "eu", "ofac_sdn"], NOW)
        assert [(r.source, r.status) for r in rows] == [("uk", "missing"), ("eu", "screened"), ("ofac_sdn", "missing")]

    def test_coverage_is_read_only(self, screening_home: Path) -> None:
        store.coverage(["uk", "eu"], NOW)
        assert not screening_home.exists()
