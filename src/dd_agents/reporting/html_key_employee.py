"""Key Employee & Organizational Risk renderer (Issue #131).

Renders analysis of key-person dependencies, employment agreements,
retention risk, and non-compete enforcement gaps.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class KeyEmployeeRenderer(SectionRenderer):
    """Render Key Employee & Organizational Risk section."""

    def render(self) -> str:
        if self.data is None:
            return ""

        analysis: dict[str, Any] = getattr(self.data, "key_employee_analysis", {})
        if not analysis or analysis.get("total_findings", 0) == 0:
            return ""

        total = analysis.get("total_findings", 0)
        retention_count = analysis.get("retention_risk_count", 0)
        noncompete_count = analysis.get("noncompete_gap_count", 0)
        findings: list[dict[str, Any]] = analysis.get("findings", [])

        parts: list[str] = [
            "<section class='report-section' id='sec-key-employee'>",
            "<h2>Key Employee &amp; Organizational Risk</h2>",
        ]

        # Alert for critical findings
        p0_p1 = [f for f in findings if str(f.get("severity", "P3")) in ("P0", "P1")]
        if p0_p1:
            parts.append(
                self.render_alert(
                    "critical" if any(str(f.get("severity")) == "P0" for f in p0_p1) else "high",
                    f"{len(p0_p1)} Critical Key-Person Risk{'s' if len(p0_p1) != 1 else ''}",
                    "Key employee dependencies with high severity require immediate retention planning.",
                )
            )

        # Metric cards
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total}</div>"
            "<div class='label'>Key Employee Findings</div></div>"
            f"<div class='metric-card'><div class='value'>{retention_count}</div>"
            "<div class='label'>Retention Risks</div></div>"
            f"<div class='metric-card'><div class='value'>{noncompete_count}</div>"
            "<div class='label'>Non-Compete Gaps</div></div>"
            "</div>"
        )

        # Findings table
        if findings:
            parts.append(
                "<table class='subject-table sortable'><thead><tr>"
                "<th scope='col'>Entity</th><th scope='col'>Severity</th>"
                "<th scope='col'>Finding</th><th scope='col'>Category</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:30]:
                entity = self.escape(self._resolve_display_name(f))
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                cat = self.escape(str(f.get("category", "")))
                parts.append(
                    f"<tr><td>{entity}</td><td>{self.severity_badge(sev)}</td><td>{title}</td><td>{cat}</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
