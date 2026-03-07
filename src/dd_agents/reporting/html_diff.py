"""Report diff renderer — run-over-run changes (new/resolved/changed findings)."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from dd_agents.reporting.html_base import SectionRenderer

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class DiffRenderer(SectionRenderer):
    """Render the run-over-run diff section from ``report_diff.json``.

    Only rendered when diff data exists (incremental runs).
    """

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
        diff = self._load_diff()
        if diff is None:
            return ""

        summary = diff.get("summary", {})
        changes = diff.get("changes", [])
        new_count = summary.get("new_findings", 0)
        resolved_count = summary.get("resolved_findings", 0)
        changed_count = summary.get("changed_severity", 0)

        parts: list[str] = [
            "<section class='report-section' id='sec-diff'>",
            "<h2>Run-over-Run Changes</h2>",
        ]

        # Summary cards
        parts.append(
            "<div class='metrics-strip'>"
            f"<div class='metric-card'><div class='value' style='color:#dc3545'>{new_count}</div>"
            "<div class='label'>New Findings</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#28a745'>{resolved_count}</div>"
            "<div class='label'>Resolved</div></div>"
            f"<div class='metric-card'><div class='value' style='color:#ffc107'>{changed_count}</div>"
            "<div class='label'>Changed Severity</div></div>"
            "</div>"
        )

        # New findings table
        new_findings = [c for c in changes if c.get("change_type") == "new_finding"]
        if new_findings:
            parts.append("<h3>New Findings</h3>")
            parts.append(self._render_change_table(new_findings))

        # Resolved findings table
        resolved = [c for c in changes if c.get("change_type") == "resolved_finding"]
        if resolved:
            parts.append("<h3>Resolved Findings</h3>")
            parts.append(self._render_change_table(resolved))

        # Severity changes table
        severity_changes = [c for c in changes if c.get("change_type") == "changed_severity"]
        if severity_changes:
            parts.append("<h3>Severity Changes</h3>")
            parts.append(self._render_severity_change_table(severity_changes))

        parts.append("</section>")
        return "\n".join(parts)

    def _load_diff(self) -> dict[str, Any] | None:
        """Load report_diff.json from the run directory."""
        if self._run_dir is None:
            return None
        diff_path = self._run_dir / "report" / "report_diff.json"
        if not diff_path.exists():
            return None
        try:
            return json.loads(diff_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load report_diff.json from %s", diff_path)
            return None

    def _render_change_table(self, changes: list[dict[str, Any]]) -> str:
        parts: list[str] = [
            "<table class='sortable'><thead><tr>"
            "<th scope='col'>Entity</th><th scope='col'>Finding</th>"
            "</tr></thead><tbody>"
        ]
        for c in changes:
            raw_customer = str(c.get("customer", ""))
            customer = self.escape(
                self.data.display_names.get(raw_customer, raw_customer) if self.data else raw_customer
            )
            summary = self.escape(str(c.get("finding_summary", "")))
            parts.append(f"<tr><td>{customer}</td><td>{summary}</td></tr>")
        parts.append("</tbody></table>")
        return "\n".join(parts)

    def _render_severity_change_table(self, changes: list[dict[str, Any]]) -> str:
        parts: list[str] = [
            "<table class='sortable'><thead><tr>"
            "<th scope='col'>Entity</th><th scope='col'>Finding</th>"
            "<th scope='col'>Prior</th><th scope='col'>Current</th>"
            "</tr></thead><tbody>"
        ]
        for c in changes:
            raw_customer = str(c.get("customer", ""))
            customer = self.escape(
                self.data.display_names.get(raw_customer, raw_customer) if self.data else raw_customer
            )
            summary = self.escape(str(c.get("finding_summary", "")))
            prior = self.escape(str(c.get("prior_severity", "")))
            current = self.escape(str(c.get("current_severity", "")))
            parts.append(f"<tr><td>{customer}</td><td>{summary}</td><td>{prior}</td><td>{current}</td></tr>")
        parts.append("</tbody></table>")
        return "\n".join(parts)
