"""Discount & Pricing Analysis renderer (Issue #135).

Renders discount distribution, pricing findings table, and
alert boxes for revenue quality concerns.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class DiscountAnalysisRenderer(SectionRenderer):
    """Render Discount & Pricing Analysis section."""

    def render(self) -> str:
        analysis: dict[str, Any] = getattr(self.data, "discount_analysis", {})
        total = analysis.get("total_pricing_findings", 0)
        if total == 0:
            return ""

        parts: list[str] = [
            "<section id='sec-discount' class='report-section'>",
            "<h2>Discount &amp; Pricing Analysis</h2>",
        ]

        customers_with = analysis.get("customers_with_discounts", 0)
        if customers_with > 0:
            parts.append(
                self.render_alert(
                    "high" if customers_with > 5 else "info",
                    f"{customers_with} entities with identified discounts",
                    f"{total} pricing-related findings across "
                    f"{customers_with} entities. "
                    f"Review discount concentration for revenue quality risk.",
                )
            )

        # Distribution summary
        dist = analysis.get("distribution", {})
        if any(v > 0 for v in dist.values()):
            parts.append("<h3>Discount Distribution</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Bucket</th>"
                "<th scope='col'>Count</th>"
                "</tr></thead><tbody>"
            )
            for bucket, count in dist.items():
                parts.append(f"<tr><td>{self.escape(str(bucket))}</td><td>{count}</td></tr>")
            parts.append("</tbody></table>")

        # Findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Pricing Findings</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Severity</th>"
                "<th scope='col'>Entity</th>"
                "<th scope='col'>Finding</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                title = self.escape(str(f.get("title", "")))
                customer = self.escape(str(f.get("_customer", f.get("_customer_safe_name", ""))))
                parts.append(f"<tr><td>{self.severity_badge(sev)}</td><td>{customer}</td><td>{title}</td></tr>")
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
