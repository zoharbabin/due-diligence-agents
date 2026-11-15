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


# -- Officer discovery and public source research (Issue #274 8b) ------------------


def _lead_finding(name: str = "Rowan Pellegrino Madeup") -> dict[str, Any]:
    return {
        "id": "F2",
        "agent": "external_screening",
        "severity": "P2",
        "title": f"Public source lead, needs review: {name}",
        "citations": [
            {
                "source_type": "web_research",
                "source_path": "https://example.invalid/case/1",
                "exact_quote": "Madeup, defendant",
                "access_date": "2026-11-14",
            }
        ],
        "metadata": {
            "profile_research": {
                "researched_name": name,
                "researched_kind": "person",
                "roles": ["officer named in the data room (Managing Director)"],
                "category": "litigation",
                "source_url": "https://example.invalid/case/1",
                "access_date": "2026-11-14",
            }
        },
    }


_RESEARCH_OK = {
    "ran": True,
    "complete": True,
    "names_sent": 4,
    "found": 1,
    "unavailable": 0,
    "invalid": 0,
    "not_researched": [],
    "detail": "",
}


def test_no_research_blocks_means_no_research_text(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage()))
    assert "Public source" not in html
    assert "Officers found" not in html
    assert "sent names" not in html


def test_leads_are_listed_with_source_and_date(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage(profile_research=_RESEARCH_OK)), [_lead_finding()])
    assert "Public Source Leads (Need Human Review)" in html
    assert "Rowan Pellegrino Madeup" in html
    assert "https://example.invalid/case/1" in html
    assert "2026-11-14" in html
    assert "litigation" in html
    # A lead is not a sanctions hit.
    assert "Possible Matches (Need Human Review)" not in html
    assert "No possible matches were found" in html


def test_research_statement_says_names_left_the_machine(tmp_path: Path) -> None:
    html = _render(_write(tmp_path, _coverage(profile_research=_RESEARCH_OK)))
    assert "sent names and roles, and no document text" in html
    assert "not clearance" in html.lower()


def test_incomplete_research_is_a_gap_with_names(tmp_path: Path) -> None:
    block = {**_RESEARCH_OK, "complete": False, "unavailable": 2, "not_researched": ["Name One Made", "Name Two Made"]}
    html = _render(_write(tmp_path, _coverage(profile_research=block)))
    assert "Public source research is incomplete" in html
    assert "Name One Made, Name Two Made" in html


def test_research_that_did_not_run_is_shown(tmp_path: Path) -> None:
    block = {"ran": False, "complete": False, "names_sent": 0, "detail": "external_verification.enabled is false"}
    html = _render(_write(tmp_path, _coverage(profile_research=block)))
    assert "Public source research did not run" in html
    assert "external_verification.enabled is false" in html
    assert "sent names and roles" not in html


def test_officer_discovery_counts_are_shown(tmp_path: Path) -> None:
    block = {"ran": True, "accepted": 3, "rejected": 1, "invalid": 1, "detail": ""}
    html = _render(_write(tmp_path, _coverage(officer_discovery=block)))
    assert "Officers found in the data room" in html
    assert "3 name(s)" in html
    assert "2 proposal(s) were dropped" in html


def test_failed_discovery_is_a_gap(tmp_path: Path) -> None:
    block = {"ran": False, "accepted": 0, "rejected": 0, "invalid": 0, "detail": "agent failed"}
    html = _render(_write(tmp_path, _coverage(officer_discovery=block)))
    assert "Officer discovery is incomplete" in html
    assert "agent failed" in html


def test_research_text_is_escaped(tmp_path: Path) -> None:
    evil = "<script>alert(1)</script>"
    finding = _lead_finding(evil)
    finding["metadata"]["profile_research"]["source_url"] = evil
    cov = _coverage(
        profile_research={**_RESEARCH_OK, "complete": False, "not_researched": [evil], "detail": evil},
        officer_discovery={"ran": False, "detail": evil},
    )
    html = _render(_write(tmp_path, cov), [finding])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
