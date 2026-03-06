"""Red Flag Assessment renderer — single-page stoplight report (Issue #125).

Renders the output of the Red Flag Scanner agent as a visual assessment
with stoplight indicators (green/yellow/red), flag cards with severity
and confidence badges, and an overall recommendation.
"""

from __future__ import annotations

import html
from typing import Any

from dd_agents.agents.red_flag_scanner import CATEGORY_LABELS
from dd_agents.reporting.html_base import SectionRenderer

_SIGNAL_CONFIG: dict[str, dict[str, str]] = {
    "green": {
        "color": "#198754",
        "bg": "#d1e7dd",
        "icon": "&#10004;",
        "label": "No Deal-Killers Detected",
    },
    "yellow": {
        "color": "#856404",
        "bg": "#fff3cd",
        "icon": "&#9888;",
        "label": "Issues Require Investigation",
    },
    "red": {
        "color": "#842029",
        "bg": "#f8d7da",
        "icon": "&#9888;",
        "label": "Potential Deal-Killer Detected",
    },
}

_CONFIDENCE_COLORS: dict[str, str] = {
    "high": "#198754",
    "medium": "#fd7e14",
    "low": "#6c757d",
}


class RedFlagAssessmentRenderer(SectionRenderer):
    """Render the Red Flag Assessment section."""

    def render(self) -> str:
        scan_data = self._get_scan_data()
        if not scan_data:
            return ""

        signal = str(scan_data.get("overall_signal", "green"))
        recommendation = str(scan_data.get("recommendation", ""))
        flags: list[dict[str, Any]] = scan_data.get("flags", [])

        parts: list[str] = [
            "<section id='sec-red-flags' class='report-section'>",
            "<h2>Red Flag Assessment</h2>",
            self._render_stoplight(signal),
            self._render_recommendation(recommendation),
        ]

        if flags:
            parts.append(self._render_flags(flags))
        else:
            parts.append(
                "<p style='color:#198754;font-style:italic'>"
                "No red flags detected in quick scan. "
                "Full pipeline analysis recommended for comprehensive coverage.</p>"
            )

        parts.append("</section>")
        return "\n".join(parts)

    def _get_scan_data(self) -> dict[str, Any] | None:
        """Extract red flag scan data from computed data."""
        if not self.data:
            return None
        scan: dict[str, Any] | None = getattr(self.data, "red_flag_scan", None)
        if not scan or not isinstance(scan, dict):
            return None
        return scan

    def _render_stoplight(self, signal: str) -> str:
        """Render the stoplight indicator banner."""
        cfg = _SIGNAL_CONFIG.get(signal, _SIGNAL_CONFIG["green"])
        return (
            f"<div style='background:{cfg['bg']};color:{cfg['color']};"
            f"padding:16px 24px;border-radius:8px;margin:16px 0;"
            f"font-size:1.2em;font-weight:600;text-align:center'>"
            f"<span style='font-size:1.5em;margin-right:8px'>{cfg['icon']}</span>"
            f"{html.escape(cfg['label'])}"
            "</div>"
        )

    def _render_recommendation(self, recommendation: str) -> str:
        """Render the recommendation text."""
        if not recommendation:
            return ""
        return (
            f"<p style='font-size:1.05em;margin:12px 0'>"
            f"<strong>Recommendation:</strong> {html.escape(recommendation)}</p>"
        )

    def _render_flags(self, flags: list[dict[str, Any]]) -> str:
        """Render individual red flag cards."""
        parts: list[str] = ["<div style='margin-top:16px'>"]

        for flag in flags:
            parts.append(self._render_flag_card(flag))

        parts.append("</div>")
        return "\n".join(parts)

    def _render_flag_card(self, flag: dict[str, Any]) -> str:
        """Render a single red flag as a card."""
        title = html.escape(str(flag.get("title", "Unknown")))
        description = html.escape(str(flag.get("description", "")))
        category = str(flag.get("category", ""))
        severity = str(flag.get("severity", "P3"))
        confidence = str(flag.get("confidence", "low"))
        source = html.escape(str(flag.get("source_document", "")))
        action = html.escape(str(flag.get("recommended_action", "")))

        cat_label = html.escape(CATEGORY_LABELS.get(category, category.replace("_", " ").title()))

        sev_colors: dict[str, str] = {
            "P0": "#dc3545",
            "P1": "#fd7e14",
            "P2": "#ffc107",
            "P3": "#6c757d",
        }
        sev_color = sev_colors.get(severity, "#6c757d")
        conf_color = _CONFIDENCE_COLORS.get(confidence, "#6c757d")

        return (
            f"<div style='border:1px solid #dee2e6;border-left:4px solid {sev_color};"
            f"border-radius:4px;padding:12px 16px;margin-bottom:12px'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;"
            f"margin-bottom:8px'>"
            f"<strong style='font-size:1.05em'>{title}</strong>"
            f"<div>"
            f"<span style='background:{sev_color};color:#fff;padding:2px 8px;"
            f"border-radius:3px;font-size:0.8em;margin-right:4px'>{html.escape(severity)}</span>"
            f"<span style='background:{conf_color};color:#fff;padding:2px 8px;"
            f"border-radius:3px;font-size:0.8em'>{html.escape(confidence)}</span>"
            f"</div></div>"
            f"<div style='color:#6c757d;font-size:0.85em;margin-bottom:6px'>{cat_label}</div>"
            f"<p style='margin:6px 0'>{description}</p>"
            + (f"<div style='font-size:0.85em;color:#495057'><strong>Source:</strong> {source}</div>" if source else "")
            + (
                f"<div style='font-size:0.85em;color:#0d6efd;margin-top:4px'><strong>Action:</strong> {action}</div>"
                if action
                else ""
            )
            + "</div>"
        )
