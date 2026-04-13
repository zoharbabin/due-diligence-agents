"""Insurance & Liability Analysis renderer (Issue #156).

Renders liability caps, insurance requirements, uncapped liability alerts,
and indemnification findings table.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.utils.constants import SEVERITY_P3


class LiabilityRenderer(SectionRenderer):
    """Render Insurance & Liability Analysis section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "liability_analysis", {})
        total = analysis.get("total_liability_findings", 0)
        if total == 0:
            return ""

        insurance = analysis.get("insurance_count", 0)
        liability_caps = analysis.get("liability_cap_count", 0)
        uncapped = analysis.get("uncapped_count", 0)
        indemnification = analysis.get("indemnification_count", 0)

        parts: list[str] = [
            "<section id='sec-liability' class='report-section'>",
            "<h2>Insurance &amp; Liability Analysis</h2>",
        ]

        # Metrics strip
        parts.append("<div class='metrics-strip'>")
        for label, value in [
            ("Total Findings", str(total)),
            ("Insurance", str(insurance)),
            ("Liability Caps", str(liability_caps)),
            ("Uncapped", str(uncapped)),
            ("Indemnification", str(indemnification)),
        ]:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        # Uncapped liability alert
        if uncapped > 0:
            parts.append(
                self.render_alert(
                    "critical",
                    f"Uncapped liability detected in {uncapped} contracts",
                    f"{uncapped} contracts have no liability cap. Negotiate caps before close to limit exposure.",
                )
            )

        # Insurance requirement alert
        if insurance > 0:
            parts.append(
                self.render_alert(
                    "info",
                    f"Insurance requirements in {insurance} contracts",
                    f"{insurance} contracts contain insurance requirements. "
                    f"Verify current coverage meets all contractual obligations.",
                )
            )

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Liability Findings</h3>")
            parts.append(
                "<table class='subject-table sortable'><thead><tr>"
                "<th scope='col'>Entity</th>"
                "<th scope='col'>Finding</th>"
                "<th scope='col'>Severity</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", SEVERITY_P3))
                title = self.escape(str(f.get("title", "")))
                entity_name = self.escape(self._resolve_display_name(f))
                parts.append(f"<tr><td>{entity_name}</td><td>{title}</td><td>{self.severity_badge(sev)}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
