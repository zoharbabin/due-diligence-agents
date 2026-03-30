"""Product Adoption Matrix & Platform Dependency renderer (Issue #138).

Renders a matrix showing which customers use which products,
along with single-product risk and multi-product adoption metrics.
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class ProductAdoptionRenderer(SectionRenderer):
    """Render Product Adoption Matrix section."""

    def render(self) -> str:
        if self.data is None:
            return ""

        adoption: dict[str, Any] = getattr(self.data, "product_adoption", {})
        if not adoption:
            return ""

        products: list[str] = adoption.get("products", [])
        matrix: dict[str, list[str]] = adoption.get("matrix", {})
        if not products or not matrix:
            return ""

        total_customers = len(matrix)
        multi_product = sum(1 for prods in matrix.values() if len(prods) > 1)
        single_product = total_customers - multi_product
        single_pct = round(100 * single_product / total_customers, 1) if total_customers > 0 else 0.0

        parts: list[str] = [
            "<section class='report-section' id='sec-product-adoption'>",
            "<h2>Product Adoption Matrix</h2>",
        ]

        # Alert for high single-product dependency
        if single_pct >= 70:
            parts.append(
                self.render_alert(
                    "high",
                    f"{single_pct:.0f}% Single-Product Customers",
                    "High single-product dependency increases churn risk "
                    "— customers using only one product are easier to replace.",
                )
            )

        # Metric cards
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value'>{len(products)}</div>"
            "<div class='label'>Products Identified</div></div>"
            f"<div class='metric-card'><div class='value'>{multi_product}</div>"
            "<div class='label'>Multi-Product Customers</div></div>"
            f"<div class='metric-card'><div class='value'>{single_pct:.0f}%</div>"
            "<div class='label'>Single-Product Risk</div></div>"
            "</div>"
        )

        # Adoption matrix table
        parts.append("<table class='customer-table sortable'><thead><tr><th scope='col'>Entity</th>")
        for prod in products:
            parts.append(f"<th scope='col'>{self.escape(prod)}</th>")
        parts.append("<th scope='col'>Product Count</th></tr></thead><tbody>")

        for csn, customer_products in sorted(matrix.items()):
            display_name = self.escape(self.data.display_names.get(csn, csn) if self.data else csn)
            parts.append(f"<tr><td>{display_name}</td>")
            for prod in products:
                if prod in customer_products:
                    parts.append("<td style='text-align:center;color:#28a745;'>&#10003;</td>")
                else:
                    parts.append("<td style='text-align:center;color:#ccc;'>&mdash;</td>")
            parts.append(f"<td style='text-align:center;'>{len(customer_products)}</td></tr>")

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)
