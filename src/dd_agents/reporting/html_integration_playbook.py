"""Post-Close Integration Playbook & Churn Risk Model renderer (Issue #117).

Renders:
1. Churn Risk Score card with severity indicator
2. Integration risk factors table
3. Post-close milestone timeline
4. Integration complexity assessment
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.reporting.html_base import fmt_currency as _fmt_currency


class IntegrationPlaybookRenderer(SectionRenderer):
    """Render the Post-Close Integration Playbook section."""

    def render(self) -> str:
        playbook: dict[str, Any] = getattr(self.data, "integration_playbook", {})
        if not playbook:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-integration'>",
            "<h2>Post-Close Integration Playbook</h2>",
        ]

        # Churn risk score
        churn_score = playbook.get("churn_risk_score", 0)
        churn_label = playbook.get("churn_risk_label", "Unknown")
        complexity = playbook.get("integration_complexity", "Unknown")

        churn_color = self._risk_color(churn_label)
        complexity_color = self._risk_color(complexity)

        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'>"
            f"<div class='value' style='color:{churn_color}'>{churn_score}</div>"
            "<div class='label'>Churn Risk Score</div></div>"
            f"<div class='metric-card'>"
            f"<div class='value' style='color:{churn_color}'>{self.escape(churn_label)}</div>"
            "<div class='label'>Churn Risk Level</div></div>"
            f"<div class='metric-card'>"
            f"<div class='value' style='color:{complexity_color}'>{self.escape(complexity)}</div>"
            "<div class='label'>Integration Complexity</div></div>"
            "</div>"
        )

        # High risk alert
        if churn_score >= 60:
            arr = getattr(self.data, "total_contracted_arr", 0.0)
            at_risk = arr * churn_score / 100
            parts.append(
                self.render_alert(
                    "critical" if churn_score >= 75 else "high",
                    f"Churn Risk Score: {churn_score}/100 ({churn_label})",
                    f"Estimated {_fmt_currency(at_risk)} ARR at elevated churn risk. "
                    "Recommend retention-focused integration plan with customer outreach "
                    "within first 30 days post-close.",
                )
            )

        # Risk factors table
        risk_factors: list[dict[str, Any]] = playbook.get("risk_factors", [])
        if risk_factors:
            parts.append("<h3>Integration Risk Factors</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Risk Factor</th>"
                "<th scope='col'>Impact</th>"
                "<th scope='col'>ARR at Risk</th>"
                "</tr></thead><tbody>"
            )
            for rf in risk_factors:
                factor = self.escape(str(rf.get("factor", "")))
                impact = self.escape(str(rf.get("impact", "")))
                arr_risk = rf.get("arr_at_risk", 0)
                parts.append(f"<tr><td>{factor}</td><td>{impact}</td><td>{_fmt_currency(arr_risk)}</td></tr>")
            parts.append("</tbody></table>")

        # Milestone timeline
        milestones: list[dict[str, Any]] = playbook.get("milestones", [])
        if milestones:
            parts.append("<h3>Integration Milestones</h3>")
            for ms in milestones:
                phase = self.escape(str(ms.get("phase", "")))
                items = ms.get("items", [])
                if not items:
                    continue
                parts.append(f"<h4>{phase}</h4>")
                parts.append("<ul>")
                for item in items:
                    parts.append(f"<li>{self.escape(str(item))}</li>")
                parts.append("</ul>")

        parts.append("</section>")
        return "\n".join(parts)

    @staticmethod
    def _risk_color(label: str) -> str:
        """Return CSS color for a risk label."""
        label_lower = label.lower()
        if label_lower in ("critical", "very high"):
            return "var(--red)"
        if label_lower == "high":
            return "var(--orange)"
        if label_lower == "medium":
            return "var(--amber)"
        return "var(--green)"
