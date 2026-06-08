"""Atlas DD Analyst — an agno agent that answers questions about a completed
dd-agents due-diligence report.

No server is started here. ``cli.py`` imports ``agent`` for one-shot local runs;
``bindu_agent.py`` imports it to expose the agent over A2A.

The agent's tools read a deal's *already-produced* merged findings through the
upstream ``dd_agents.query`` finding index — pure, deterministic Python, no LLM
and no Anthropic key. The agno model (via OpenRouter) supplies the conversational
reasoning on top. The dd-agents pipeline itself is never run here.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from prompts import AGENT_DESCRIPTION, AGENT_NAME, SYSTEM_PROMPT

# Upstream library — available after `uv pip install -e .` at the repo root.
from dd_agents.query.indexer import FindingIndex, FindingIndexer

HERE = Path(__file__).parent.resolve()
REPO_ROOT = HERE.parent.parent.resolve()  # examples/agno-bindu -> repo root
# Default: the golden, 100%-synthetic "Project Atlas" report this repo already
# ships (real pipeline output, committed under docs/). Point DD_REPORT_DIR at any
# `dd-agents run` output directory (e.g. its runs/latest) to analyze a real deal.
DEFAULT_REPORT_DIR = REPO_ROOT / "docs" / "marketing" / "sample-report-atlas"

_QUOTE_PREVIEW = 240  # chars of an exact quote to show in compact list rows


def report_path() -> Path:
    """Resolve the report directory the analyst reads (env-overridable)."""
    return Path(os.getenv("DD_REPORT_DIR", str(DEFAULT_REPORT_DIR))).expanduser().resolve()


@lru_cache(maxsize=1)
def _index() -> FindingIndex:
    """Load and index the report's merged findings once (cached)."""
    return FindingIndexer().index_report(report_path())


def _first_citation(finding: dict, *, quote_chars: int | None = None) -> dict | None:
    citations = finding.get("citations") or []
    if not citations:
        return None
    c = citations[0]
    quote = c.get("exact_quote") or ""
    if quote_chars is not None and len(quote) > quote_chars:
        quote = quote[:quote_chars].rstrip() + "…"
    return {
        "source": c.get("source_path", ""),
        "location": c.get("location", ""),
        "quote": quote,
    }


def _row(finding: dict) -> dict:
    return {
        "id": finding.get("id", ""),
        "severity": finding.get("severity", ""),
        "domain": finding.get("agent", finding.get("domain", "")),
        "category": finding.get("category", ""),
        "title": finding.get("title", ""),
        "citation": _first_citation(finding, quote_chars=_QUOTE_PREVIEW),
    }


# --------------------------------------------------------------------------
# Tools (the agno model calls these; each returns a JSON string)
# --------------------------------------------------------------------------


def report_overview() -> str:
    """Summarize the loaded due-diligence report.

    Returns total findings, the severity breakdown (P0-P4, where P0 is a
    deal-stopper), per-domain counts across the nine specialist domains, and the
    list of finding categories present. Call this first to orient before drilling
    in. Takes no arguments.

    Returns:
        JSON string with report_dir, total_findings, summary, severity_counts,
        domain_counts, and categories.
    """
    idx = _index()
    if idx.total_findings == 0:
        return json.dumps(
            {
                "error": (
                    f"No findings found at {report_path()}. Set DD_REPORT_DIR to a "
                    "dd-agents run output directory (e.g. its runs/latest)."
                )
            }
        )
    return json.dumps(
        {
            "report_dir": str(report_path()),
            "total_findings": idx.total_findings,
            "summary": idx.summary,
            "severity_counts": {s: len(v) for s, v in sorted(idx.by_severity.items())},
            "domain_counts": {d: len(v) for d, v in sorted(idx.by_domain.items())},
            "categories": sorted(c for c in idx.by_category if c),
        }
    )


def list_findings(
    severity: str = "",
    domain: str = "",
    category: str = "",
    text: str = "",
    limit: int = 15,
) -> str:
    """List findings from the report, optionally filtered. All filters combine (AND).

    Args:
        severity: One of P0, P1, P2, P3, P4 (P0 = deal-stopper). Empty = any.
        domain: One of legal, finance, commercial, producttech, cybersecurity,
            hr, tax, regulatory, esg. Empty = any.
        category: Case-insensitive substring matched against the finding category.
        text: Case-insensitive substring matched against title + description.
        limit: Maximum rows to return (default 15).

    Returns:
        JSON string with the applied filters, the match count, and compact rows
        (id, severity, domain, category, title, one citation). Use get_finding
        for the full description and all exact quotes.
    """
    idx = _index()
    sev = severity.strip().upper()
    dom = domain.strip().lower()
    cat = category.strip().lower()
    needle = text.strip().lower()

    matches: list[dict] = []
    for f in idx.findings:
        if sev and str(f.get("severity", "")).upper() != sev:
            continue
        if dom and str(f.get("agent", f.get("domain", ""))).lower() != dom:
            continue
        if cat and cat not in str(f.get("category", "")).lower():
            continue
        if needle:
            haystack = f"{f.get('title', '')} {f.get('description', '')}".lower()
            if needle not in haystack:
                continue
        matches.append(f)

    try:
        cap = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        cap = 15

    return json.dumps(
        {
            "filters": {"severity": sev, "domain": dom, "category": category, "text": text},
            "match_count": len(matches),
            "returned": min(len(matches), cap),
            "findings": [_row(f) for f in matches[:cap]],
        }
    )


def get_finding(finding_id: str) -> str:
    """Return the full detail for a single finding by its id.

    Args:
        finding_id: The finding id (e.g. from a list_findings row).

    Returns:
        JSON string with severity, domain, category, title, the complete
        description, confidence, the analysis unit (deal subject), every citation
        (source document, section/location, full exact quote), and any
        cross-domain corroboration metadata. Returns an error if the id is
        unknown.
    """
    idx = _index()
    fid = (finding_id or "").strip()
    finding = next((f for f in idx.findings if f.get("id") == fid), None)
    if finding is None:
        return json.dumps(
            {
                "error": f"No finding with id {fid!r}.",
                "hint": "Use list_findings to get valid finding ids.",
            }
        )

    citations = [
        {
            "source": c.get("source_path", ""),
            "location": c.get("location", ""),
            "exact_quote": c.get("exact_quote") or "",
        }
        for c in (finding.get("citations") or [])
    ]
    meta = finding.get("metadata") or {}
    corroboration = {
        k: meta[k] for k in ("contributing_agents", "corroborated_by", "severity_disagreement") if meta.get(k)
    }
    return json.dumps(
        {
            "id": finding.get("id", ""),
            "severity": finding.get("severity", ""),
            "domain": finding.get("agent", finding.get("domain", "")),
            "category": finding.get("category", ""),
            "title": finding.get("title", ""),
            "description": finding.get("description", ""),
            "confidence": finding.get("confidence", ""),
            "subject": finding.get("analysis_unit", ""),
            "citations": citations,
            "corroboration": corroboration,
        }
    )


def _build_model() -> OpenRouter:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add it to your .env (see .env.example).")
    return OpenRouter(
        id=os.getenv("BINDU_AGENT_MODEL", "anthropic/claude-sonnet-4.5"),
        api_key=api_key,
        max_tokens=int(os.getenv("BINDU_AGENT_MAX_TOKENS", "4096")),
    )


def build_agent() -> Agent:
    return Agent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        instructions=SYSTEM_PROMPT,
        model=_build_model(),
        tools=[report_overview, list_findings, get_finding],
        markdown=True,
    )


agent: Agent = build_agent()
