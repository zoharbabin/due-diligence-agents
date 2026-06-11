"""Data-room completeness + model-integrity renderer (Issue #238).

Surfaces two deterministic, pre-computed artifacts that otherwise never reach
the deliverable — they only lived in ``assess`` output, an inventory JSON, or
the agent's prompt:

1. **Request-list completeness** (``inventory/request_list.json``, Issue #192) —
   received vs. missing-required vs. missing-optional expected documents, plus
   the count of unexpected files.
2. **Model-integrity audit** (``inventory/formula_audit.json``, Issue #194) —
   spreadsheet formula issues (hardcoded overrides, circular refs, ``#REF!``,
   broken external links) citing an exact ``file → Sheet!Cell``, independent of
   whether the Finance agent also flagged them.

Both are sourced from the persisted run metadata (mirrors how
``MethodologyRenderer`` reads ``_run_metadata``). Parity-safe: the section
renders nothing when neither artifact is present (a generic room adds nothing).
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.html_base import SectionRenderer

# Human labels for the machine ``kind`` keys emitted by formula_audit.
_KIND_LABELS: dict[str, str] = {
    "hardcoded_override": "Hardcoded override",
    "circular_reference": "Circular reference",
    "error_literal": "Error literal (e.g. #REF!)",
    "broken_external_link": "Broken external link",
}


class CompletenessRenderer(SectionRenderer):
    """Render request-list completeness + model-integrity audit sub-sections."""

    def render(self) -> str:
        run_meta = (self.config or {}).get("_run_metadata") or {}
        if not isinstance(run_meta, dict):
            return ""
        request_list = run_meta.get("request_list")
        formula_audit = run_meta.get("formula_audit")

        body: list[str] = []
        if isinstance(request_list, dict) and request_list:
            body.append(self._render_request_list(request_list))
        if isinstance(formula_audit, dict) and formula_audit.get("files_with_formulas"):
            body.append(self._render_formula_audit(formula_audit))

        body = [b for b in body if b]
        if not body:
            return ""

        parts: list[str] = [
            "<section class='report-section' id='sec-completeness'>",
            "<h2>Data-Room Completeness &amp; Model Integrity</h2>",
            *body,
            "</section>",
        ]
        return "\n".join(parts)

    # -- Request-list completeness (Issue #192) ------------------------------

    def _render_request_list(self, rl: dict[str, Any]) -> str:
        received = [str(c) for c in rl.get("received", []) if c]
        missing_required = [str(c) for c in rl.get("missing_required", []) if c]
        missing_optional = [str(c) for c in rl.get("missing_optional", []) if c]
        unexpected = int(rl.get("unexpected_count", 0) or 0)
        summary = str(rl.get("summary", "")).strip()

        parts: list[str] = [
            "<div class='domain-section'>",
            "<div class='domain-header' tabindex='0' role='button' aria-expanded='true'"
            " style='border-left-color: var(--blue)'>",
            "<h2>Request-List Completeness</h2>",
            "<span class='arrow open'>&#9654;</span></div>",
            "<div class='domain-body open'>",
        ]
        if summary:
            # render_alert already escapes — pass raw text. Missing-required is a
            # gap (critical framing); otherwise informational.
            level = "high" if missing_required else "info"
            parts.append(self.render_alert(level, "Completeness", summary))

        parts.append(
            "<table class='subject-table sortable'><caption>Requested-document reconciliation</caption>"
            "<thead><tr><th scope='col'>Status</th><th scope='col'>Count</th>"
            "<th scope='col'>Items</th></tr></thead><tbody>"
        )
        parts.append(self._rl_row("Received", received))
        parts.append(self._rl_row("Missing — required", missing_required))
        parts.append(self._rl_row("Missing — optional", missing_optional))
        parts.append(
            f"<tr><td>Unexpected files</td><td>{unexpected}</td>"
            "<td class='text-muted'>Files present but not on the request list (informational)</td></tr>"
        )
        parts.append("</tbody></table>")
        parts.append("</div></div>")
        return "".join(parts)

    def _rl_row(self, label: str, items: list[str]) -> str:
        joined = ", ".join(self.escape(i) for i in items) if items else "<span class='text-muted'>—</span>"
        return f"<tr><td>{self.escape(label)}</td><td>{len(items)}</td><td>{joined}</td></tr>"

    # -- Model-integrity audit (Issue #194) ----------------------------------

    def _render_formula_audit(self, fa: dict[str, Any]) -> str:
        total = int(fa.get("total_issues", 0) or 0)
        files_with_formulas = int(fa.get("files_with_formulas", 0) or 0)
        files_with_issues = int(fa.get("files_with_issues", 0) or 0)
        by_kind = fa.get("by_kind") or {}
        issues = fa.get("issues") or []
        truncated = bool(fa.get("truncated"))

        # Collapsed by default — supplementary integrity evidence.
        parts: list[str] = [
            "<div class='domain-section'>",
            "<div class='domain-header' tabindex='0' role='button' aria-expanded='false'"
            " style='border-left-color: var(--orange)'>",
            f"<h2>Model Integrity ({total})</h2>",
            "<span class='arrow'>&#9654;</span></div>",
            "<div class='domain-body'>",
        ]

        if total == 0:
            parts.append(
                self.render_alert(
                    "good",
                    "Model integrity",
                    f"No formula-integrity issues detected across {files_with_formulas} spreadsheet(s) with formulas.",
                )
            )
            parts.append("</div></div>")
            return "".join(parts)

        parts.append(
            self.render_alert(
                "high",
                "Model integrity",
                f"{total} potential issue(s) across {files_with_issues} of {files_with_formulas} "
                "spreadsheet(s) with formulas. Each cites an exact cell — verify before relying on the model.",
            )
        )

        if isinstance(by_kind, dict) and by_kind:
            kind_bits = ", ".join(
                f"{self.escape(_KIND_LABELS.get(str(k), str(k)))}: {v}" for k, v in sorted(by_kind.items())
            )
            parts.append(f"<p><strong>By type:</strong> {kind_bits}</p>")

        parts.append(
            "<table class='subject-table sortable'><caption>Formula-integrity issues</caption>"
            "<thead><tr><th scope='col'>File</th><th scope='col'>Cell</th>"
            "<th scope='col'>Type</th><th scope='col'>Detail</th></tr></thead><tbody>"
        )
        for row in issues:
            if not isinstance(row, dict):
                continue
            file = self.escape(str(row.get("file", "")))
            sheet = str(row.get("sheet", ""))
            cell = str(row.get("cell", ""))
            location = self.escape(f"{sheet}!{cell}" if sheet else cell)
            kind = self.escape(_KIND_LABELS.get(str(row.get("kind", "")), str(row.get("kind", ""))))
            detail = self.escape(str(row.get("detail", "")))
            parts.append(f"<tr><td>{file}</td><td>{location}</td><td>{kind}</td><td>{detail}</td></tr>")
        parts.append("</tbody></table>")
        if truncated:
            parts.append("<p class='text-muted'>Note: issue list truncated to a bounded cap.</p>")
        parts.append("</div></div>")
        return "".join(parts)
