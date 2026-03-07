"""SaaS health metrics dashboard renderer (Issue #115).

Renders KPI cards for total ARR, customer count, average contract value,
top customer concentration, and tier distribution.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer
from dd_agents.reporting.html_base import fmt_currency as _fmt_currency


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
                f"<div class='value'>{self.escape(value)}</div>"
                f"<div class='label'>{self.escape(label)}</div>"
                f"</div>"
            )
        parts.append("</div>")

        # Tier distribution as a table (uses existing CSS)
        if tiers:
            parts.append("<h3>Customer Tier Distribution</h3>")
            parts.append(
                "<table class='customer-table sortable'><thead><tr>"
                "<th scope='col'>Tier</th>"
                "<th scope='col'>Customers</th>"
                "<th scope='col'>%</th>"
                "</tr></thead><tbody>"
            )
            for tier_name, count in tiers.items():
                pct = (count / total_customers * 100) if total_customers > 0 else 0
                parts.append(f"<tr><td>{self.escape(str(tier_name))}</td><td>{count}</td><td>{pct:.0f}%</td></tr>")
            parts.append("</tbody></table>")

        # NRR/GRR section (only if nrr_estimate is present)
        nrr = metrics.get("nrr_estimate")
        if nrr is not None:
            grr = metrics.get("grr_estimate", 0.0)
            expansion = metrics.get("expansion_signals", 0)
            contraction = metrics.get("contraction_signals", 0)

            # Color coding for NRR: green >=115, amber >=100, red <100
            if nrr >= 115:
                nrr_color = "var(--green)"
            elif nrr >= 100:
                nrr_color = "var(--amber)"
            else:
                nrr_color = "var(--red)"

            # Color coding for GRR: green >=90, amber >=80, red <80
            if grr >= 90:
                grr_color = "var(--green)"
            elif grr >= 80:
                grr_color = "var(--amber)"
            else:
                grr_color = "var(--red)"

            parts.append("<h3>Net &amp; Gross Revenue Retention</h3>")
            parts.append("<div class='metrics-strip'>")
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value' style='color:{nrr_color}'>{nrr:.0f}%</div>"
                f"<div class='label'>NRR Estimate</div>"
                f"</div>"
            )
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value' style='color:{grr_color}'>{grr:.0f}%</div>"
                f"<div class='label'>GRR Estimate</div>"
                f"</div>"
            )
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{expansion}</div>"
                f"<div class='label'>Expansion Signals</div>"
                f"</div>"
            )
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='value'>{contraction}</div>"
                f"<div class='label'>Contraction Signals</div>"
                f"</div>"
            )
            parts.append("</div>")

            parts.append(
                self.render_alert(
                    "info",
                    "Benchmark Comparison",
                    f"NRR {nrr:.0f}% vs. best-in-class SaaS benchmark of 120%+. "
                    f"GRR {grr:.0f}% vs. median SaaS benchmark of 90%.",
                )
            )

        # Concentration alert
        if top_pct >= 30:
            parts.append(
                self.render_alert(
                    "critical" if top_pct >= 50 else "high",
                    f"Top customer represents {top_pct:.0f}% of total ARR",
                    f"{'Severe' if top_pct >= 50 else 'Moderate'} concentration risk. "
                    f"Consider earn-out or escrow protections.",
                )
            )

        parts.append("</section>")
        return "\n".join(parts)
