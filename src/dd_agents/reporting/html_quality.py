"""Quality and methodology renderer (Issue #107)."""

from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.html_base import SectionRenderer

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class QualityRenderer(SectionRenderer):
    """Render the quality audit, governance metrics, and audit check results."""

    def __init__(
        self,
        data: Any,
        merged_data: dict[str, Any],
        config: dict[str, Any] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(data, merged_data, config)
        self._run_dir = run_dir

    def render(self) -> str:
        parts: list[str] = []
        parts.append(self._render_governance_metrics())
        parts.append(self._render_quality_scores())
        parts.append(self._render_audit_checks())
        return "\n".join(p for p in parts if p)

    def _render_governance_metrics(self) -> str:
        scores: list[tuple[str, float]] = []
        for csn, data in sorted(self.merged_data.items()):
            if not isinstance(data, dict):
                continue
            gov = data.get("governance_resolution_pct")
            if gov is not None:
                with contextlib.suppress(ValueError, TypeError):
                    name = (
                        self.data.display_names.get(csn, str(data.get("subject", csn)))
                        if self.data
                        else str(data.get("subject", csn))
                    )
                    scores.append((name, float(gov)))

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
                f"<span class='gov-label'>{self.escape(name)}</span>"
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
                        f"<tr><td>{self.escape(str(agent_name))}</td>"
                        f"<td>{self.escape(str(score_val))}</td>"
                        f"<td>{self.escape(str(details))}</td></tr>"
                    )
                parts.append("</tbody></table>")

        parts.append("</section>")
        return "\n".join(parts)

    def _render_audit_checks(self) -> str:
        """Render audit.json QA check results with pass/fail badges."""
        audit = self._load_audit()
        if audit is None:
            return ""

        checks = audit.get("checks", [])
        if not checks:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-audit-checks'>",
            "<h2>QA Audit Checks</h2>",
            "<table class='sortable'><thead><tr>"
            "<th scope='col'>Check</th><th scope='col'>Status</th><th scope='col'>Detail</th>"
            "</tr></thead><tbody>",
        ]

        for check in checks:
            if not isinstance(check, dict):
                continue
            name = self.escape(str(check.get("name", "")))
            status = str(check.get("status", "")).lower()
            detail = self.escape(str(check.get("detail", "")))

            if status == "pass":
                badge = "<span class='verification-badge vb-verified'>pass</span>"
            elif status == "fail":
                badge = "<span class='verification-badge vb-failed'>fail</span>"
            else:
                badge = f"<span class='verification-badge vb-unchecked'>{self.escape(status)}</span>"

            parts.append(f"<tr><td>{name}</td><td>{badge}</td><td>{detail}</td></tr>")

        parts.append("</tbody></table>")
        parts.append("</section>")
        return "\n".join(parts)

    def _load_audit(self) -> dict[str, Any] | None:
        """Load audit.json from the run directory."""
        if self._run_dir is None:
            return None
        audit_path = self._run_dir / "report" / "audit.json"
        if not audit_path.exists():
            return None
        try:
            return json.loads(audit_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load audit.json from %s", audit_path)
            return None
