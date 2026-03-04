"""Business analysis renderers — CoC, Privacy, Customer Health (Issue #113 B4, B10).

These sections synthesize findings into business-level insights with
alert boxes providing executive context.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.reporting.html_base import SectionRenderer


class CoCAnalysisRenderer(SectionRenderer):
    """Render the Change of Control analysis section (B4)."""

    def render(self) -> str:
        coc = self.data.coc_findings
        if not coc:
            return ""

        customers_affected = self.data.coc_customers_affected
        consent_required = self.data.consent_required_customers

        parts: list[str] = [
            "<section class='report-section' id='sec-coc'>",
            "<h2>Change of Control Analysis</h2>",
        ]

        # Summary alert
        parts.append(
            self.render_alert(
                "high" if customers_affected > 5 else "info",
                f"{customers_affected} entities with change-of-control provisions",
                f"{len(coc)} change-of-control findings identified across "
                f"{customers_affected} entities. "
                f"{consent_required} entities may require assignment consent. "
                f"Review consent requirements and assess impact on deal timeline.",
            )
        )

        # CoC findings by customer
        by_customer: dict[str, list[dict[str, Any]]] = {}
        for f in coc:
            cust = str(f.get("_customer", "Unknown"))
            by_customer.setdefault(cust, []).append(f)

        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Findings</th>"
            "<th scope='col'>Severity</th>"
            "<th scope='col'>Primary Issue</th>"
            "</tr></thead><tbody>"
        )

        for customer, findings in sorted(by_customer.items(), key=lambda x: -len(x[1])):
            count = len(findings)
            max_sev = "P3"
            for f in findings:
                sev = f.get("severity", "P3")
                if sev < max_sev:  # P0 < P1 < P2 < P3 lexicographically
                    max_sev = sev
            primary = html.escape(str(findings[0].get("title", "")))
            parts.append(
                f"<tr><td><strong>{html.escape(customer)}</strong></td>"
                f"<td>{count}</td>"
                f"<td>{self.severity_badge(max_sev)}</td>"
                f"<td>{primary}</td></tr>"
            )

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)


class PrivacyAnalysisRenderer(SectionRenderer):
    """Render the Data Privacy & DPA analysis section (B10)."""

    def render(self) -> str:
        privacy = self.data.privacy_findings
        if not privacy:
            return ""

        by_customer: dict[str, list[dict[str, Any]]] = {}
        for f in privacy:
            cust = str(f.get("_customer", "Unknown"))
            by_customer.setdefault(cust, []).append(f)

        parts: list[str] = [
            "<section class='report-section' id='sec-privacy'>",
            "<h2>Data Privacy &amp; DPA Analysis</h2>",
        ]

        # Alert
        p0_count = sum(1 for f in privacy if f.get("severity") == "P0")
        level = "critical" if p0_count > 0 else ("high" if len(privacy) > 5 else "info")
        parts.append(
            self.render_alert(
                level,
                f"{len(privacy)} privacy findings across {len(by_customer)} entities",
                f"Data privacy analysis identified {len(privacy)} findings. "
                f"Review GDPR/CCPA compliance status and DPA coverage for each entity.",
            )
        )

        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Findings</th>"
            "<th scope='col'>Max Severity</th>"
            "<th scope='col'>Primary Issue</th>"
            "</tr></thead><tbody>"
        )

        for customer, findings in sorted(by_customer.items(), key=lambda x: -len(x[1])):
            max_sev = min((f.get("severity", "P3") for f in findings), default="P3")
            primary = html.escape(str(findings[0].get("title", "")))
            parts.append(
                f"<tr><td><strong>{html.escape(customer)}</strong></td>"
                f"<td>{len(findings)}</td>"
                f"<td>{self.severity_badge(max_sev)}</td>"
                f"<td>{primary}</td></tr>"
            )

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)


class CustomerHealthRenderer(SectionRenderer):
    """Render the Customer Health Tiers section (G2)."""

    def render(self) -> str:
        tier1 = self.data.tier1_customers
        tier2 = self.data.tier2_customers
        tier3 = self.data.tier3_customers

        if not tier1 and not tier2 and not tier3:
            return ""

        total = len(tier1) + len(tier2) + len(tier3)

        parts: list[str] = [
            "<section class='report-section' id='sec-health'>",
            "<h2>Entity Health Tiers</h2>",
        ]

        # Summary alert
        if tier1:
            parts.append(
                self.render_alert(
                    "critical",
                    f"{len(tier1)} entities require immediate attention",
                    f"Tier 1 (Critical): {len(tier1)} entities have P0 findings. "
                    f"Tier 2 (High): {len(tier2)} entities have P1 findings. "
                    f"Tier 3 (Standard): {len(tier3)} of {total} entities have only lower-severity findings.",
                )
            )
        elif tier2:
            parts.append(
                self.render_alert(
                    "high",
                    f"{len(tier2)} entities with high-priority findings",
                    f"No critical (P0) entities. "
                    f"Tier 2: {len(tier2)} entities have P1 findings. "
                    f"Tier 3: {len(tier3)} of {total} entities are lower risk.",
                )
            )
        else:
            parts.append(
                self.render_alert(
                    "good",
                    "All entities are in standard health tier",
                    f"All {total} entities have only P2/P3 findings or no findings.",
                )
            )

        # Tier cards
        parts.append("<div class='severity-cards'>")

        parts.append(
            f"<div class='severity-card' style='background:var(--sev-p0-bg);border:1px solid var(--red)'>"
            f"<div class='sev-count' style='color:var(--red)'>{len(tier1)}</div>"
            f"<div class='sev-label'>Tier 1 &mdash; Critical</div></div>"
        )
        parts.append(
            f"<div class='severity-card' style='background:var(--sev-p1-bg);border:1px solid var(--orange)'>"
            f"<div class='sev-count' style='color:var(--orange)'>{len(tier2)}</div>"
            f"<div class='sev-label'>Tier 2 &mdash; High</div></div>"
        )
        parts.append(
            f"<div class='severity-card' style='background:var(--sev-p3-bg);border:1px solid var(--gray)'>"
            f"<div class='sev-count' style='color:var(--gray)'>{len(tier3)}</div>"
            f"<div class='sev-label'>Tier 3 &mdash; Standard</div></div>"
        )
        parts.append(
            f"<div class='severity-card' style='background:#f0f0ff;border:1px solid var(--blue)'>"
            f"<div class='sev-count' style='color:var(--blue)'>{total}</div>"
            f"<div class='sev-label'>Total Entities</div></div>"
        )

        parts.append("</div>")  # severity-cards

        # Entity lists
        if tier1:
            parts.append("<h3>Tier 1 &mdash; Immediate Attention</h3><ul>")
            for name in tier1:
                parts.append(f"<li><span class='tier-badge tier-1'>T1</span> {html.escape(name)}</li>")
            parts.append("</ul>")

        if tier2:
            parts.append("<h3>Tier 2 &mdash; Pre-Close Review</h3><ul>")
            for name in tier2:
                parts.append(f"<li><span class='tier-badge tier-2'>T2</span> {html.escape(name)}</li>")
            parts.append("</ul>")

        parts.append("</section>")
        return "\n".join(parts)
