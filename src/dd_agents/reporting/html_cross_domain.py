"""Cross-Domain Risk Correlation renderer (Issues #103, #189, #198).

Renders compound risk analysis across multiple domains:
- Connection cards with compound severity, narrative, and contributing findings
- Domain interaction matrix (pair-wise connection counts)
- Cross-domain trigger analysis from neurosymbolic pipeline
- Empty state handling

Compound severity escalation rules (Issue #198):
- 2×P2 in same entity across domains → escalate to P1
- P1 + P2 in same entity → escalate to P0
- 3+ domains flagging same entity → P1 minimum
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from dd_agents.reporting.html_base import (
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SEVERITY_COLORS,
    SectionRenderer,
)
from dd_agents.utils.constants import SEVERITY_P0, SEVERITY_P1, SEVERITY_P2

# Domain-pair narrative templates (deterministic, auditable)
_PAIR_NARRATIVES: dict[tuple[str, str], str] = {
    ("finance", "legal"): (
        "Financial exposure correlates with contractual obligations — "
        "verify indemnity caps and warranty provisions cover the identified risk"
    ),
    ("legal", "producttech"): (
        "IP and licensing terms intersect with technology implementation — "
        "confirm license scope matches actual product architecture and deployment"
    ),
    ("legal", "commercial"): (
        "Contract terms affect commercial viability — assess whether restrictive clauses impair go-to-market strategy"
    ),
    ("finance", "commercial"): (
        "Revenue quality issues compound commercial risk — "
        "validate pipeline assumptions against actual financial performance"
    ),
    ("legal", "hr"): (
        "Employment-related legal obligations create retention risk — "
        "review change-of-control provisions in key employee agreements"
    ),
    ("finance", "tax"): (
        "Financial structure creates tax exposure — assess whether identified positions are adequately reserved"
    ),
    ("legal", "regulatory"): (
        "Regulatory compliance intersects with contractual obligations — "
        "confirm that license conditions satisfy applicable regulatory requirements"
    ),
    ("cybersecurity", "regulatory"): (
        "Data security gaps create regulatory exposure — "
        "assess GDPR/CCPA compliance implications of identified vulnerabilities"
    ),
    ("commercial", "producttech"): (
        "Product capabilities affect commercial commitments — verify that roadmap obligations are technically feasible"
    ),
    ("finance", "hr"): (
        "Compensation structures create retention risk — assess golden parachute and earn-out cost implications"
    ),
}


def _get_pair_narrative(domains: list[str]) -> str:
    """Get a deterministic narrative for a domain pair/group."""
    if len(domains) < 2:
        return ""
    for i in range(len(domains)):
        for j in range(i + 1, len(domains)):
            sorted_pair = sorted([domains[i], domains[j]])
            pair: tuple[str, str] = (sorted_pair[0], sorted_pair[1])
            narrative = _PAIR_NARRATIVES.get(pair)
            if narrative:
                return narrative
    return (
        f"Findings across {len(domains)} domains indicate systemic risk — "
        f"coordinate cross-functional review to assess compound impact"
    )


def _compute_compound_severity(
    severities: list[str],
    domain_count: int,
) -> str:
    """Compute escalated compound severity.

    Rules:
    - 2×P2 across domains → P1
    - P1 + P2 → P0
    - 3+ domains → P1 minimum
    """
    p0_count = severities.count(SEVERITY_P0)
    p1_count = severities.count(SEVERITY_P1)
    p2_count = severities.count(SEVERITY_P2)

    if p0_count > 0:
        return SEVERITY_P0

    if p1_count > 0 and p2_count > 0:
        return SEVERITY_P0

    if domain_count >= 3:
        return SEVERITY_P1

    if p2_count >= 2:
        return SEVERITY_P1

    if p1_count > 0:
        return SEVERITY_P1

    return SEVERITY_P2


class CrossDomainRenderer(SectionRenderer):
    """Render Cross-Domain Risk Correlation section (enhanced Issue #198)."""

    def render(self) -> str:
        risks: list[dict[str, Any]] = getattr(self.data, "cross_domain_risks", [])
        triggers: list[dict[str, Any]] = getattr(self.data, "cross_domain_triggers", [])
        if not risks and not triggers:
            return ""

        parts: list[str] = [
            "<section id='sec-cross-domain' class='report-section'>",
            "<h2>Cross-Domain Risk Correlation</h2>",
        ]

        if risks:
            self._render_connection_cards(parts, risks)
            self._render_interaction_matrix(parts, risks)

        if triggers:
            self._render_trigger_analysis(parts, triggers)

        if not risks:
            parts.append("<div class='text-muted' style='padding:16px'>No cross-domain correlations identified.</div>")

        parts.append("</section>")
        return "\n".join(parts)

    def _render_connection_cards(self, parts: list[str], risks: list[dict[str, Any]]) -> None:
        """Render connection cards with compound severity, narrative, and domains."""
        parts.append("<h3>Compound Risk Connections</h3>")

        for risk in risks[:10]:
            csn = str(risk.get("entity", ""))
            display = self.data.display_names.get(csn, csn) if self.data else csn
            domains: list[str] = risk.get("domains", [])
            finding_count = int(risk.get("finding_count", 0))
            has_p0 = risk.get("has_p0", False)
            domain_count = int(risk.get("domain_count", len(domains)))

            # Compute compound severity from individual finding severities
            # Use available data to approximate severities list
            sevs: list[str] = []
            if has_p0:
                sevs.append(SEVERITY_P0)
            sevs.extend([SEVERITY_P1] * max(0, finding_count - (1 if has_p0 else 0)))
            compound_sev = _compute_compound_severity(sevs, domain_count)

            sev_color = SEVERITY_COLORS.get(compound_sev, "#6c757d")
            narrative = _get_pair_narrative(domains)

            # Render card
            parts.append(
                f"<div class='cross-domain-card' style='border-left-color:{sev_color}' "
                f"data-severity='{self.escape(compound_sev)}' "
                f"data-domain='{self.escape(domains[0]) if domains else ''}'>"
            )

            # Header
            parts.append(
                f"<div class='cross-domain-card-header'>"
                f"<span class='severity-badge' style='background:{sev_color}'>"
                f"{self.escape(compound_sev)}</span> "
                f"<strong>{self.escape(display)}</strong>"
                f"<span class='text-small text-muted' style='margin-left:auto'>"
                f"{finding_count} findings across {domain_count} domains</span>"
                f"</div>"
            )

            # Domain pills
            parts.append("<div class='cross-domain-pills'>")
            for d in domains:
                d_display = DOMAIN_DISPLAY.get(d, d.capitalize())
                d_color = DOMAIN_COLORS.get(d, "#333")
                parts.append(
                    f"<span class='domain-pill' style='border-color:{d_color};color:{d_color}'>"
                    f"{self.escape(d_display)}</span>"
                )
            parts.append("</div>")

            # Narrative
            if narrative:
                parts.append(f"<div class='cross-domain-narrative'>{self.escape(narrative)}</div>")

            parts.append("</div>")

    def _render_interaction_matrix(self, parts: list[str], risks: list[dict[str, Any]]) -> None:
        """Render domain interaction matrix showing pair-wise connection counts."""
        # Build pair counts
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for risk in risks:
            domains: list[str] = risk.get("domains", [])
            for i in range(len(domains)):
                for j in range(i + 1, len(domains)):
                    sp = sorted([domains[i], domains[j]])
                    pair_typed: tuple[str, str] = (sp[0], sp[1])
                    pair_counts[pair_typed] += 1

        if not pair_counts:
            return

        active_domains = sorted({d for pair in pair_counts for d in pair})
        if len(active_domains) < 2:
            return

        parts.append("<h3>Domain Interaction Matrix</h3>")
        parts.append("<table class='subject-table sortable'><thead><tr><th scope='col'></th>")
        for d in active_domains:
            d_display = DOMAIN_DISPLAY.get(d, d.capitalize())
            parts.append(f"<th scope='col'>{self.escape(d_display)}</th>")
        parts.append("</tr></thead><tbody>")

        for d1 in active_domains:
            d1_display = DOMAIN_DISPLAY.get(d1, d1.capitalize())
            parts.append(f"<tr><td style='font-weight:600'>{self.escape(d1_display)}</td>")
            for d2 in active_domains:
                if d1 == d2:
                    parts.append("<td style='background:#f0f0f0'>—</td>")
                else:
                    sp = sorted([d1, d2])
                    pair_key: tuple[str, str] = (sp[0], sp[1])
                    count = pair_counts.get(pair_key, 0)
                    bg = f"background:{SEVERITY_COLORS[SEVERITY_P0]}22" if count >= 3 else ""
                    parts.append(f"<td style='{bg}'>{count if count > 0 else ''}</td>")
            parts.append("</tr>")

        parts.append("</tbody></table>")

    def _render_trigger_analysis(self, parts: list[str], triggers: list[dict[str, Any]]) -> None:
        """Render the cross-domain trigger analysis results (Issue #189)."""
        parts.append("<h3>Cross-Domain Verification</h3>")
        parts.append(
            "<p>The following cross-domain verifications were automatically triggered "
            "when specialist agents identified findings requiring validation by other domains.</p>"
        )
        parts.append(
            "<table class='subject-table sortable'><thead><tr>"
            "<th scope='col'>Entity</th>"
            "<th scope='col'>Source</th>"
            "<th scope='col'>Target</th>"
            "<th scope='col'>Type</th>"
            "<th scope='col'>Priority</th>"
            "</tr></thead><tbody>"
        )
        for trigger in triggers[:20]:
            subject = self.escape(str(trigger.get("subject", "")))
            source = self.escape(str(trigger.get("source_agent", "")))
            target = self.escape(str(trigger.get("target_agent", "")))
            ttype = self.escape(str(trigger.get("trigger_type", "")))
            priority = str(trigger.get("priority", ""))
            badge = self.severity_badge(priority)
            parts.append(
                f"<tr><td>{subject}</td><td>{source}</td><td>{target}</td><td>{ttype}</td><td>{badge}</td></tr>"
            )
        parts.append("</tbody></table>")


# ---------------------------------------------------------------------------
# CSS for cross-domain cards
# ---------------------------------------------------------------------------

CROSS_DOMAIN_CSS = """
/* Cross-Domain Cards (Issue #198) */
.cross-domain-card { background: var(--bg-secondary); border-left: 5px solid; border-radius: 4px 8px 8px 4px;
                     padding: 16px 20px; margin-bottom: 12px; box-shadow: var(--shadow-sm); }
.cross-domain-card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
                            flex-wrap: wrap; }
.cross-domain-pills { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.domain-pill { border: 1.5px solid; border-radius: 12px; padding: 2px 10px;
               font-size: 0.78em; font-weight: 600; }
.cross-domain-narrative { font-size: 0.88em; color: var(--text-secondary); line-height: 1.5;
                          padding: 8px 12px; background: var(--bg-hover); border-radius: 4px; }
"""
