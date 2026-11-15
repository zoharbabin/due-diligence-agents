"""Screening report section (Issue #274 phase 3). Synthetic names only."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html_screening import ScreeningRenderer

if TYPE_CHECKING:
    from pathlib import Path

HIT_NAME = "Zelda Quintero Fakename"


def _coverage(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "r",
        "complete": True,
        "coverage": [
            {"source": "ofac_sdn", "status": "screened", "list_date": "2026-11-10", "entry_count": 5, "detail": ""},
            {"source": "uk", "status": "screened", "list_date": "2026-11-11", "entry_count": 7, "detail": ""},
        ],
        "gaps": [],
        "user_errors": [],
        "targets_screened": {"person": 2, "organization": 6},
        "targets_with_hits": 0,
        "not_covered": ["SAM.gov exclusions, unless added as a user list"],
    }
    base.update(over)
    return base


def _hit_finding(screened: str = HIT_NAME, listed: str = HIT_NAME) -> dict[str, Any]:
    return {
        "id": "F1",
        "agent": "external_screening",
        "severity": "P0",
        "title": "Possible match, needs review",
        "metadata": {
            "screening": {
                "screened_name": screened,
                "hits": [
                    {
                        "list": "OFAC SDN (US Treasury)",
                        "listed_name": listed,
                        "matched_name": listed,
                        "band": "exact",
                        "score": 100.0,
                        "programs": ["TEST-PROGRAM"],
                        "corroboration": ["birth year agrees"],
                    }
                ],
            }
        },
    }


def _render(run_dir: Path | None, findings: list[dict[str, Any]] | None = None) -> str:
    merged: dict[str, Any] = {
        "_target_screening": {"subject": "Target company and executives", "findings": findings or [], "gaps": []},
        "subject_a": {"subject": "Subject A", "findings": [], "gaps": []},
    }
    computed = ReportDataComputer().compute(merged)
    return ScreeningRenderer(computed, merged, {}, run_dir=run_dir).render()


def _write(tmp_path: Path, coverage: dict[str, Any]) -> Path:
    folder = tmp_path / "screening"
    folder.mkdir()
    (folder / "coverage.json").write_text(json.dumps(coverage), encoding="utf-8")
    return tmp_path


def test_empty_when_screening_did_not_run(tmp_path: Path) -> None:
    assert _render(tmp_path) == ""
    assert _render(None) == ""


def test_empty_when_coverage_is_unreadable(tmp_path: Path) -> None:
    (tmp_path / "screening").mkdir()
    (tmp_path / "screening" / "coverage.json").write_text("not json", encoding="utf-8")
    assert _render(tmp_path) == ""


def test_clean_run_still_says_not_clearance(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage()))
    assert "Sanctions and Watchlist Screening" in html
    assert "No possible matches were found" in html
    assert "not clearance" in html.lower()
    assert "Screening is incomplete" not in html
    assert "Entities Screened" in html
    assert "SAM.gov exclusions" in html


def test_gaps_are_shown_as_incomplete(tmp_path: Path) -> None:
    cov = _coverage(
        complete=False,
        gaps=["uk: missing. Run dd-agents screening update"],
        coverage=[{"source": "uk", "status": "missing", "list_date": "", "entry_count": 0, "detail": "not downloaded"}],
    )
    html = _render(_write(tmp_path, cov))
    assert "Screening is incomplete" in html
    assert "uk: missing" in html
    assert "does not mean the name is clear" in html


def test_user_errors_are_shown_as_incomplete(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage(user_errors=["bad.md: broken front matter"])))
    assert "Screening is incomplete" in html
    assert "bad.md: broken front matter" in html


def test_hits_are_listed_with_human_review_wording(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage(targets_with_hits=1)), [_hit_finding()])
    assert "Possible Matches (Need Human Review)" in html
    assert HIT_NAME in html
    assert "TEST-PROGRAM" in html
    assert "birth year agrees" in html
    assert "is sanctioned" not in html


def test_report_uses_entity_not_subject(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage()))
    assert "Entities Screened" in html
    assert "subject" not in html.lower()


def test_only_screening_findings_are_listed(tmp_path: Path) -> None:
    other = _hit_finding(screened="Other Party Placeholder")
    other["agent"] = "legal"
    html = _render(_write(tmp_path, _coverage()), [other])
    assert "Other Party Placeholder" not in html
    assert "No possible matches were found" in html


def test_full_report_includes_section_only_when_screening_ran(tmp_path: Path) -> None:
    from dd_agents.reporting.html import HTMLReportGenerator

    merged: dict[str, Any] = {
        "_target_screening": {"subject": "Target", "findings": [_hit_finding()], "gaps": []},
        "subject_a": {"subject": "Subject A", "findings": [], "gaps": []},
    }
    (tmp_path / "ran").mkdir()
    run_dir = _write(tmp_path / "ran", _coverage())
    with_screening = tmp_path / "with.html"
    HTMLReportGenerator().generate(merged, with_screening, run_dir=run_dir)
    assert "Sanctions and Watchlist Screening" in with_screening.read_text(encoding="utf-8")

    (tmp_path / "off").mkdir()
    without = tmp_path / "without.html"
    HTMLReportGenerator().generate(merged, without, run_dir=tmp_path / "off")
    assert "Sanctions and Watchlist Screening" not in without.read_text(encoding="utf-8")


def test_names_and_list_text_are_escaped(tmp_path: Path) -> None:
    evil = "<script>alert(1)</script>"
    cov = _coverage(
        gaps=[f"{evil} gap"],
        user_errors=[f"{evil} error"],
        not_covered=[f"{evil} not covered"],
        coverage=[{"source": evil, "status": evil, "list_date": evil, "entry_count": 1, "detail": evil}],
    )
    finding = _hit_finding(screened=evil, listed=evil)
    finding["metadata"]["screening"]["hits"][0]["programs"] = [evil]
    finding["metadata"]["screening"]["hits"][0]["corroboration"] = [evil]
    html = _render(_write(tmp_path, cov), [finding])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
