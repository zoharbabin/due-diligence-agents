"""Technology Stack Assessment & Technical Debt renderer (Issue #132).

Renders analysis of technology stack, security posture, scalability,
and migration complexity findings.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class TechStackRenderer(SectionRenderer):
    """Render Technology Stack Assessment section."""

    def render(self) -> str:
        if self.data is None:
            return ""

        analysis: dict[str, Any] = getattr(self.data, "tech_stack_analysis", {})
        if not analysis or analysis.get("total_findings", 0) == 0:
            return ""

        total = analysis.get("total_findings", 0)
        security_count = analysis.get("security_gap_count", 0)
        debt_count = analysis.get("tech_debt_count", 0)
        migration_count = analysis.get("migration_risk_count", 0)
        findings: list[dict[str, Any]] = analysis.get("findings", [])

        parts: list[str] = [
            "<section class='report-section' id='sec-tech-stack'>",
            "<h2>Technology Stack Assessment</h2>",
        ]

        # Alert for security gaps
        security_critical = [
            f
            for f in findings
            if str(f.get("severity", "P3")) in ("P0", "P1")
            and any(
                kw in str(f.get("title", "")).lower() + str(f.get("category", "")).lower()
                for kw in ("security", "vulnerability", "soc", "penetration")
            )
        ]
        if security_critical:
            parts.append(
                self.render_alert(
                    "critical",
                    f"{len(security_critical)} Critical Security Gap{'s' if len(security_critical) != 1 else ''}",
                    "Security posture findings at P0/P1 require urgent remediation assessment.",
                )
            )

        # Metric cards
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{total}</div>"
            "<div class='label'>Tech Findings</div></div>"
            f"<div class='metric-card'><div class='value'>{security_count}</div>"
            "<div class='label'>Security Gaps</div></div>"
            f"<div class='metric-card'><div class='value'>{debt_count}</div>"
            "<div class='label'>Technical Debt</div></div>"
            f"<div class='metric-card'><div class='value'>{migration_count}</div>"
            "<div class='label'>Migration Risks</div></div>"
            "</div>"
        )

        # Findings table
        if findings:
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Entity</th><th scope='col'>Severity</th>"
                "<th scope='col'>Finding</th><th scope='col'>Sub-Category</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:30]:
                entity = self.escape(self._resolve_display_name(f))
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                subcat = self.escape(str(f.get("_tech_subcategory", f.get("category", ""))))
                parts.append(
                    f"<tr><td>{entity}</td><td>{self.severity_badge(sev)}</td><td>{title}</td><td>{subcat}</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
