"""Investment Committee (IC) memo generation (Issue #190).

Packages the synthesis dd-agents already computes into a distributable,
deterministic memo — no new LLM pass. The memo is *analysis used as a basis for
deliverables*, never a sign-off-ready document and never a replacement for
advisors (positioning guardrails enforced by a test).

Pure rendering: :func:`render_ic_memo` takes the already-computed
:class:`~dd_agents.reporting.computed_metrics.ReportComputedData` (plus the raw
deal config for the header) and returns Markdown. The CLI command computes the
data from a completed run via the same ``ReportDataComputer`` the HTML report
uses, writes Markdown + HTML, and can hand the HTML to ``export-pdf`` — so the
memo needs no new rendering dependency.

Assembled from existing structured output: deterministic Go/No-Go verdict,
executive synthesis key takeaways, top risks by severity (with cited evidence),
deterministic recommendations (action/owner/timeline), and a methodology +
limitations appendix.
"""

from __future__ import annotations

import html as _html
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dd_agents.reporting.computed_metrics import ReportComputedData

# Positioning guardrails — the memo must never imply it replaces advisors or is
# a final sign-off. A unit test asserts none of these appear in rendered output.
_FORBIDDEN_PHRASES: tuple[str, ...] = ("board-ready", "replaces advisors", "zero hallucinations")

_SEVERITY_LABEL: dict[str, str] = {"P0": "Critical", "P1": "High", "P2": "Medium", "P3": "Low"}


def _esc(text: Any) -> str:
    """Collapse to a single-line, markdown-safe string (for table cells)."""
    return str(text).replace("\n", " ").replace("|", "\\|").strip()


def _deal_header(deal_config: dict[str, Any] | None) -> list[str]:
    cfg = deal_config or {}
    buyer = (cfg.get("buyer") or {}).get("name", "") if isinstance(cfg.get("buyer"), dict) else ""
    target = (cfg.get("target") or {}).get("name", "") if isinstance(cfg.get("target"), dict) else ""
    deal = cfg.get("deal") or {}
    deal_type = deal.get("type", "") if isinstance(deal, dict) else ""

    lines = ["# Investment Committee Memo", ""]
    if target:
        lines.append(f"**Target:** {target}")
    if buyer:
        lines.append(f"**Acquirer:** {buyer}")
    if deal_type:
        lines.append(f"**Transaction type:** {deal_type}")
    lines.append("")
    lines.append(
        "> This memo is automated forensic analysis used as a **basis** for your team's "
        "deliverables. Every finding is traceable to a cited source. It accelerates — and "
        "does not replace — qualified legal, financial, tax, and regulatory advisors; humans make the decisions."
    )
    lines.append("")
    return lines


def _verdict_section(computed: ReportComputedData) -> list[str]:
    verdict = computed.verdict or {}
    signal = verdict.get("signal", "") or computed.deal_risk_label
    rationale = verdict.get("rationale", "")
    factors = verdict.get("contributing_factors", []) or []

    lines = ["## Recommendation (Go / No-Go)", ""]
    lines.append(f"**Signal:** {_esc(signal)}")
    lines.append(f"**Deal risk:** {_esc(computed.deal_risk_label)} (score {computed.deal_risk_score:.0f}/100)")
    if rationale:
        lines.append("")
        lines.append(_esc(rationale))
    if factors:
        lines.append("")
        lines.append("**Contributing factors:**")
        for f in factors[:8]:
            lines.append(f"- {_esc(f)}")
    lines.append("")
    return lines


def _key_takeaways_section(computed: ReportComputedData) -> list[str]:
    es = computed.executive_synthesis or {}
    takeaways = es.get("key_takeaways") or es.get("takeaways") or []
    if not isinstance(takeaways, list) or not takeaways:
        return []
    lines = ["## Key Takeaways", ""]
    for t in takeaways[:10]:
        text = t.get("text", "") if isinstance(t, dict) else t
        if str(text).strip():
            lines.append(f"- {_esc(text)}")
    lines.append("")
    return lines


def _top_risks_section(computed: ReportComputedData, *, max_risks: int = 15) -> list[str]:
    risks = computed.wolf_pack or []
    if not risks:
        return ["## Top Risks", "", "No P0/P1 risks were identified.", ""]

    lines = ["## Top Risks (by severity, with cited evidence)", ""]
    lines.append("| Severity | Entity | Finding | Cited evidence |")
    lines.append("| --- | --- | --- | --- |")
    for f in risks[:max_risks]:
        sev = str(f.get("severity", "P3"))
        sev_label = f"{sev} ({_SEVERITY_LABEL.get(sev, '')})".strip()
        subject = f.get("_subject") or f.get("_subject_safe_name") or ""
        title = f.get("title", "")
        citation = ""
        cits = f.get("citations") or []
        if isinstance(cits, list) and cits:
            c0 = cits[0]
            if isinstance(c0, dict):
                quote = c0.get("exact_quote", "")
                loc = c0.get("location") or c0.get("source_path") or ""
                citation = f"{quote} ({loc})" if quote else str(loc)
        lines.append(f"| {_esc(sev_label)} | {_esc(subject)} | {_esc(title)} | {_esc(citation)[:160]} |")
    lines.append("")
    return lines


def _recommendations_section(computed: ReportComputedData, *, max_recs: int = 20) -> list[str]:
    recs = computed.recommendations or []
    if not recs:
        return []
    lines = ["## Recommendations", "", "| Action | Owner | Timeline |", "| --- | --- | --- |"]
    for r in recs[:max_recs]:
        action = r.get("action", "")
        owner = r.get("owner", "")
        timeline = r.get("timeline", "")
        if str(action).strip():
            lines.append(f"| {_esc(action)} | {_esc(owner)} | {_esc(timeline)} |")
    lines.append("")
    return lines


def _appendix_section(computed: ReportComputedData) -> list[str]:
    return [
        "## Appendix — Methodology & Limitations",
        "",
        f"- Entities analyzed: {computed.subjects_analyzed}; findings extracted: {computed.total_findings}; "
        f"gaps identified: {computed.total_gaps}.",
        "- Findings are produced by specialist AI agents across the deal's domains, cross-referenced, "
        "and traced to an exact source quote; the pipeline halts rather than ship a claim it cannot ground.",
        "- This is analysis to accelerate your diligence — verify material findings with qualified advisors "
        "before acting. It is not a final, sign-off-ready deliverable.",
        "",
    ]


def render_ic_memo(computed: ReportComputedData, deal_config: dict[str, Any] | None = None) -> str:
    """Render a deterministic IC memo (Markdown) from computed report data.

    Pure + side-effect-free; same input → same output. Sections with no data are
    omitted so the memo stays clean for thin deals.
    """
    parts: list[str] = []
    parts += _deal_header(deal_config)
    parts += _verdict_section(computed)
    parts += _key_takeaways_section(computed)
    parts += _top_risks_section(computed)
    parts += _recommendations_section(computed)
    parts += _appendix_section(computed)
    memo = "\n".join(parts).rstrip() + "\n"

    # Guardrail self-check: never emit a forbidden positioning phrase. This is a
    # belt-and-suspenders runtime guard in addition to the unit test.
    lowered = memo.lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in lowered:  # pragma: no cover — defensive; prose above avoids these
            raise ValueError(f"IC memo contains a forbidden positioning phrase: {phrase!r}")
    return memo


def memo_to_html(memo_markdown: str, *, title: str = "Investment Committee Memo") -> str:
    """Wrap the memo Markdown in minimal self-contained HTML (no new dependency).

    Renders headings, tables, blockquotes, and lists with a tiny hand-rolled
    Markdown subset — enough for the memo's structure — so the result is a
    standalone file that ``dd-agents export-pdf`` can convert to PDF. Avoids
    pulling in a Markdown library to honor the minimal-deps rule.
    """
    body_lines: list[str] = []
    in_table = False
    in_list = False

    def _close_blocks() -> None:
        nonlocal in_list, in_table
        if in_list:
            body_lines.append("</ul>")
            in_list = False
        if in_table:
            body_lines.append("</table>")
            in_table = False

    for raw in memo_markdown.splitlines():
        line = raw.rstrip()
        if not line:
            _close_blocks()
            continue
        if line.startswith("# "):
            _close_blocks()
            body_lines.append(f"<h1>{_html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            _close_blocks()
            body_lines.append(f"<h2>{_html.escape(line[3:])}</h2>")
        elif line.startswith("> "):
            _close_blocks()
            body_lines.append(f"<blockquote>{_html.escape(line[2:])}</blockquote>")
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", " "} for c in cells):
                continue  # markdown table separator row
            first_row = not in_table
            if not in_table:
                if in_list:
                    body_lines.append("</ul>")
                    in_list = False
                body_lines.append("<table border='1' cellpadding='6' cellspacing='0'>")
                in_table = True
            tag = "th" if first_row else "td"  # first row of each table is the header
            row = "".join(f"<{tag}>{_html.escape(c)}</{tag}>" for c in cells)
            body_lines.append(f"<tr>{row}</tr>")
        elif line.startswith("- "):
            if in_table:
                body_lines.append("</table>")
                in_table = False
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append(f"<li>{_html.escape(line[2:])}</li>")
        else:
            _close_blocks()
            body_lines.append(f"<p>{_html.escape(line)}</p>")
    _close_blocks()

    style = (
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:900px;margin:2rem auto;"
        "padding:0 1rem;line-height:1.5;color:#1a1a2e} h1{border-bottom:2px solid #6366f1;padding-bottom:.3rem}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0} th{background:#f3f4f6;text-align:left}"
        "blockquote{border-left:4px solid #6366f1;margin:1rem 0;padding:.5rem 1rem;background:#f9fafb;color:#374151}"
    )
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title><style>{style}</style></head>"
        f"<body>{''.join(body_lines)}</body></html>"
    )
