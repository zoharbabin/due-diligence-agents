"""SaaS health metrics dashboard renderer (Issue #115).

Renders KPI cards for total ARR, customer count, average contract value,
top customer concentration, and tier distribution.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


def _fmt_currency(amount: float) -> str:
    """Format a dollar amount for display."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:,.0f}"


class SaaSMetricsRenderer(SectionRenderer):
    """Render SaaS health metrics dashboard."""

    def render(self) -> str:
        total_arr = getattr(self.data, "total_contracted_arr", 0.0)
        metrics: dict[str, Any] = getattr(self.data, "saas_metrics", {})
        if not metrics or total_arr <= 0:
            return ""

        total_customers = metrics.get("total_customers", 0)
        customers_with_rev = metrics.get("customers_with_revenue", 0)
        avg_cv = metrics.get("avg_contract_value", 0.0)
        top_pct = metrics.get("top_customer_pct", 0.0)
        tiers = metrics.get("tier_distribution", {})

        parts: list[str] = [
            "<section class='report-section' id='sec-saas'>",
            "<h2>SaaS Health Metrics</h2>",
            "<div class='metrics-strip'>",
        ]

        # KPI cards
        kpis = [
            ("Total ARR", _fmt_currency(total_arr)),
            ("Customers", str(total_customers)),
            ("With Revenue Data", f"{customers_with_rev}/{total_customers}"),
            ("Avg Contract Value", _fmt_currency(avg_cv)),
            ("Top Customer", f"{top_pct:.0f}% of ARR"),
        ]
        for label, value in kpis:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='metric-value'>{html.escape(value)}</div>"
                f"<div class='metric-label'>{html.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        # Tier distribution
        if tiers:
            parts.append("<h3>Customer Tier Distribution</h3>")
            parts.append("<div class='tier-distribution'>")
            for tier_name, count in tiers.items():
                pct = (count / total_customers * 100) if total_customers > 0 else 0
                parts.append(
                    f"<div class='tier-bar'>"
                    f"<span class='tier-label'>{html.escape(str(tier_name))}</span>"
                    f"<div class='bar-bg'><div class='bar-fill' style='width:{max(pct, 2):.0f}%'></div></div>"
                    f"<span class='tier-count'>{count} ({pct:.0f}%)</span>"
                    f"</div>"
                )
            parts.append("</div>")

        # Concentration alert
        if top_pct >= 30:
            level = "critical" if top_pct >= 50 else "warning"
            parts.append(
                f"<div class='alert-box {level}'>"
                f"Top customer represents {top_pct:.0f}% of total ARR — "
                f"{'severe' if top_pct >= 50 else 'moderate'} concentration risk."
                f"</div>"
            )

        parts.append("</section>")
        return "\n".join(parts)
