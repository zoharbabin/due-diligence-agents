"""Download, store and report on the official sanctions lists (Issue #274).

Layout under :func:`screening_dir` (env ``DD_SCREENING_DIR``, default
``~/.dd-agents/screening``)::

    lists/{source}.json          a ListSnapshot, written atomically
    lists/{source}.failure.json  last failed update, removed after the next success

Rules:

* A failed update never touches a good snapshot. It only writes the failure note.
* Downloads are HTTPS only, size capped and time limited. Nothing is extracted to disk.
* The raw download is parsed in memory and not kept. Only the parsed snapshot is stored.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import dd_agents
from dd_agents.screening.models import Coverage, ListSnapshot
from dd_agents.screening.sources import SOURCES, SourceParseError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from http.client import HTTPMessage

ENV_SCREENING_DIR = "DD_SCREENING_DIR"
DEFAULT_SCREENING_DIR = "~/.dd-agents/screening"

#: A list downloaded longer ago than this is reported as ``stale``.
LIST_MAX_AGE_DAYS = 7
#: Largest download accepted. The real files are about 20 to 30 MB.
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
#: Seconds to wait on one socket operation (connect or read).
FETCH_TIMEOUT_SECONDS = 60
#: Seconds allowed for one whole download.
FETCH_DEADLINE_SECONDS = 300
USER_AGENT = (
    f"dd-agents/{dd_agents.__version__} sanctions-list-updater (+https://github.com/zoharbabin/due-diligence-agents)"
)

_CHUNK_BYTES = 1024 * 1024
_FAILURE_NOTE_MAX_CHARS = 300


class StoreError(Exception):
    """Download, parse or storage problem. The message is safe to show to the user."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def screening_dir() -> Path:
    """Root of the local screening data (``DD_SCREENING_DIR`` or ``~/.dd-agents/screening``)."""
    configured = os.environ.get(ENV_SCREENING_DIR, "").strip()
    return Path(configured or DEFAULT_SCREENING_DIR).expanduser()


def _lists_dir() -> Path:
    return screening_dir() / "lists"


def _check_id(source_id: str) -> str:
    """Source ids become file names, so allow only ``[a-z0-9_]``."""
    if not source_id or not all(c.islower() or c.isdigit() or c == "_" for c in source_id) or not source_id.isascii():
        raise StoreError(f"Invalid source id: {source_id!r}")
    return source_id


def snapshot_path(source_id: str) -> Path:
    """Where the snapshot of ``source_id`` lives."""
    return _lists_dir() / f"{_check_id(source_id)}.json"


def _failure_path(source_id: str) -> Path:
    return _lists_dir() / f"{_check_id(source_id)}.failure.json"


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def save_snapshot(snapshot: ListSnapshot) -> Path:
    """Write ``snapshot`` atomically. The old file stays intact if the write fails."""
    path = snapshot_path(snapshot.source)
    try:
        _atomic_write(path, snapshot.model_dump_json())
    except OSError as exc:
        raise StoreError(f"Could not write {path}: {exc}") from exc
    return path


def load_snapshot(source_id: str) -> ListSnapshot | None:
    """Read a stored snapshot. ``None`` when the source was never downloaded.

    Raises:
        StoreError: the file exists but cannot be read or does not match the snapshot schema.
    """
    path = snapshot_path(source_id)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StoreError(f"Could not read {path}: {exc}") from exc
    try:
        snapshot = ListSnapshot.model_validate_json(text)
    except ValueError as exc:
        raise StoreError(f"Snapshot {path.name} is not valid: {exc}") from exc
    if snapshot.source != source_id:
        raise StoreError(f"Snapshot {path.name} belongs to source {snapshot.source!r}")
    return snapshot


def _record_failure(source_id: str, message: str, now: datetime) -> None:
    note = {"at": _iso(now), "error": message[:_FAILURE_NOTE_MAX_CHARS]}
    with suppress(OSError):
        _atomic_write(_failure_path(source_id), json.dumps(note))


def _clear_failure(source_id: str) -> None:
    with suppress(OSError):
        _failure_path(source_id).unlink(missing_ok=True)


def _load_failure(source_id: str) -> dict[str, str] | None:
    try:
        data: Any = json.loads(_failure_path(source_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("at"), str):
        return {"at": data["at"], "error": str(data.get("error", ""))}
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only when they stay on HTTPS."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(req.full_url, code, "Redirect to a non-HTTPS URL refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _tls_context() -> ssl.SSLContext:
    """Verified TLS context. Uses the ``certifi`` CA bundle when installed.

    Some Python builds (for example python.org and pyenv builds on macOS) miss root
    certificates that the list servers need. ``certifi`` ships with ``httpx``, which
    the Claude Agent SDK already pulls in. Without it, the system store is used.
    Certificate and host name checks are never turned off.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _build_opener() -> urllib.request.OpenerDirector:
    """An opener that speaks HTTPS only. No ``http:``, ``file:`` or ``ftp:`` handlers."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        _HttpsOnlyRedirectHandler(),
        urllib.request.HTTPSHandler(context=_tls_context()),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


def _download(
    url: str,
    *,
    opener: urllib.request.OpenerDirector | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    timeout: float = FETCH_TIMEOUT_SECONDS,
    deadline: float = FETCH_DEADLINE_SECONDS,
) -> bytes:
    """GET ``url`` over HTTPS and return the body.

    Raises:
        StoreError: not an HTTPS URL, network error, bad HTTP status, body larger
            than ``max_bytes``, or the download took longer than ``deadline`` seconds.
    """
    if urllib.parse.urlsplit(url).scheme != "https":
        raise StoreError("Only HTTPS downloads are allowed")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    started = time.monotonic()
    try:
        with (opener or _build_opener()).open(request, timeout=timeout) as response:
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise StoreError(f"Download is larger than the {max_bytes // (1024 * 1024)} MB limit")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk: bytes = response.read(_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise StoreError(f"Download is larger than the {max_bytes // (1024 * 1024)} MB limit")
                if time.monotonic() - started > deadline:
                    raise StoreError(f"Download took longer than {deadline:.0f} seconds")
                chunks.append(chunk)
    except StoreError:
        raise
    except urllib.error.HTTPError as exc:
        raise StoreError(f"HTTP {exc.code} from server ({exc.reason})") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise StoreError(f"Network error: {getattr(exc, 'reason', exc)}") from exc
    return b"".join(chunks)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def fetch(source_id: str, *, now: datetime | None = None) -> ListSnapshot:
    """Download and parse one list. Writes nothing.

    Raises:
        StoreError: unknown source, download problem, or the file does not parse.
    """
    source = SOURCES.get(source_id)
    if source is None:
        raise StoreError(f"Unknown source: {source_id!r}. Known sources: {', '.join(sorted(SOURCES))}")
    raw = _download(source.url)
    try:
        entries, published = source.parse(raw)
    except SourceParseError as exc:
        raise StoreError(f"Could not parse the {source_id} file: {exc}") from exc
    return ListSnapshot(
        source=source_id,
        source_url=source.url,
        fetched_at=_iso(now or datetime.now(UTC)),
        published=published,
        sha256=hashlib.sha256(raw).hexdigest(),
        entries=entries,
    )


def update(source_id: str, *, now: datetime | None = None) -> ListSnapshot:
    """Download, parse and store one list. Safe to repeat.

    On failure the stored snapshot is left as it was and a failure note is written.

    Raises:
        StoreError: any failure. The message is safe to show to the user.
    """
    moment = now or datetime.now(UTC)
    try:
        snapshot = fetch(source_id, now=moment)
        save_snapshot(snapshot)
    except StoreError as exc:
        if source_id in SOURCES:
            _record_failure(source_id, str(exc), moment)
        raise
    _clear_failure(source_id)
    return snapshot


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def _parse_time(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _coverage_one(source_id: str, now: datetime, max_age: timedelta) -> Coverage:
    try:
        snapshot = load_snapshot(source_id)
    except StoreError as exc:
        return Coverage(source=source_id, status="failed", detail=str(exc))
    failure = _load_failure(source_id)

    if snapshot is None:
        if failure:
            return Coverage(
                source=source_id, status="failed", detail=f"Update failed on {failure['at']}: {failure['error']}"
            )
        return Coverage(source=source_id, status="missing", detail="Not downloaded. Run: dd-agents screening update")

    fetched = _parse_time(snapshot.fetched_at)
    if fetched is None:
        return Coverage(source=source_id, status="failed", detail=f"Invalid fetched_at: {snapshot.fetched_at!r}")

    age = now - fetched
    stale = age > max_age
    detail = f"Downloaded {snapshot.fetched_at[:10]}"
    if stale:
        detail += f", {age.days} days ago (limit {max_age.days}). Run: dd-agents screening update"
    failed_since = failure is not None and (_parse_time(failure["at"]) or fetched) > fetched
    if failure is not None and failed_since:
        detail += f". Last update failed on {failure['at']}: {failure['error']}"
    return Coverage(
        source=source_id,
        status="stale" if stale else "screened",
        list_date=snapshot.published or snapshot.fetched_at[:10],
        entry_count=len(snapshot.entries),
        detail=detail,
    )


def coverage(
    sources: Iterable[str], now: datetime | None = None, max_age_days: int = LIST_MAX_AGE_DAYS
) -> list[Coverage]:
    """One :class:`Coverage` row per source id. Read-only.

    Status:

    * ``screened``: a snapshot exists and was downloaded within ``max_age_days``.
    * ``stale``: a snapshot exists but is older than ``max_age_days`` (exactly
      ``max_age_days`` old is still ``screened``).
    * ``missing``: never downloaded.
    * ``failed``: no usable snapshot and the last update failed, or the stored file is unreadable.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    max_age = timedelta(days=max_age_days)
    return [_coverage_one(source_id, moment, max_age) for source_id in sources]
