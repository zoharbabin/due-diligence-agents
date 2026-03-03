"""Domain deep-dive renderer — per-domain analysis with category grouping (Issue #104)."""

from __future__ import annotations

import html
from collections import defaultdict

from dd_agents.reporting.html_base import (
    DOMAIN_AGENTS,
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SectionRenderer,
)


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
        risk = self.domain_risk(sev)
        risk_color = self.risk_color(risk)
        total = sum(sev.values())
        categories = self.data.category_groups.get(domain, {})

        parts: list[str] = [
            f"<section class='report-section' id='sec-domain-{html.escape(domain)}'>",
            f"<div class='domain-section' data-domain='{html.escape(domain)}'>",
            f"<div class='domain-header' style='border-left-color:{domain_color}' "
            f"tabindex='0' role='button' aria-expanded='false'>",
            f"<h2>{html.escape(display)} ({total} findings)</h2>",
            f"<span><span class='severity-badge' style='background:{risk_color}'>{html.escape(risk)}</span> "
            f"<span class='arrow'>&#9654;</span></span>",
            "</div>",
            "<div class='domain-body'>",
        ]

        parts.append(self.render_severity_bar(sev))

        if categories:
            parts.append(
                "<table class='sortable'><thead><tr>"
                "<th scope='col'>Category</th><th scope='col'>Findings</th><th scope='col'>Severity Mix</th>"
                "<th scope='col'>Top Entity</th></tr></thead><tbody>"
            )
            for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                cat_sev: dict[str, int] = defaultdict(int)
                customer_counts: dict[str, int] = defaultdict(int)
                for cf in cat_findings:
                    cat_sev[cf.get("severity", "P3")] += 1
                    customer_counts[str(cf.get("_customer", ""))] += 1
                top_customer = max(customer_counts, key=lambda c: customer_counts.get(c, 0)) if customer_counts else ""
                sev_mix = ", ".join(f"{k}:{v}" for k, v in sorted(cat_sev.items()) if v > 0)

                parts.append(
                    f"<tr><td>{html.escape(cat)}</td><td>{len(cat_findings)}</td>"
                    f"<td>{html.escape(sev_mix)}</td><td>{html.escape(top_customer)}</td></tr>"
                )
            parts.append("</tbody></table>")

            for cat, cat_findings in sorted(categories.items(), key=lambda x: -len(x[1])):
                parts.append(self.render_category_group(cat, cat_findings))
        else:
            parts.append("<p class='text-muted'>No findings in this domain.</p>")

        parts.extend(["</div>", "</div>", "</section>"])
        return "\n".join(parts)
