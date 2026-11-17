"""Findings and report routes read the latest run's files."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient

RID = "20260101_000000"


def _finding(fid: str, sev: str, agent: str, title: str, subject: str) -> dict[str, object]:
    return {
        "id": fid,
        "severity": sev,
        "category": "termination",
        "title": title,
        "description": f"{title} details",
        "citations": [],
        "confidence": "high",
        "agent": agent,
        "analysis_unit": subject,
    }


def _seed(room: Path) -> Path:
    run = room / "_dd" / "forensic-dd" / "runs" / RID
    merged = run / "findings" / "merged"
    merged.mkdir(parents=True)
    for name, items in {
        "subject_a": [
            _finding("1", "P0", "legal", "Change of control", "Subject A"),
            _finding("2", "P3", "finance", "Minor", "Subject A"),
        ],
        "subject_b": [_finding("3", "P1", "legal", "Termination right", "Subject B")],
    }.items():
        (merged / f"{name}.json").write_text(
            json.dumps({"subject": name.replace("_", " ").title(), "subject_safe_name": name, "findings": items})
        )
    (merged / "_quarantine.json").write_text("[]")
    (run.parent / "latest").symlink_to(RID)
    (run / "report").mkdir()
    (run / "report" / "dd_report.html").write_text("<html>ok</html>")
    return run


def _project(client: TestClient, room: Path) -> None:
    assert client.post("/api/projects", json={"name": "Deal", "data_room": str(room)}).status_code == 201


def test_no_run_is_404(client: TestClient, data_room: Path) -> None:
    _project(client, data_room)
    assert client.get("/api/projects/deal/findings").status_code == 404


def test_findings_sorted_by_severity_with_facets(client: TestClient, data_room: Path) -> None:
    _seed(data_room)
    _project(client, data_room)
    body = client.get("/api/projects/deal/findings").json()
    assert body["total"] == 3
    assert [i["severity"] for i in body["items"]] == ["P0", "P1", "P3"]
    assert body["facets"]["severity"] == {"P0": 1, "P1": 1, "P3": 1}
    assert body["facets"]["agent"] == {"legal": 2, "finance": 1}
    assert body["items"][0]["subject"] == "Subject A"


def test_filters_and_paging(client: TestClient, data_room: Path) -> None:
    _seed(data_room)
    _project(client, data_room)
    assert client.get("/api/projects/deal/findings", params={"severity": "P1"}).json()["total"] == 1
    assert client.get("/api/projects/deal/findings", params={"agent": "legal"}).json()["total"] == 2
    assert client.get("/api/projects/deal/findings", params={"q": "control"}).json()["total"] == 1
    page = client.get("/api/projects/deal/findings", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3
    assert [i["id"] for i in page["items"]] == ["3"]


def test_bad_paging_is_422(client: TestClient, data_room: Path) -> None:
    _seed(data_room)
    _project(client, data_room)
    assert client.get("/api/projects/deal/findings", params={"limit": 0}).status_code == 422
    assert client.get("/api/projects/deal/findings", params={"limit": 100000}).status_code == 422
    assert client.get("/api/projects/deal/findings", params={"severity": "P9"}).status_code == 422


def test_run_id_must_be_a_run_directory(client: TestClient, data_room: Path) -> None:
    _seed(data_room)
    _project(client, data_room)
    assert client.get("/api/projects/deal/findings", params={"run_id": RID}).status_code == 200
    assert client.get("/api/projects/deal/findings", params={"run_id": "../../etc"}).status_code == 422
    assert client.get("/api/projects/deal/findings", params={"run_id": "missing"}).status_code == 404


def test_report_download(client: TestClient, data_room: Path) -> None:
    _seed(data_room)
    _project(client, data_room)
    r = client.get(f"/api/projects/deal/runs/{RID}/report/html")
    assert r.status_code == 200
    assert r.text == "<html>ok</html>"
    assert r.headers["content-type"].startswith("text/html")
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(f"/api/projects/deal/runs/{RID}/report/xlsx").status_code == 404
    assert client.get(f"/api/projects/deal/runs/{RID}/report/exe").status_code == 422


def test_report_link_escape_is_blocked(client: TestClient, data_room: Path, tmp_path: Path) -> None:
    run = _seed(data_room)
    secret = tmp_path / "secret.html"
    secret.write_text("secret")
    (run / "report" / "dd_report.html").unlink()
    (run / "report" / "dd_report.html").symlink_to(secret)
    _project(client, data_room)
    assert client.get(f"/api/projects/deal/runs/{RID}/report/html").status_code == 404


def test_run_summary_labels_risk_the_way_the_report_does(tmp_path: Path) -> None:
    """The app and the report must show one risk label. Eleven P2 findings are Medium in the report."""
    from dd_agents.api.findings_io import summarize_run

    merged = tmp_path / "findings" / "merged"
    merged.mkdir(parents=True)
    findings = [{"title": f"f{i}", "severity": "P2"} for i in range(11)]
    (merged / "subject_a.json").write_text(json.dumps({"subject": "Subject A", "findings": findings}))
    summary = summarize_run(tmp_path)
    assert summary.risk_label == "Medium"
