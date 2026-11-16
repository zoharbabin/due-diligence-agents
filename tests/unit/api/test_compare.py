"""Run-vs-run compare route. Numbers must match ``ReportDiffBuilder``, the engine behind ``dd-agents diff``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.reporting.diff import ReportDiffBuilder

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _finding(title: str, sev: str, source: str) -> dict[str, object]:
    return {
        "id": title,
        "severity": sev,
        "category": "termination",
        "title": title,
        "description": "",
        "citations": [{"source_path": source}],
        "agent": "legal",
    }


def _run(room: Path, run_id: str, subjects: dict[str, list[dict[str, object]]]) -> Path:
    run = room / "_dd" / "forensic-dd" / "runs" / run_id
    merged = run / "findings" / "merged"
    merged.mkdir(parents=True)
    for name, items in subjects.items():
        (merged / f"{name}.json").write_text(json.dumps({"subject": name, "findings": items}))
    return run


def _two_runs(room: Path) -> None:
    _run(room, "20260101_000000", {"acme": [_finding("Old", "P1", "a.pdf"), _finding("Same", "P2", "b.pdf")]})
    _run(
        room,
        "20260201_000000",
        {
            "acme": [_finding("New", "P0", "c.pdf"), _finding("Same", "P0", "b.pdf")],
            "zeta": [_finding("Z", "P3", "z.pdf")],
        },
    )


def _project(client: TestClient, room: Path) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201


def test_compare_matches_the_diff_engine(client: TestClient, data_room: Path) -> None:
    _two_runs(data_room)
    _project(client, data_room)
    runs = data_room / "_dd" / "forensic-dd" / "runs"
    expected = ReportDiffBuilder().build_diff(
        runs / "20260201_000000" / "findings",
        runs / "20260101_000000" / "findings",
        "20260201_000000",
        "20260101_000000",
    )
    got = client.get("/api/projects/deal/compare", params={"current": "20260201_000000", "prior": "20260101_000000"})
    assert got.status_code == 200, got.text
    assert got.json() == expected.model_dump()
    summary = got.json()["summary"]
    assert (
        summary["new_findings"],
        summary["resolved_findings"],
        summary["changed_severity"],
        summary["new_subjects"],
    ) == (1, 1, 1, 1)


def test_defaults_to_the_two_newest_runs(client: TestClient, data_room: Path) -> None:
    _two_runs(data_room)
    _project(client, data_room)
    body = client.get("/api/projects/deal/compare").json()
    assert (body["current_run_id"], body["prior_run_id"]) == ("20260201_000000", "20260101_000000")


def test_one_run_cannot_be_compared(client: TestClient, data_room: Path) -> None:
    _run(data_room, "20260101_000000", {"acme": []})
    _project(client, data_room)
    r = client.get("/api/projects/deal/compare")
    assert r.status_code == 404
    assert "two runs" in r.json()["detail"]


def test_unknown_run_is_404_and_bad_id_is_422(client: TestClient, data_room: Path) -> None:
    _two_runs(data_room)
    _project(client, data_room)
    assert (
        client.get("/api/projects/deal/compare", params={"current": "nope", "prior": "20260101_000000"}).status_code
        == 404
    )
    assert (
        client.get("/api/projects/deal/compare", params={"current": "../x", "prior": "20260101_000000"}).status_code
        == 422
    )


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/none/compare").status_code == 404
