"""Domain summary cards — Layer 3 domain overview (Issue #197).

Renders domain cards with left-border accent, risk badge, severity bar,
top-3 findings preview with severity tag pills, and navigation to detail.

Progressive enhancement: cards are static summaries without JS.
Grid layout: 3-col desktop, 2-col tablet, 1-col mobile.
"""

from __future__ import annotations

from dd_agents.reporting.html_base import (
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
    get_domain_agents,
)
from dd_agents.utils.constants import ALL_SEVERITIES


class DomainSummaryRenderer(SectionRenderer):
    """Render Layer 2 domain summary cards and top-priority findings."""

    def render(self) -> str:
        if not self.data.domain_summaries:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-domain-overview'>",
            "<h2>Domain Overview</h2>",
        ]

        parts.append(self._render_domain_cards())
        dashboard = self._render_dashboard_findings()
        if dashboard:
            parts.append(dashboard)

        parts.append("</section>")
        return "\n".join(p for p in parts if p)

    def _render_domain_cards(self) -> str:
        """Render the domain summary card grid."""
        parts: list[str] = ["<div class='domain-card-grid'>"]

        for domain in get_domain_agents():
            summary = self.data.domain_summaries.get(domain)
            if not summary:
                continue

            display = DOMAIN_DISPLAY.get(domain, domain.capitalize())
            color = DOMAIN_COLORS.get(domain, "#333")
            rag = summary.get("rag_status", "green")
            risk_label = self.escape(str(summary.get("risk_label", "Clean")))
            finding_count = summary.get("finding_count", 0)
            sev_counts: dict[str, int] = summary.get("severity_counts", {})
            top_findings = summary.get("top_findings_preview", [])

            rag_color = {"red": "#dc3545", "amber": "#fd7e14", "green": "#28a745"}.get(rag, "#28a745")

            parts.append(
                f"<div class='domain-card' style='--card-accent:{color}'>"
                f"<div class='domain-card-header'>"
                f"<span class='domain-card-name'>{self.escape(display)}</span>"
                f"<span class='domain-card-badge' style='background:{rag_color}'>{risk_label}</span>"
                f"</div>"
            )

            if finding_count > 0:
                # Severity mini-bar (only for domains with findings)
                total = max(sum(sev_counts.values()), 1)
                parts.append("<div class='sev-bar'>")
                for sev in ALL_SEVERITIES:
                    count = sev_counts.get(sev, 0)
                    if count > 0:
                        pct = count / total * 100
                        parts.append(
                            f"<span style='width:{pct:.1f}%;background:{SEVERITY_COLORS[sev]}' "
                            f"title='{sev}: {count}'></span>"
                        )
                parts.append("</div>")

                # Finding count
                parts.append(
                    f"<div class='domain-card-count'>{finding_count} "
                    f"{'finding' if finding_count == 1 else 'findings'}</div>"
                )

                # Top findings preview
                if top_findings:
                    parts.append("<ul class='domain-card-findings'>")
                    for fp in top_findings[:3]:
                        title = self.escape(str(fp.get("title", ""))[:55])
                        sev = str(fp.get("severity", "P3"))
                        sev_color = SEVERITY_COLORS.get(sev, "#6c757d")
                        parts.append(
                            f"<li><span class='sev-tag' style='background:{sev_color}'>"
                            f"{self.escape(sev)}</span> {title}</li>"
                        )
                    parts.append("</ul>")

                # Narrative headline (from LLM narrative if available)
                narr = self._get_domain_narrative(domain)
                if narr:
                    headline = self.escape(str(narr.get("headline", "")).strip())
                    if headline:
                        parts.append(f"<div class='domain-card-narrative'>{headline}</div>")
            else:
                parts.append("<div class='domain-card-clean'>No findings</div>")

            # Navigation link
            parts.append(
                f"<a href='#sec-domain-{self.escape(domain)}' class='domain-card-link'>View details &rarr;</a>"
            )
            parts.append("</div>")

        parts.append("</div>")
        return "\n".join(parts)

    def _get_domain_narrative(self, domain: str) -> dict[str, str] | None:
        """Get LLM-generated narrative for a domain from computed narrative data."""
        narr = self.data.narrative
        if not narr or not isinstance(narr, dict):
            return None
        summaries = narr.get("domain_summaries", [])
        if not isinstance(summaries, list):
            return None
        for s in summaries:
            if isinstance(s, dict) and s.get("domain") == domain:
                return s
        return None

    def _render_dashboard_findings(self) -> str:
        """Render top-5 priority findings widget."""
        findings = self.data.dashboard_findings
        if not findings:
            return ""

        parts: list[str] = [
            "<h3>Top Priority Findings</h3>",
            "<div class='priority-findings'>",
        ]

        for i, f in enumerate(findings[:5], 1):
            title = self.escape(str(f.get("title", "Untitled")))
            sev = str(f.get("severity", "P3"))
            sev_color = SEVERITY_COLORS.get(sev, "#6c757d")
            agent = str(f.get("agent", ""))
            domain_display = DOMAIN_DISPLAY.get(agent, agent.capitalize())
            entity = self.escape(self._resolve_display_name(f))

            parts.append(
                f"<div class='priority-finding' data-severity='{self.escape(sev)}' "
                f"data-domain='{self.escape(agent)}'>"
                f"<span class='priority-rank'>#{i}</span>"
                f"<div class='priority-content'>"
                f"<div class='priority-title'>"
                f"<span class='severity-badge' style='background:{sev_color}'>{self.escape(sev)}</span> "
                f"{title}"
                f"</div>"
                f"<div class='text-small text-muted'>"
                f"{self.escape(domain_display)} &mdash; {entity}"
                f"</div>"
                f"</div>"
                f"</div>"
            )

        parts.append("</div>")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS for domain summary cards (appended to main CSS via html_base)
# ---------------------------------------------------------------------------

DOMAIN_SUMMARY_CSS = """
/* Domain Summary Cards */
.domain-card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 24px; }
.domain-card { background: #fff; border-radius: 10px; padding: 18px 20px;
               border: 1px solid #e8ecf0; display: flex;
               flex-direction: column; gap: 6px; text-align: left;
               border-left: 4px solid var(--card-accent, #333);
               transition: box-shadow 0.15s; }
.domain-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.domain-card-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.domain-card-name { font-weight: 700; font-size: 0.92em; letter-spacing: 0.02em;
                    text-transform: uppercase; color: #1a1a2e; }
.domain-card-badge { font-size: 0.7em; font-weight: 600; color: #fff; padding: 2px 8px;
                     border-radius: 10px; letter-spacing: 0.02em; white-space: nowrap; }
.domain-card-count { font-size: 0.8em; color: #64748b; }
.domain-card-clean { font-size: 0.82em; color: #94a3b8; padding: 6px 0; }
.domain-card-findings { margin: 0; padding: 0; font-size: 0.8em;
                        color: #475569; list-style: none; }
.domain-card-findings li { margin-bottom: 5px; display: flex; align-items: baseline; gap: 6px;
                           white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.domain-card-findings .sev-tag { font-size: 0.75em; font-weight: 700; color: #fff;
                                  padding: 1px 5px; border-radius: 3px; flex-shrink: 0; }
.domain-card-narrative { font-size: 0.78em; color: #64748b; line-height: 1.5;
                         font-style: italic; border-top: 1px solid #f1f5f9; padding-top: 8px; }
.domain-card-link { font-size: 0.78em; color: #3b82f6; text-decoration: none;
                    font-weight: 600; margin-top: auto; }
.domain-card-link:hover { text-decoration: underline; }

/* Priority findings widget */
.priority-findings { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.priority-finding { display: flex; align-items: flex-start; gap: 12px; padding: 10px 14px;
                    background: #fff; border-radius: 8px; border: 1px solid #e8ecf0; }
.priority-rank { font-size: 1.1em; font-weight: 700; color: #94a3b8;
                 min-width: 24px; text-align: center; }
.priority-content { flex: 1; min-width: 0; }
.priority-title { font-weight: 600; font-size: 0.88em; }

@media (max-width: 900px) { .domain-card-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .domain-card-grid { grid-template-columns: 1fr; } }
@media print { .domain-card-link { display: none; } }
"""
