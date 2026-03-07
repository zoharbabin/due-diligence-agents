"""Cross-Domain Risk Correlation renderer (Issue #103).

Renders compound risk analysis across multiple domains,
highlighting entities with correlated risks.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class CrossDomainRenderer(SectionRenderer):
    """Render Cross-Domain Risk Correlation section."""

    def render(self) -> str:
        risks: list[dict[str, Any]] = getattr(self.data, "cross_domain_risks", [])
        if not risks:
            return ""

        parts: list[str] = [
            "<section id='sec-cross-domain' class='report-section'>",
            "<h2>Cross-Domain Risk Correlation</h2>",
        ]

        # P0 alerts
        for risk in risks:
            has_p0 = risk.get("has_p0", False)
            csn = str(risk.get("entity", ""))
            display = self.data.display_names.get(csn, csn) if self.data else csn
            if has_p0 and csn:
                parts.append(
                    self.render_alert(
                        "critical",
                        f"P0 finding detected for {display}",
                        f"Entity {display} has critical findings spanning "
                        f"{risk.get('domain_count', 0)} domains. Immediate review required.",
                    )
                )

        # Compound risk table
        parts.append("<h3>Compound Risk Summary</h3>")
        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Domains</th>"
            "<th scope='col'>Findings</th>"
            "<th scope='col'>Risk Score</th>"
            "</tr></thead><tbody>"
        )
        for risk in risks[:15]:
            csn = str(risk.get("entity", ""))
            display = self.data.display_names.get(csn, csn) if self.data else csn
            entity = self.escape(display)
            domain_count = risk.get("domain_count", 0)
            finding_count = risk.get("finding_count", 0)
            risk_score = risk.get("risk_score", 0.0)
            parts.append(
                f"<tr><td>{entity}</td><td>{domain_count}</td><td>{finding_count}</td><td>{risk_score:.1f}</td></tr>"
            )
        parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
