"""Risk analysis renderer — heat map and risk visualization (Issue #102)."""

from __future__ import annotations

import html

from dd_agents.reporting.html_base import (
    DOMAIN_AGENTS,
    DOMAIN_COLORS,
    DOMAIN_DISPLAY,
    SectionRenderer,
)


class RiskRenderer(SectionRenderer):
    """Render the domain risk heatmap."""

    def render(self) -> str:
        parts: list[str] = [
            "<section class='report-section' id='sec-heatmap'>",
            "<h2>Domain Risk Heatmap</h2>",
            "<div class='heatmap'>",
        ]

        for domain in DOMAIN_AGENTS:
            sev = self.data.domain_severity.get(domain, {})
            risk = self.data.domain_risk_labels.get(domain, "Clean")
            risk_color = self.risk_color(risk)
            domain_color = DOMAIN_COLORS.get(domain, "#666")
            total = sum(sev.values())
            display = DOMAIN_DISPLAY.get(domain, domain)

            sev_str = html.escape(" | ".join(f"{k}:{v}" for k, v in sev.items() if v > 0) or "None")

            parts.append(
                f"<a href='#sec-domain-{html.escape(domain)}' style='text-decoration:none;color:inherit'>"
                f"<div class='heatmap-cell' style='border-top-color:{domain_color}'>"
                f"<div class='domain-name'>{html.escape(display)}</div>"
                f"<div class='domain-risk' style='color:{risk_color}'>{html.escape(risk)}</div>"
                f"<div class='domain-counts'>{total} findings ({sev_str})</div>"
                f"</div></a>"
            )

        parts.extend(["</div>", "</section>"])
        return "\n".join(parts)
