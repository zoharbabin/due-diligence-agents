"""Sanctions and watchlist screening section (Issue #274).

Reads ``screening/coverage.json`` (written by pipeline step 26) and the merged
findings from the ``external_screening`` agent. Renders nothing when the step
did not run, so deals without screening get no extra section.

Wording is fixed on purpose: hits are possible matches that need human review,
and the absence of a hit is not clearance.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.models.enums import AgentName
from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.utils.constants import SEVERITY_ORDER

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_COVERAGE_PATH = ("screening", "coverage.json")


class ScreeningRenderer(SectionRenderer):
    """Render what was screened, against which lists, and the possible matches."""

    def __init__(
        self,
        data: Any,
        merged_data: dict[str, Any],
        config: dict[str, Any] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(data, merged_data, config)
        self._run_dir = run_dir

    def render(self) -> str:
        coverage = self._load_coverage()
        if coverage is None:
            return ""
        parts: list[str] = [
            "<section class='report-section' id='sec-screening'>",
            "<h2>Sanctions and Watchlist Screening</h2>",
            self._render_status(coverage),
            self._render_counts(coverage),
            self._render_coverage_table(coverage),
            self._render_research_status(coverage),
            self._render_hits(),
            self._render_leads(),
            self._render_statement(coverage),
            "</section>",
        ]
        return "\n".join(p for p in parts if p)

    # -- data -------------------------------------------------------------

    def _load_coverage(self) -> dict[str, Any] | None:
        if self._run_dir is None:
            return None
        path = self._run_dir.joinpath(*_COVERAGE_PATH)
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read %s", path)
            return None
        return loaded if isinstance(loaded, dict) else None

    def _screening_findings(self) -> list[dict[str, Any]]:
        agent = AgentName.EXTERNAL_SCREENING.value
        found: list[dict[str, Any]] = []
        for data in self.merged_data.values():
            if not isinstance(data, dict):
                continue
            for finding in data.get("findings", []):
                if isinstance(finding, dict) and str(finding.get("agent", "")) == agent:
                    found.append(finding)
        found.sort(key=lambda f: SEVERITY_ORDER.get(str(f.get("severity", "P3")), 9))
        return found

    # -- parts ------------------------------------------------------------

    def _render_status(self, coverage: dict[str, Any]) -> str:
        gaps = [str(g) for g in coverage.get("gaps", [])]
        errors = [str(e) for e in coverage.get("user_errors", [])]
        problems = gaps + [e for e in errors if e not in gaps]
        if problems:
            body = (
                "Some lists were missing, out of date or unreadable. "
                "Having no possible match for such a list does not mean the name is clear. "
                "Problems: " + " | ".join(problems)
            )
            return self.render_alert("high", "Screening is incomplete", body)
        return self.render_alert(
            "info",
            "All lists were current when screened",
            "No possible match is not clearance. See the limits below.",
        )

    def _render_counts(self, coverage: dict[str, Any]) -> str:
        screened = coverage.get("targets_screened", {})
        orgs = int(screened.get("organization", 0)) if isinstance(screened, dict) else 0
        people = int(screened.get("person", 0)) if isinstance(screened, dict) else 0
        with_hits = int(coverage.get("targets_with_hits", 0))
        cards = [
            (orgs, "Entities Screened"),
            (people, "People Screened"),
            (with_hits, "With Possible Matches"),
        ]
        inner = "".join(
            f"<div class='metric-card'><div class='value'>{value}</div>"
            f"<div class='label'>{self.escape(label)}</div></div>"
            for value, label in cards
        )
        return f"<div class='metrics-strip'>{inner}</div>"

    def _render_coverage_table(self, coverage: dict[str, Any]) -> str:
        rows = coverage.get("coverage", [])
        if not isinstance(rows, list) or not rows:
            return "<p class='text-muted'>No list was available to screen against.</p>"
        parts = [
            "<table class='sortable'><caption>Lists screened against</caption><thead><tr>"
            "<th scope='col'>List</th><th scope='col'>Status</th><th scope='col'>List date</th>"
            "<th scope='col'>Entries</th><th scope='col'>Detail</th>"
            "</tr></thead><tbody>"
        ]
        for row in rows:
            if not isinstance(row, dict):
                continue
            parts.append(
                "<tr>"
                f"<td>{self.escape(str(row.get('source', '')))}</td>"
                f"<td>{self.escape(str(row.get('status', '')))}</td>"
                f"<td>{self.escape(str(row.get('list_date', '')))}</td>"
                f"<td>{self.escape(str(row.get('entry_count', 0)))}</td>"
                f"<td>{self.escape(str(row.get('detail', '')))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_hits(self) -> str:
        findings = [f for f in self._screening_findings() if _meta(f, "screening")]
        if not findings:
            return "<p>No possible matches were found in the lists that were screened.</p>"
        parts = [
            "<h3>Possible Matches (Need Human Review)</h3>",
            "<table class='sortable'><caption>Possible sanctions and watchlist matches</caption><thead><tr>"
            "<th scope='col'>Severity</th><th scope='col'>Screened name</th><th scope='col'>Listed name</th>"
            "<th scope='col'>Matched name</th><th scope='col'>List</th><th scope='col'>Band</th>"
            "<th scope='col'>Score</th><th scope='col'>Program</th><th scope='col'>Corroboration</th>"
            "</tr></thead><tbody>",
        ]
        for finding in findings:
            meta = finding.get("metadata", {})
            info = meta.get("screening", {}) if isinstance(meta, dict) else {}
            if not isinstance(info, dict):
                continue
            screened = self.escape(str(info.get("screened_name", "")))
            severity = self.severity_badge(str(finding.get("severity", "P3")))
            for hit in info.get("hits", []):
                if not isinstance(hit, dict):
                    continue
                programs = ", ".join(str(p) for p in hit.get("programs", [])) or "not stated"
                notes = "; ".join(str(n) for n in hit.get("corroboration", [])) or "none"
                parts.append(
                    "<tr>"
                    f"<td>{severity}</td><td>{screened}</td>"
                    f"<td>{self.escape(str(hit.get('listed_name', '')))}</td>"
                    f"<td>{self.escape(str(hit.get('matched_name', '')))}</td>"
                    f"<td>{self.escape(str(hit.get('list', '')))}</td>"
                    f"<td>{self.escape(str(hit.get('band', '')))}</td>"
                    f"<td>{self.escape(str(hit.get('score', '')))}</td>"
                    f"<td>{self.escape(programs)}</td>"
                    f"<td>{self.escape(notes)}</td>"
                    "</tr>"
                )
        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_research_status(self, coverage: dict[str, Any]) -> str:
        """Alerts for officer discovery and public source research. Empty when neither was requested."""
        parts: list[str] = []
        discovery = coverage.get("officer_discovery")
        if isinstance(discovery, dict):
            if discovery.get("ran"):
                body = (
                    f"{int(discovery.get('accepted', 0))} name(s) were found in data room documents with a quote "
                    f"that was checked against the document and added to screening. "
                    f"{int(discovery.get('rejected', 0)) + int(discovery.get('invalid', 0))} proposal(s) were dropped. "
                    "Officers named only in documents the agent did not open are not covered."
                )
                parts.append(self.render_alert("info", "Officers found in the data room", body))
            else:
                body = str(discovery.get("detail", "")) or "The agent did not finish."
                parts.append(self.render_alert("high", "Officer discovery is incomplete", body))
        research = coverage.get("profile_research")
        if isinstance(research, dict):
            parts.append(self._research_alert(research))
        return "\n".join(parts)

    def _research_alert(self, research: dict[str, Any]) -> str:
        if not research.get("ran"):
            detail = str(research.get("detail", "")) or "Research did not start."
            return self.render_alert(
                "high",
                "Public source research did not run",
                f"{detail} No public source was searched. This is not clearance.",
            )
        sent = int(research.get("names_sent", 0))
        found = int(research.get("found", 0))
        if research.get("complete"):
            body = (
                f"{sent} name(s) were searched in public sources and {found} lead(s) were found. "
                "Finding no lead is not clearance. Search tools miss records and match names loosely."
            )
            return self.render_alert("info", "Public source research", body)
        missed = [str(n) for n in research.get("not_researched", [])]
        body = (
            f"{sent} name(s) were sent. {found} lead(s) were found, "
            f"{int(research.get('unavailable', 0))} lookup(s) were unavailable and "
            f"{int(research.get('invalid', 0))} record(s) were invalid."
        )
        if missed:
            body += " Not researched: " + ", ".join(missed) + "."
        detail = str(research.get("detail", ""))
        if detail:
            body += " " + detail
        return self.render_alert("high", "Public source research is incomplete", body)

    def _render_leads(self) -> str:
        findings = [f for f in self._screening_findings() if _meta(f, "profile_research")]
        if not findings:
            return ""
        parts = [
            "<h3>Public Source Leads (Need Human Review)</h3>",
            "<table class='sortable'><caption>Leads from public sources. Low confidence, not conclusions</caption>"
            "<thead><tr><th scope='col'>Severity</th><th scope='col'>Name searched</th>"
            "<th scope='col'>Role</th><th scope='col'>Category</th><th scope='col'>Source</th>"
            "<th scope='col'>Accessed</th><th scope='col'>Quote</th></tr></thead><tbody>",
        ]
        for finding in findings:
            info = _meta(finding, "profile_research")
            citations = finding.get("citations", [])
            first = citations[0] if isinstance(citations, list) and citations and isinstance(citations[0], dict) else {}
            roles = ", ".join(str(r) for r in info.get("roles", []))
            parts.append(
                "<tr>"
                f"<td>{self.severity_badge(str(finding.get('severity', 'P3')))}</td>"
                f"<td>{self.escape(str(info.get('researched_name', '')))}</td>"
                f"<td>{self.escape(roles)}</td>"
                f"<td>{self.escape(str(info.get('category', '')).replace('_', ' '))}</td>"
                f"<td>{self.escape(str(info.get('source_url', '')))}</td>"
                f"<td>{self.escape(str(info.get('access_date', '')))}</td>"
                f"<td>{self.escape(str(first.get('exact_quote', '')))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_statement(self, coverage: dict[str, Any]) -> str:
        not_covered = [str(n) for n in coverage.get("not_covered", [])]
        items = "".join(f"<li>{self.escape(n)}</li>" for n in not_covered)
        research = coverage.get("profile_research")
        searched = isinstance(research, dict) and bool(research.get("ran"))
        egress = (
            "<p>Public source research sent names and roles, and no document text, to the external server "
            "named in the deal config. Leads are low confidence. A lead may concern someone with the same name.</p>"
            if searched
            else ""
        )
        return (
            "<div class='text-muted'>"
            "<p>List matching runs on this machine. Names are compared with lists downloaded earlier. "
            "Every match shown is a possible match that needs human review. "
            "A name match alone does not show that the screened party is the listed party. "
            "Not finding a match is not clearance.</p>"
            + egress
            + (f"<p>Not screened:</p><ul>{items}</ul>" if items else "")
            + "</div>"
        )


def _meta(finding: dict[str, Any], key: str) -> dict[str, Any]:
    meta = finding.get("metadata", {})
    value = meta.get(key) if isinstance(meta, dict) else None
    return value if isinstance(value, dict) else {}
