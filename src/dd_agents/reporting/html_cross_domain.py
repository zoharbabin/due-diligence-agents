"""Cross-Domain Risk Correlation renderer (Issues #103, #189).

Renders compound risk analysis across multiple domains,
highlighting entities with correlated risks.  Also shows
cross-domain trigger analysis results from the neurosymbolic
pass-2 pipeline (Issue #189).
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class CrossDomainRenderer(SectionRenderer):
    """Render Cross-Domain Risk Correlation section."""

    def render(self) -> str:
        risks: list[dict[str, Any]] = getattr(self.data, "cross_domain_risks", [])
        triggers: list[dict[str, Any]] = getattr(self.data, "cross_domain_triggers", [])
        if not risks and not triggers:
            return ""

        parts: list[str] = [
            "<section id='sec-cross-domain' class='report-section'>",
            "<h2>Cross-Domain Risk Correlation</h2>",
        ]

        if risks:
            self._render_compound_risks(parts, risks)

        if triggers:
            self._render_trigger_analysis(parts, triggers)

        parts.append("</section>")
        return "\n".join(parts)

    def _render_compound_risks(self, parts: list[str], risks: list[dict[str, Any]]) -> None:
        """Render the compound risk correlation table."""
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

        parts.append("<h3>Compound Risk Summary</h3>")
        parts.append(
            "<table class='subject-table sortable'><thead><tr>"
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

    def _render_trigger_analysis(self, parts: list[str], triggers: list[dict[str, Any]]) -> None:
        """Render the cross-domain trigger analysis results (Issue #189)."""
        parts.append("<h3>Cross-Domain Verification</h3>")
        parts.append(
            "<p>The following cross-domain verifications were automatically triggered "
            "when specialist agents identified findings requiring validation by other domains.</p>"
        )
        parts.append(
            "<table class='subject-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Source</th>"
            "<th scope='col'>Target</th>"
            "<th scope='col'>Type</th>"
            "<th scope='col'>Priority</th>"
            "</tr></thead><tbody>"
        )
        for trigger in triggers[:20]:
            subject = self.escape(str(trigger.get("subject", "")))
            source = self.escape(str(trigger.get("source_agent", "")))
            target = self.escape(str(trigger.get("target_agent", "")))
            ttype = self.escape(str(trigger.get("trigger_type", "")))
            priority = str(trigger.get("priority", ""))
            badge = self.severity_badge(priority)
            parts.append(
                f"<tr><td>{subject}</td><td>{source}</td><td>{target}</td><td>{ttype}</td><td>{badge}</td></tr>"
            )
        parts.append("</tbody></table>")
