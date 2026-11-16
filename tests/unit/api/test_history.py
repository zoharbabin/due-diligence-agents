"""History: the project's analysis chronicle, newest first."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.knowledge.chronicle import AnalysisChronicle, AnalysisLogEntry, FindingsSummary, InteractionType

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _project(client: TestClient, room: Path) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201


def _log(room: Path) -> AnalysisChronicle:
    return AnalysisChronicle(room / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl")


def _entry(n: int, kind: InteractionType = InteractionType.PIPELINE_RUN, **extra: object) -> AnalysisLogEntry:
    return AnalysisLogEntry(
        id=f"e{n}",
        timestamp=f"2026-01-0{n}T10:00:00+00:00",
        interaction_type=kind,
        title=f"Entry {n}",
        details={"private": "do not send"},
        **extra,  # type: ignore[arg-type]
    )


def test_empty_history(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    body = client.get("/api/projects/deal/history").json()
    assert body == {"entries": [], "total": 0, "by_type": {}}


def test_entries_are_newest_first_with_totals(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    log = _log(data_room)
    log.append(_entry(1, findings_summary=FindingsSummary(total=5, p0=1), cost_usd=1.5, duration_seconds=60.0))
    log.append(_entry(2, InteractionType.CHAT, entities_affected=["subject_a"], user_initiated=True))
    body = client.get("/api/projects/deal/history").json()
    assert [e["title"] for e in body["entries"]] == ["Entry 2", "Entry 1"]
    assert body["total"] == 2
    assert body["by_type"] == {"pipeline_run": 1, "chat": 1}
    first = body["entries"][1]
    assert first["findings_summary"]["p0"] == 1
    assert first["cost_usd"] == 1.5
    assert body["entries"][0]["entities_affected"] == ["subject_a"]


def test_details_are_not_sent(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    _log(data_room).append(_entry(1))
    entry = client.get("/api/projects/deal/history").json()["entries"][0]
    assert "details" not in entry
    assert "do not send" not in str(entry)


def test_filter_by_type_and_limit(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    log = _log(data_room)
    for n in (1, 2, 3):
        log.append(_entry(n, InteractionType.SEARCH))
    log.append(_entry(4, InteractionType.CHAT))
    body = client.get("/api/projects/deal/history?type=search&limit=2").json()
    assert [e["title"] for e in body["entries"]] == ["Entry 3", "Entry 2"]
    assert body["total"] == 3  # all searches, before the limit
    assert body["by_type"] == {"search": 3, "chat": 1}  # counts cover every entry


def test_bad_type_and_limit_are_422(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    assert client.get("/api/projects/deal/history?type=nope").status_code == 422
    assert client.get("/api/projects/deal/history?limit=0").status_code == 422
    assert client.get("/api/projects/deal/history?limit=501").status_code == 422


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/none/history").status_code == 404
