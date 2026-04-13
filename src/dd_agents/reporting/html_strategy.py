"""Buyer strategy renderer — conditional buyer-specific analysis (Issue #111).

This section is ONLY rendered when ``config.buyer_strategy`` is present.
All buyer-specific content is exclusively here — no other renderer
contains buyer-contextualized interpretation.
"""

from __future__ import annotations

from dd_agents.reporting.html_base import SectionRenderer


def _normalize_for_match(s: str) -> str:
    """Normalize a category or focus area string for substring matching.

    Strips whitespace, ampersands, and collapses underscores so that
    canonical names like ``"IP & Ownership"`` match focus areas like
    ``"ip_ownership"``.
    """
    return s.lower().replace(" ", "_").replace("&", "").replace("__", "_").strip("_")


class StrategyRenderer(SectionRenderer):
    """Render the optional buyer strategy section."""

    def render(self) -> str:
        buyer_strategy = self.data.buyer_strategy
        if not buyer_strategy:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-strategy'>",
            "<h2>Buyer Strategy Analysis</h2>",
        ]

        # Acquisition thesis
        thesis = buyer_strategy.get("thesis", "")
        if thesis:
            parts.append(
                f"<div class='metric-card'>"
                f"<div class='label'>Acquisition Thesis</div>"
                f"<div style='text-align:left;padding:8px'>{self.escape(thesis)}</div>"
                f"</div>"
            )

        # Key synergies
        synergies = buyer_strategy.get("key_synergies", [])
        if synergies:
            parts.append("<h3>Expected Synergies</h3><ul>")
            for s in synergies:
                parts.append(f"<li>{self.escape(str(s))}</li>")
            parts.append("</ul>")

        # Integration priorities
        priorities = buyer_strategy.get("integration_priorities", [])
        if priorities:
            parts.append("<h3>Integration Priorities</h3><ol>")
            for p in priorities:
                parts.append(f"<li>{self.escape(str(p))}</li>")
            parts.append("</ol>")

        # Risk tolerance
        tolerance = buyer_strategy.get("risk_tolerance", "")
        if tolerance:
            color = {"conservative": "#28a745", "moderate": "#ffc107", "aggressive": "#dc3545"}.get(
                tolerance, "#6c757d"
            )
            parts.append(
                f"<div class='mb-8'>Risk Tolerance: "
                f"<strong style='color:{color}'>{self.escape(tolerance)}</strong></div>"
            )

        # Focus areas
        focus = buyer_strategy.get("focus_areas", [])
        if focus:
            parts.append("<h3>Buyer Focus Areas</h3><ul>")
            for f in focus:
                parts.append(f"<li>{self.escape(str(f))}</li>")
            parts.append("</ul>")

        # Risk alignment summary (findings in buyer focus areas)
        if focus and self.data.findings_by_category:
            relevant_findings = 0
            for cat, findings in self.data.findings_by_category.items():
                cat_norm = _normalize_for_match(cat)
                if any(_normalize_for_match(fa) in cat_norm or cat_norm in _normalize_for_match(fa) for fa in focus):
                    relevant_findings += len(findings)
            if relevant_findings > 0:
                parts.append(
                    f"<div class='metric-card'>"
                    f"<div class='value' style='color:#dc3545'>{relevant_findings}</div>"
                    f"<div class='label'>Findings in Buyer Focus Areas</div>"
                    f"</div>"
                )

        # Acquirer intelligence (if available from #110)
        acq_intel = self.data.acquirer_intelligence
        if acq_intel and isinstance(acq_intel, dict):
            parts.append("<h3>AI-Enhanced Acquirer Analysis</h3>")
            summary = acq_intel.get("summary", "")
            if summary:
                parts.append(f"<p>{self.escape(str(summary))}</p>")
            recommendations = acq_intel.get("recommendations", [])
            if recommendations:
                parts.append("<ul>")
                for r in recommendations:
                    parts.append(f"<li>{self.escape(str(r))}</li>")
                parts.append("</ul>")

        parts.append("</section>")
        return "\n".join(parts)
