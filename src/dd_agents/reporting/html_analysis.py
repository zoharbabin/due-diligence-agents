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

    # CoC subtype detection keywords (order matters: most specific first)
    _SUBTYPE_KEYWORDS: list[tuple[str, list[str]]] = [
        ("Competitor-Only", ["competitor"]),
        ("Auto-Termination", ["auto-terminat", "automatically terminate"]),
        ("Consent-Required", ["consent"]),
        ("Termination-Right", ["termination right", "right to terminate", "may terminate"]),
        ("Notification", ["notif", "notify", "notice"]),
    ]

    @classmethod
    def _detect_subtype(cls, finding: dict[str, Any]) -> str:
        """Detect CoC subtype from finding title/description keywords."""
        combined = (f"{str(finding.get('title', ''))} {str(finding.get('description', ''))}").lower()
        for label, keywords in cls._SUBTYPE_KEYWORDS:
            if any(kw in combined for kw in keywords):
                return label
        return "General"

    def render(self) -> str:
        coc = self.data.coc_findings
        if not coc:
            return ""

        customers_affected = self.data.coc_customers_affected
        consent_required = self.data.consent_required_customers

        # Count subtypes for summary
        subtype_counts: dict[str, int] = {}
        for f in coc:
            st = self._detect_subtype(f)
            subtype_counts[st] = subtype_counts.get(st, 0) + 1

        parts: list[str] = [
            "<section class='report-section' id='sec-coc'>",
            "<h2>Change of Control Analysis</h2>",
        ]

        # Summary alert with subtype breakdown
        subtype_summary = ", ".join(f"{v} {k}" for k, v in sorted(subtype_counts.items()))
        dominant = max(subtype_counts, key=subtype_counts.get) if subtype_counts else ""  # type: ignore[arg-type]
        if dominant in ("Consent-Required", "Auto-Termination"):
            guidance = "Initiate customer outreach for consent-dependent contracts."
        elif dominant == "Notification":
            guidance = "Notification-only provisions are a routine administrative step."
        else:
            guidance = "Review consent requirements and assess impact on deal timeline."

        parts.append(
            self.render_alert(
                "high" if customers_affected > 5 else "info",
                f"{customers_affected} entities with change-of-control provisions",
                f"{len(coc)} change-of-control findings identified across "
                f"{customers_affected} entities ({subtype_summary}). "
                f"{consent_required} entities may require assignment consent. "
                f"{guidance}",
            )
        )

        # CoC findings by customer with Type column
        by_customer: dict[str, list[dict[str, Any]]] = {}
        for f in coc:
            cust = str(f.get("_customer_safe_name", f.get("_customer", "Unknown")))
            by_customer.setdefault(cust, []).append(f)

        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Type</th>"
            "<th scope='col'>Findings</th>"
            "<th scope='col'>Severity</th>"
            "<th scope='col'>Primary Issue</th>"
            "</tr></thead><tbody>"
        )

        for customer_csn, findings in sorted(by_customer.items(), key=lambda x: -len(x[1])):
            display_name = self.data.display_names.get(customer_csn, customer_csn) if self.data else customer_csn
            count = len(findings)
            max_sev = "P3"
            for f in findings:
                sev = f.get("severity", "P3")
                if sev < max_sev:
                    max_sev = sev
            primary = html.escape(str(findings[0].get("title", "")))
            subtype = html.escape(self._detect_subtype(findings[0]))
            parts.append(
                f"<tr><td><strong>{html.escape(display_name)}</strong></td>"
                f"<td>{subtype}</td>"
                f"<td>{count}</td>"
                f"<td>{self.severity_badge(max_sev)}</td>"
                f"<td>{primary}</td></tr>"
            )

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)


class TfCAnalysisRenderer(SectionRenderer):
    """Render the Termination for Convenience — Revenue Quality section."""

    def render(self) -> str:
        tfc = self.data.tfc_findings
        if not tfc:
            return ""

        customers_affected = self.data.tfc_customers_affected

        parts: list[str] = [
            "<section class='report-section' id='sec-tfc'>",
            "<h2>Termination for Convenience &mdash; Revenue Quality</h2>",
        ]

        # Valuation-framed alert (never critical/high — amber at most)
        parts.append(
            self.render_alert(
                "info",
                f"{customers_affected} entities with TfC clauses (valuation input)",
                f"{len(tfc)} termination-for-convenience findings across "
                f"{customers_affected} entities. "
                "TfC revenue is non-committed (at-risk ARR). "
                "Model as a valuation/RPO input — this is not a deal-blocker.",
            )
        )

        # TfC findings table
        by_customer: dict[str, list[dict[str, Any]]] = {}
        for f in tfc:
            cust = str(f.get("_customer_safe_name", f.get("_customer", "Unknown")))
            by_customer.setdefault(cust, []).append(f)

        parts.append(
            "<table class='customer-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Notice Period</th>"
            "<th scope='col'>Revenue Impact</th>"
            "<th scope='col'>Finding Detail</th>"
            "</tr></thead><tbody>"
        )

        for customer_csn, findings in sorted(by_customer.items(), key=lambda x: -len(x[1])):
            display_name = self.data.display_names.get(customer_csn, customer_csn) if self.data else customer_csn
            primary = findings[0]
            desc = str(primary.get("description", ""))
            # Best-effort notice period extraction
            notice = "—"
            desc_lower = desc.lower()
            for marker in ("notice", "day", "month"):
                if marker in desc_lower:
                    notice = html.escape(desc[:80])
                    break
            # Revenue impact from finding text
            revenue = "See valuation model"
            title_text = html.escape(str(primary.get("title", "")))
            parts.append(
                f"<tr><td><strong>{html.escape(display_name)}</strong></td>"
                f"<td>{notice}</td>"
                f"<td>{revenue}</td>"
                f"<td>{title_text}</td></tr>"
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
            cust = str(f.get("_customer_safe_name", f.get("_customer", "Unknown")))
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

        for customer_csn, findings in sorted(by_customer.items(), key=lambda x: -len(x[1])):
            display_name = self.data.display_names.get(customer_csn, customer_csn) if self.data else customer_csn
            max_sev = min((f.get("severity", "P3") for f in findings), default="P3")
            primary = html.escape(str(findings[0].get("title", "")))
            parts.append(
                f"<tr><td><strong>{html.escape(display_name)}</strong></td>"
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
