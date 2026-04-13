"""Subject profiles renderer — per-subject expandable sections (Issue #105)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html_base import (
    DOMAIN_AGENTS,
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
)
from dd_agents.utils.constants import SEVERITY_P3


class SubjectRenderer(SectionRenderer):
    """Render per-subject detail sections."""

    def render(self) -> str:
        parts: list[str] = [
            "<section id='sec-subjects' class='report-section'>",
            "<h2>Entity Detail</h2>",
        ]
        for csn, data in sorted(self.merged_data.items()):
            parts.append(self._render_subject_section(csn, data))
        parts.append("</section>")
        return "\n".join(parts)

    def _render_subject_section(self, csn: str, data: Any) -> str:
        raw_name = data.get("subject", csn) if isinstance(data, dict) else csn
        subject_name = self.data.display_names.get(csn, raw_name) if self.data else raw_name
        raw_findings = data.get("findings", []) if isinstance(data, dict) else []
        gaps = data.get("gaps", []) if isinstance(data, dict) else []
        xrefs = data.get("cross_references", []) if isinstance(data, dict) else []
        gov_pct = data.get("governance_resolution_pct") if isinstance(data, dict) else None

        # Enrich findings with CSN keys and apply severity recalibration
        # (merged_data findings are raw — recalibration is only applied in compute())
        findings: list[dict[str, Any]] = []
        for f in raw_findings:
            if isinstance(f, dict):
                enriched = ReportDataComputer._recalibrate_severity(f)
                enriched = {**enriched, "_subject_safe_name": csn, "_subject": raw_name}
                findings.append(enriched)

        finding_count = len(findings)
        sev_summary: dict[str, int] = defaultdict(int)
        for f in findings:
            sev_summary[f.get("severity", SEVERITY_P3)] += 1
        sev_str = " ".join(
            f"<span class='severity-badge' style='background:{SEVERITY_COLORS.get(s, '#ccc')}'>"
            f"{self.escape(str(s))}:{c}</span>"
            for s, c in sorted(sev_summary.items())
            if c > 0
        )

        parts: list[str] = [
            "<div class='subject-section'>",
            f"<div class='subject-header' tabindex='0' role='button' aria-expanded='false'>"
            f"<span><strong>{self.escape(subject_name)}</strong> "
            f"({finding_count} finding{'s' if finding_count != 1 else ''}, "
            f"{len(gaps)} gap{'s' if len(gaps) != 1 else ''}) {sev_str}</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='subject-body'>",
        ]

        # Governance score
        if gov_pct is not None:
            try:
                pct = float(gov_pct)
                color = "#28a745" if pct >= 90 else ("#ffc107" if pct >= 70 else "#dc3545")
                parts.append(
                    f"<div class='mb-8'>Governance Resolution: <strong style='color:{color}'>{pct:.0f}%</strong></div>"
                )
            except (ValueError, TypeError):
                pass

        # Cross-references
        if xrefs and isinstance(xrefs, list):
            parts.append("<h3>Cross-Reference Reconciliation</h3>")
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th scope='col'>Field</th><th scope='col'>Source A</th>"
                "<th scope='col'>Source B</th><th scope='col'>Match</th>"
                "</tr></thead><tbody>"
            )
            for xr in xrefs:
                if not isinstance(xr, dict):
                    continue
                field = self.escape(str(xr.get("data_point", xr.get("field", ""))))
                src_a = self.escape(str(xr.get("contract_value", xr.get("source_a", xr.get("value_a", "")))))
                src_b = self.escape(str(xr.get("reference_value", xr.get("source_b", xr.get("value_b", "")))))
                raw_status = str(xr.get("match_status", xr.get("match", ""))).lower()
                is_match = raw_status in ("match", "true", "yes")
                is_mismatch = raw_status in ("mismatch", "false", "no")
                match_str = "Yes" if is_match else ("No" if is_mismatch else "Unverified")
                row_class = "xref-mismatch" if is_mismatch else ("xref-match" if is_match else "xref-unverified")
                parts.append(
                    f"<tr class='{row_class}'><td>{field}</td><td>{src_a}</td><td>{src_b}</td><td>{match_str}</td></tr>"
                )
            parts.append("</tbody></table>")

        # Findings grouped by domain
        if findings:
            parts.append("<h3>Findings</h3>")
            by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for f in findings:
                domain = self.agent_to_domain(str(f.get("agent", "")))
                by_domain[domain].append(f)

            for domain in DOMAIN_AGENTS:
                domain_f = by_domain.get(domain, [])
                if not domain_f:
                    continue
                display = DOMAIN_DISPLAY.get(domain, domain)
                parts.append(f"<h4 style='color:{DOMAIN_COLORS.get(domain, '#666')}'>{self.escape(display)}</h4>")
                for f in domain_f:
                    parts.append(self.render_finding_card(f))
                    parts.append(self.render_finding_detail(f))

        # Gaps
        if gaps:
            parts.append("<h3>Gaps</h3>")
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th scope='col'>Priority</th><th scope='col'>Type</th><th scope='col'>Missing Item</th>"
                "<th scope='col'>Risk</th><th scope='col'>Why Needed</th>"
                "<th scope='col'>Request to Company</th><th scope='col'>Agent</th>"
                "</tr></thead><tbody>"
            )
            for g in gaps:
                if isinstance(g, dict):
                    prio = self.escape(str(g.get("priority", "")))
                    gtype = self.escape(str(g.get("gap_type", "")))
                    item = self.escape(str(g.get("missing_item", "")))
                    risk = self.escape(str(g.get("risk_if_missing", "")))
                    why = self.escape(str(g.get("why_needed", "")))
                    request = self.escape(str(g.get("request_to_company", "")))
                    agent = self.escape(str(g.get("agent", "")))
                    parts.append(
                        f"<tr><td>{prio}</td><td>{gtype}</td><td>{item}</td><td>{risk}</td>"
                        f"<td>{why}</td><td>{request}</td><td>{agent}</td></tr>"
                    )
            parts.append("</tbody></table>")

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)
