"""Domain deep-dive renderer — per-domain analysis with category grouping (Issue #104)."""

from __future__ import annotations

from collections import defaultdict

from dd_agents.reporting.html_base import (
    DOMAIN_AGENTS,
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SectionRenderer,
)
from dd_agents.utils.constants import SEVERITY_P3


class DomainRenderer(SectionRenderer):
    """Render all four domain deep-dive sections."""

    def render(self) -> str:
        parts: list[str] = []
        for domain in DOMAIN_AGENTS:
            parts.append(self._render_domain_section(domain))
        return "\n".join(parts)

    def _render_domain_section(self, domain: str) -> str:
        display = DOMAIN_DISPLAY.get(domain, domain)
        domain_color = DOMAIN_COLORS.get(domain, "#666")
        sev = self.data.domain_severity.get(domain, {})
        risk = self.data.domain_risk_labels.get(domain, "Clean")
        risk_color = self.risk_color(risk)
        total = sum(sev.values())
        categories = self.data.category_groups.get(domain, {})
        top_findings = self.data.top_findings_by_domain.get(domain, [])

        parts: list[str] = [
            f"<section class='report-section' id='sec-domain-{self.escape(domain)}'>",
            f"<div class='domain-section' data-domain='{self.escape(domain)}'>",
            f"<div class='domain-header' style='border-left-color:{domain_color}' "
            f"tabindex='0' role='button' aria-expanded='false'>",
            f"<h2>{self.escape(display)} ({total} findings)</h2>",
            f"<span><span class='severity-badge' style='background:{risk_color}'>{self.escape(risk)}</span> "
            f"<span class='arrow'>&#9654;</span></span>",
            "</div>",
            "<div class='domain-body'>",
        ]

        parts.append(self.render_severity_bar(sev))

        if categories:
            # Category summary table
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th scope='col'>Category</th><th scope='col'>Findings</th><th scope='col'>Severity Mix</th>"
                "<th scope='col'>Top Entity</th></tr></thead><tbody>"
            )
            for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                cat_sev: dict[str, int] = defaultdict(int)
                subject_counts: dict[str, int] = defaultdict(int)
                for cf in cat_findings:
                    cat_sev[cf.get("severity", SEVERITY_P3)] += 1
                    subject_counts[str(cf.get("_subject_safe_name", cf.get("_subject", "")))] += 1
                top_subject_raw = max(subject_counts, key=lambda c: subject_counts.get(c, 0)) if subject_counts else ""
                top_subject_display = self.data.display_names.get(top_subject_raw, top_subject_raw)
                sev_mix = ", ".join(f"{k}:{v}" for k, v in sorted(cat_sev.items()) if v > 0)

                parts.append(
                    f"<tr><td>{self.escape(cat)}</td><td>{len(cat_findings)}</td>"
                    f"<td>{self.escape(sev_mix)}</td><td>{self.escape(top_subject_display)}</td></tr>"
                )
            parts.append("</tbody></table>")

            # Count all findings across categories
            all_domain_findings = [f for cat_f in categories.values() for f in cat_f]

            if len(all_domain_findings) <= 10:
                # Few findings — render all category groups directly
                for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                    parts.append(self.render_category_group(cat, cat_findings))
            else:
                # Top 10 material findings as cards
                for f in top_findings[:10]:
                    parts.append(self.render_finding_card(f))
                    parts.append(self.render_finding_detail(f))

                # Remaining findings in collapsed section
                parts.append(
                    "<div class='domain-section'>"
                    "<div class='domain-header' tabindex='0' role='button' aria-expanded='false'>"
                    f"<h2>Show all {len(all_domain_findings)} findings</h2>"
                    "<span class='arrow'>&#9654;</span></div>"
                    "<div class='domain-body'>"
                )
                for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                    parts.append(self.render_category_group(cat, cat_findings))
                parts.append("</div></div>")
        else:
            parts.append("<p class='text-muted'>No findings in this domain.</p>")

        parts.extend(["</div>", "</div>", "</section>"])
        return "\n".join(parts)
