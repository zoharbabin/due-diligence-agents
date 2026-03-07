"""Discount & Pricing Analysis renderer (Issue #135).

Renders discount distribution, top discounted customers, and pricing
concentration analysis with alert boxes for revenue quality concerns.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

_SEV_CLASS: dict[str, str] = {"P0": "sev-p0", "P1": "sev-p1", "P2": "sev-p2", "P3": "sev-p3"}


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
                f"<div class='alert-box alert-amber'>"
                f"<strong>{customers_with}</strong> entities with identified discounts "
                f"across <strong>{total}</strong> pricing-related findings."
                f"</div>"
            )

        # Distribution bars
        dist = analysis.get("distribution", {})
        if any(v > 0 for v in dist.values()):
            parts.append("<h3>Discount Distribution</h3>")
            parts.append("<div class='bar-chart'>")
            max_val = max(dist.values()) if dist else 1
            for bucket, count in dist.items():
                width = int(count / max_val * 100) if max_val > 0 else 0
                parts.append(
                    f"<div class='bar-row'>"
                    f"<span class='bar-label'>{html.escape(str(bucket))}</span>"
                    f"<div class='bar-track'>"
                    f"<div class='bar-fill' style='width:{width}%'></div>"
                    f"</div>"
                    f"<span class='bar-value'>{count}</span>"
                    f"</div>"
                )
            parts.append("</div>")

        # Top findings table
        findings = analysis.get("findings", [])
        if findings:
            parts.append("<h3>Pricing Findings</h3>")
            parts.append(
                "<table class='findings-table'><thead><tr>"
                "<th>Severity</th><th>Entity</th><th>Finding</th>"
                "</tr></thead><tbody>"
            )
            for f in findings[:15]:
                sev = str(f.get("severity", "P3"))
                cls = _SEV_CLASS.get(sev, "sev-p3")
                title = html.escape(str(f.get("title", "")))
                customer = html.escape(str(f.get("_customer", f.get("_customer_safe_name", ""))))
                parts.append(
                    f"<tr><td><span class='sev-badge {cls}'>{sev}</span></td><td>{customer}</td><td>{title}</td></tr>"
                )
            parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
