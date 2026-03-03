"""Quality and methodology renderer (Issue #107)."""

from __future__ import annotations

import contextlib
import html

from dd_agents.reporting.html_base import SectionRenderer


class QualityRenderer(SectionRenderer):
    """Render the quality audit and governance metrics sections."""

    def render(self) -> str:
        parts: list[str] = []
        parts.append(self._render_governance_metrics())
        parts.append(self._render_quality_scores())
        return "\n".join(p for p in parts if p)

    def _render_governance_metrics(self) -> str:
        scores: list[tuple[str, float]] = []
        for csn, data in sorted(self.merged_data.items()):
            if not isinstance(data, dict):
                continue
            gov = data.get("governance_resolution_pct")
            if gov is not None:
                with contextlib.suppress(ValueError, TypeError):
                    scores.append((str(data.get("customer", csn)), float(gov)))

        if not scores:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-governance'>",
            "<h2>Governance Resolution</h2>",
        ]

        for name, pct in sorted(scores, key=lambda x: x[1]):
            color = "#28a745" if pct >= 90 else ("#ffc107" if pct >= 70 else "#dc3545")
            width = max(min(pct, 100), 0)
            parts.append(
                f"<div class='gov-bar-container'>"
                f"<span class='gov-label'>{html.escape(name)}</span>"
                f"<div style='flex:1;background:#e9ecef;border-radius:4px;height:20px'>"
                f"<div class='gov-bar' style='width:{width:.0f}%;background:{color}'></div>"
                f"</div>"
                f"<span class='gov-pct' style='color:{color}'>{pct:.0f}%</span>"
                f"</div>"
            )

        parts.append("</section>")
        return "\n".join(parts)

    def _render_quality_scores(self) -> str:
        run_metadata = self.config.get("_run_metadata")
        if not run_metadata or not isinstance(run_metadata, dict):
            return ""
        qs = run_metadata.get("quality_scores")
        if not qs:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-quality'>",
            "<h2>Quality Audit</h2>",
        ]

        if isinstance(qs, dict):
            agent_scores = qs.get("agent_scores", qs)
            if isinstance(agent_scores, dict):
                parts.append(
                    "<table class='sortable'><thead><tr>"
                    "<th scope='col'>Agent</th><th scope='col'>Score</th><th scope='col'>Details</th>"
                    "</tr></thead><tbody>"
                )
                for agent_name, score_data in sorted(agent_scores.items()):
                    if isinstance(score_data, dict):
                        score_val = score_data.get("score", score_data.get("overall", ""))
                        details = score_data.get("details", score_data.get("notes", ""))
                    else:
                        score_val = score_data
                        details = ""
                    parts.append(
                        f"<tr><td>{html.escape(str(agent_name))}</td>"
                        f"<td>{html.escape(str(score_val))}</td>"
                        f"<td>{html.escape(str(details))}</td></tr>"
                    )
                parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)
