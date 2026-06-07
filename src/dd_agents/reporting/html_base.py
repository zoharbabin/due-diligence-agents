"""Base class, constants, CSS, JS, and shared helpers for HTML report renderers.

Every section renderer inherits ``SectionRenderer`` and calls shared helpers
for severity badges, bar charts, finding cards, citations, alert boxes,
and HTML escaping.  CSS and JS live here as the single source of truth.

Issue #113: CSS variables, sidebar navigation with scroll tracking,
alert box components, two-column layouts, progressive disclosure,
confidential badge, RAG indicators, and WCAG 2.1 AA compliance.
"""

from __future__ import annotations

import html as _html
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from dd_agents.agents.registry import AgentRegistry
from dd_agents.utils.constants import (
    ALL_SEVERITIES,
    SEVERITY_P0,
    SEVERITY_P1,
    SEVERITY_P2,
    SEVERITY_P3,
)

if TYPE_CHECKING:
    from dd_agents.reporting.computed_metrics import ReportComputedData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (shared across all renderers)
# ---------------------------------------------------------------------------

SEVERITY_COLORS: dict[str, str] = {
    "P0": "#dc3545",
    "P1": "#fd7e14",
    "P2": "#ffc107",
    "P3": "#6c757d",
}

SEVERITY_BG: dict[str, str] = {
    "P0": "#fff5f5",
    "P1": "#fff8f0",
    "P2": "#fffdf0",
    "P3": "#f8f9fa",
}

SEVERITY_LABELS: dict[str, str] = {
    "P0": "Critical",
    "P1": "High",
    "P2": "Medium",
    "P3": "Low",
}


def _get_domain_agents() -> list[str]:
    """Return specialist agent names from the registry.

    Always queries the registry so that external agents registered via
    entry_points after initial import are included.
    """
    return AgentRegistry.all_specialist_names()


def get_domain_agents() -> list[str]:
    """Public API — return current specialist agent names from the registry."""
    return _get_domain_agents()


# Backward-compatible module-level snapshot.  New code should call
# ``get_domain_agents()`` to pick up late-registered external agents.
DOMAIN_AGENTS: list[str] = _get_domain_agents()

DOMAIN_DISPLAY: dict[str, str] = {
    "legal": "Legal",
    "finance": "Finance",
    "commercial": "Commercial",
    "producttech": "Product & Tech",
    "cybersecurity": "Cybersecurity",
    "hr": "HR / People",
    "tax": "Tax",
    "regulatory": "Regulatory",
    "esg": "ESG",
}

DOMAIN_COLORS: dict[str, str] = {
    "legal": "#4a90d9",
    "finance": "#2d8a4e",
    "commercial": "#7c3aed",
    "producttech": "#d97706",
    "cybersecurity": "#8B5CF6",
    "hr": "#c2185b",
    "tax": "#00838f",
    "regulatory": "#6a1b9a",
    "esg": "#2d6a4f",
}

RAG_COLORS: dict[str, str] = {
    "red": "#dc3545",
    "amber": "#fd7e14",
    "green": "#28a745",
}

TIMELINE_COLORS: dict[str, str] = {
    "Immediate": "#dc3545",
    "Pre-Close": "#fd7e14",
    "Valuation": "#9333ea",
    "Post-Close": "#4a90d9",
    "Positive": "#28a745",
}


def fmt_currency(amount: float) -> str:
    """Format a dollar amount for display (shared across renderers)."""
    sign = "-" if amount < 0 else ""
    abs_amt = abs(amount)
    if abs_amt >= 1_000_000:
        return f"{sign}${abs_amt / 1_000_000:.1f}M"
    if abs_amt >= 1_000:
        return f"{sign}${abs_amt / 1_000:.0f}K"
    return f"{sign}${abs_amt:,.0f}"


# ---------------------------------------------------------------------------
# SectionRenderer ABC
# ---------------------------------------------------------------------------


class SectionRenderer(ABC):
    """Abstract base class for all HTML report section renderers."""

    def __init__(
        self, data: ReportComputedData, merged_data: dict[str, Any], config: dict[str, Any] | None = None
    ) -> None:
        self.data = data
        self.merged_data = merged_data
        self.config = config or {}

    @abstractmethod
    def render(self) -> str:
        """Return HTML string for this section."""

    # -- Shared helpers -------------------------------------------------------

    @staticmethod
    def escape(text: str) -> str:
        """HTML-escape a string."""
        return _html.escape(str(text))

    @staticmethod
    def severity_badge(severity: str) -> str:
        """Render a colored severity badge with colorblind-safe indicator."""
        color = SEVERITY_COLORS.get(severity, "#6c757d")
        extra_cls = " sev-p1" if severity == SEVERITY_P1 else (" sev-p2" if severity == SEVERITY_P2 else "")
        indicator = {"P0": "▲", "P1": "●", "P2": "◆", "P3": "○"}.get(severity, "")
        prefix = f"{indicator} " if indicator else ""
        text = f"{prefix}{_html.escape(severity)}"
        return f"<span class='severity-badge{extra_cls}' style='background:{color}'>{text}</span>"

    @staticmethod
    def risk_color(risk: str) -> str:
        """Color for a risk rating label."""
        return {
            "Critical": "#dc3545",
            "High": "#fd7e14",
            "Medium": "#ffc107",
            "Low": "#6c757d",
            "Clean": "#28a745",
        }.get(risk, "#6c757d")

    @staticmethod
    def domain_risk(sev: dict[str, int]) -> str:
        """Compute risk label from severity distribution.

        Uses softened thresholds (Issue #113): P0 >= 3 → Critical,
        P0 1-2 → High.  Matches ``ReportDataComputer._compute_risk_label()``.
        """
        p0 = sev.get(SEVERITY_P0, 0)
        if p0 >= 3:
            return "Critical"
        if p0 > 0:
            return "High"
        p1 = sev.get(SEVERITY_P1, 0)
        if p1 >= 3:
            return "High"
        if p1 > 0 or sev.get(SEVERITY_P2, 0) >= 5:
            return "Medium"
        if sev.get(SEVERITY_P2, 0) > 0:
            return "Low"
        if sev.get(SEVERITY_P3, 0) > 0:
            return "Low"
        return "Clean"

    def _resolve_display_name(self, item: dict[str, Any]) -> str:
        """Resolve the display name for a finding/gap using CSN-first lookup.

        Looks up ``_subject_safe_name`` first (canonical key in display_names),
        then falls back to ``_subject``/``subject`` raw value.
        """
        csn = str(item.get("_subject_safe_name", ""))
        raw = str(item.get("_subject", item.get("subject", "")))
        if self.data:
            return self.data.display_names.get(csn, self.data.display_names.get(raw, raw))
        return raw

    @staticmethod
    def agent_to_domain(agent: str) -> str:
        """Map an agent name to one of the registered domains."""
        agent = agent.lower().strip()
        if agent in get_domain_agents():
            return agent
        if "legal" in agent:
            return "legal"
        if "financ" in agent:
            return "finance"
        if "commerc" in agent:
            return "commercial"
        if "cyber" in agent or "security" in agent:
            return "cybersecurity"
        if "product" in agent or "tech" in agent:
            return "producttech"
        return "legal"

    @staticmethod
    def render_alert(level: str, title: str, body: str) -> str:
        """Render a contextual alert box (C1).

        Levels: critical, high, info, good.
        Both *title* and *body* are HTML-escaped to prevent XSS.
        """
        level = level.lower()
        css_class = f"alert alert-{level}"
        return (
            f"<div class='{css_class}'>"
            f"<div class='alert-title'>{_html.escape(title)}</div>"
            f"<div class='alert-body'>{_html.escape(body)}</div>"
            f"</div>"
        )

    @staticmethod
    def rag_indicator(status: str) -> str:
        """Render a small RAG dot (E6)."""
        color = RAG_COLORS.get(status, "#6c757d")
        label = status.capitalize() if status else "Unknown"
        return (
            f"<span class='rag-dot' style='background:{color}' "
            f"title='{_html.escape(label)}' aria-label='Status: {_html.escape(label)}'></span>"
        )

    def render_finding_card(self, finding: Any) -> str:
        """Render a collapsible finding card."""
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", SEVERITY_P3))
        color = SEVERITY_COLORS.get(severity, "#ccc")
        title = self.escape(str(finding.get("title", "Untitled")))
        display_name = self._resolve_display_name(finding)
        entity_name = self.escape(display_name)
        agent = self.escape(str(finding.get("agent", "")))
        confidence = str(finding.get("confidence", "")).lower()

        # Confidence indicator dot (Issue #143)
        conf_html = ""
        if confidence in ("high", "medium", "low"):
            conf_html = f" <span class='conf-dot conf-{confidence}' title='Confidence: {confidence}'></span>"

        return (
            f"<div class='finding-card' style='border-left-color:{color}' "
            f"data-severity='{self.escape(severity)}' data-domain='{self.escape(self.agent_to_domain(agent))}' "
            f"tabindex='0' role='button' aria-expanded='false'>"
            f"<div class='fc-title'>{self.severity_badge(severity)} {title}{conf_html} "
            f"<span class='arrow'>&#9654;</span></div>"
            f"<div class='fc-meta'>Source: {entity_name} | Agent: {agent}</div>"
            f"</div>"
        )

    def render_finding_detail(self, finding: Any) -> str:
        """Render expanded finding detail with description, badges, and citations."""
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", SEVERITY_P3))
        color = SEVERITY_COLORS.get(severity, "#ccc")
        description = self.escape(str(finding.get("description", "")))
        confidence = str(finding.get("confidence", ""))
        verification = str(finding.get("verification_status", finding.get("verified", "")))
        detection = str(finding.get("detection_method", ""))

        parts: list[str] = [f"<div class='finding-detail' style='border-left-color:{color}'>"]

        if description:
            parts.append(f"<div class='fd-description'>{description}</div>")

        badges: list[str] = []
        if confidence:
            badges.append(f"<span class='text-small'>Confidence: <strong>{self.escape(confidence)}</strong></span>")
        if verification:
            vb_class = (
                "vb-verified"
                if verification.lower() in ("verified", "true")
                else ("vb-failed" if verification.lower() in ("failed", "false") else "vb-unchecked")
            )
            badges.append(f"<span class='verification-badge {vb_class}'>{self.escape(verification)}</span>")
        if detection:
            badges.append(f"<span class='text-small text-muted'>Detection: {self.escape(detection)}</span>")
        if badges:
            parts.append(f"<div class='fd-badges'>{''.join(badges)}</div>")

        for cit in finding.get("citations", []):
            parts.append(self.render_citation(cit))

        parts.append("</div>")
        return "\n".join(parts)

    def render_citation(self, citation: Any) -> str:
        """Render a citation block."""
        if not isinstance(citation, dict):
            return ""
        source = self.escape(str(citation.get("source_path", "")))
        section = citation.get("section_ref", citation.get("section", ""))
        page = citation.get("page", "")
        location = citation.get("location", "")
        quote = citation.get("exact_quote", "")

        loc_parts: list[str] = []
        if section:
            loc_parts.append(str(section))
        if page:
            loc_parts.append(f"p.{page}")
        if location and not loc_parts:
            loc_parts.append(str(location))
        loc_str = ", ".join(loc_parts)

        parts: list[str] = ["<div class='citation'>"]
        parts.append(f"<span class='source'>{source}</span>")
        if loc_str:
            parts.append(f" <span class='location'>({self.escape(loc_str)})</span>")
        if quote:
            parts.append(f"<span class='quote'>&ldquo;{self.escape(str(quote))}&rdquo;</span>")
        parts.append("</div>")
        return "".join(parts)

    def render_empty_state(self, message: str) -> str:
        """Render an empty-state placeholder."""
        return f"<p class='text-muted'>{self.escape(message)}</p>"

    def render_bar_chart(self, items: list[tuple[str, float]], max_val: float | None = None) -> str:
        """Render a horizontal bar chart."""
        if not items:
            return ""
        if max_val is None:
            max_val = max(v for _, v in items) if items else 1
        max_val = max(max_val, 1)

        parts: list[str] = []
        for label, value in items:
            pct = (value / max_val) * 100
            parts.append(
                f"<div class='gov-bar-container'>"
                f"<span class='gov-label'>{self.escape(label)}</span>"
                f"<div style='flex:1;background:var(--bg-tertiary);border-radius:4px;height:16px'>"
                f"<div style='width:{pct:.0f}%;background:var(--blue);height:100%;border-radius:4px'></div>"
                f"</div>"
                f"<span class='gov-pct'>{value:.0f}</span>"
                f"</div>"
            )
        return "\n".join(parts)

    def render_severity_bar(self, severity_counts: dict[str, int]) -> str:
        """Render a severity distribution bar with screen-reader text."""
        total = max(sum(severity_counts.values()), 1)
        # Screen-reader-accessible description
        sr_parts = [f"{s}: {severity_counts.get(s, 0)}" for s in ALL_SEVERITIES if severity_counts.get(s, 0)]
        sr_text = self.escape(", ".join(sr_parts) or "No findings")
        parts: list[str] = [f"<div class='sev-bar' role='img' aria-label='Severity distribution: {sr_text}'>"]
        for s in ALL_SEVERITIES:
            pct = (severity_counts.get(s, 0) / total) * 100
            if pct > 0:
                parts.append(f"<span style='width:{pct:.1f}%;background:{SEVERITY_COLORS[s]}'></span>")
        parts.append("</div>")
        return "".join(parts)

    def render_category_group(self, category: str, findings: list[dict[str, Any]]) -> str:
        """Render a collapsible category group with findings grouped by subject."""
        sev_counts: dict[str, int] = defaultdict(int)
        for f in findings:
            sev_counts[f.get("severity", SEVERITY_P3)] += 1
        sev_str = self.escape(", ".join(f"{k}:{v}" for k, v in sorted(sev_counts.items()) if v > 0))

        parts: list[str] = [
            "<div class='category-group'>",
            f"<div class='category-header' tabindex='0' role='button' aria-expanded='false'>"
            f"<span><strong>{self.escape(category)}</strong> ({len(findings)} findings, {sev_str})</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='category-body'>",
        ]

        by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in findings:
            by_subject[str(f.get("_subject_safe_name", f.get("_subject", "Unknown")))].append(f)

        for subj, subj_findings in sorted(by_subject.items()):
            display = self.data.display_names.get(subj, subj) if self.data else subj
            parts.append(f"<h3>{self.escape(display)}</h3>")
            for f in subj_findings:
                parts.append(self.render_finding_card(f))
                parts.append(self.render_finding_detail(f))

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS (Issue #113: CSS variables, sidebar nav, alert boxes, two-column)
# ---------------------------------------------------------------------------


def render_css() -> str:
    """Return the full CSS for the report."""
    base = """
/* CSS Custom Properties */
:root {
    --navy: #0f172a;
    --navy-light: #1e293b;
    --red: #ef4444;
    --orange: #f97316;
    --yellow: #eab308;
    --green: #22c55e;
    --blue: #3b82f6;
    --purple: #8b5cf6;
    --amber: #d97706;
    --gray: #64748b;
    --gray-light: #94a3b8;
    --gray-dark: #1e293b;
    --bg-primary: #f8fafc;
    --bg-secondary: #ffffff;
    --bg-tertiary: #f1f5f9;
    --bg-hover: #f8fafc;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --border-light: #e2e8f0;
    --border-medium: #cbd5e1;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 16px rgba(0,0,0,0.06);
    --shadow-lg: 0 8px 32px rgba(0,0,0,0.08);
    --sidebar-width: 220px;
    --header-height: 0px;
    --radius: 12px;
    --radius-sm: 8px;
    /* Severity */
    --sev-p0: #dc3545;
    --sev-p1: #fd7e14;
    --sev-p2: #ffc107;
    --sev-p3: #6c757d;
    --sev-p0-bg: #fff5f5;
    --sev-p1-bg: #fff8f0;
    --sev-p2-bg: #fffdf0;
    --sev-p3-bg: #f8f9fa;
    /* Domain */
    --dom-legal: #4a90d9;
    --dom-finance: #2d8a4e;
    --dom-commercial: #7c3aed;
    --dom-producttech: #d97706;
    /* Alert */
    --alert-critical-bg: #fff5f5;
    --alert-critical-border: #dc3545;
    --alert-high-bg: #fff8f0;
    --alert-high-border: #fd7e14;
    --alert-info-bg: #e8f4fd;
    --alert-info-border: #4a90d9;
    --alert-good-bg: #f0fff4;
    --alert-good-border: #28a745;
}

/* Reset & base */
*, *::before, *::after { box-sizing: border-box; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
       margin: 0; padding: 0; background: #ffffff; color: var(--text-primary);
       line-height: 1.7; font-size: 15px; -webkit-font-smoothing: antialiased; }

/* Sidebar Navigation — off-canvas, hidden by default */
.sidebar { position: fixed; top: 0; left: -260px; width: 250px; height: 100vh;
           background: var(--bg-secondary); border-right: 1px solid var(--border-light);
           overflow-y: auto; z-index: 2000; padding: 0; display: flex; flex-direction: column;
           transition: left 0.25s ease; box-shadow: var(--shadow-lg); }
.sidebar.open { left: 0; }
.sidebar-brand { padding: 24px 20px 20px; font-weight: 800; font-size: 0.85em;
                 color: var(--text-primary); border-bottom: 1px solid var(--border-light);
                 display: flex; align-items: center; gap: 10px; letter-spacing: -0.02em; }
.sidebar-brand .confidential { background: var(--red); color: white; font-size: 0.55em;
                                padding: 2px 7px; border-radius: 4px; font-weight: 700;
                                letter-spacing: 0.5px; text-transform: uppercase; }
.sidebar-footer { margin-top: auto; padding: 16px; border-top: 1px solid var(--border-light); }
.sidebar-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.3);
                   z-index: 1999; }
.sidebar-overlay.open { display: block; }

/* Hamburger menu button */
.nav-toggle { position: fixed; top: 16px; left: 16px; z-index: 1500;
              background: var(--bg-secondary); border: 1px solid var(--border-light);
              border-radius: 8px; padding: 8px 12px; cursor: pointer;
              box-shadow: var(--shadow-sm); font-size: 1.1em; line-height: 1;
              transition: box-shadow 0.15s; }
.nav-toggle:hover { box-shadow: var(--shadow-md); }

.toc-group { padding: 12px 0 4px; }
.toc-group-label { padding: 4px 20px 8px; font-size: 0.6em; font-weight: 700;
                   text-transform: uppercase; letter-spacing: 1.2px; color: var(--text-muted); }
.sidebar a { display: flex; align-items: center; gap: 8px; color: var(--text-secondary);
             text-decoration: none; padding: 7px 20px; font-size: 0.82em; font-weight: 500;
             transition: color 0.15s, background 0.15s; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; border-radius: 6px; margin: 1px 10px; }
.sidebar a:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.sidebar a.active { color: var(--blue); background: #eff6ff; font-weight: 600; }
.sidebar a .rag-dot { flex-shrink: 0; }

/* RAG dots */
.rag-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
           flex-shrink: 0; }

/* Content area */
.main-wrapper { margin-left: 0; }

/* Content wrapper */
.content { max-width: 820px; margin: 0 auto; padding: 60px 32px; }

/* Report sections */
.report-section { margin-bottom: 56px; }
.report-section > h2 { color: var(--text-primary); font-size: 1.5em; font-weight: 800;
                        border-bottom: none; padding-bottom: 0; margin-bottom: 24px;
                        letter-spacing: -0.03em; }

/* Deal header — light, minimal (hero zone overrides below) */
.deal-header { padding: 16px 0 20px; border-bottom: 1px solid var(--border-light);
               margin-bottom: 28px; }
.deal-header h1 { margin: 0 0 8px; font-size: 1.6em; font-weight: 800; color: var(--text-primary);
                  letter-spacing: -0.03em; }
.deal-header .deal-meta { color: var(--text-secondary); font-size: 0.9em; }
.deal-header .risk-badge { display: inline-block; padding: 6px 20px; border-radius: 20px;
                           font-weight: 700; font-size: 1.1em; margin-top: 12px; }
.deal-header .run-id { color: var(--text-muted); font-size: 0.8em; margin-top: 8px; }
.deal-header .timestamp { color: var(--text-muted); font-size: 0.75em; margin-top: 4px; }

/* Key metrics strip */
.metrics-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                 gap: 16px; margin-bottom: 32px; }
.metric-card { background: var(--bg-secondary); border-radius: var(--radius); padding: 20px 16px;
               text-align: center; box-shadow: var(--shadow-sm); border: 1px solid var(--border-light);
               transition: box-shadow 0.15s, transform 0.15s; }
.metric-card:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
.metric-card .value { font-size: 2em; font-weight: 800; letter-spacing: -0.02em; }
.metric-card .label { color: var(--text-muted); font-size: 0.72em; text-transform: uppercase;
                      letter-spacing: 0.8px; margin-top: 4px; }

/* Alert boxes (C1) */
.alert { border-radius: var(--radius-sm); padding: 18px 22px; margin: 20px 0;
         border-left: 4px solid; }
.alert-title { font-weight: 700; font-size: 0.88em; margin-bottom: 6px; text-transform: uppercase;
               letter-spacing: 0.3px; }
.alert-body { font-size: 0.9em; line-height: 1.6; }
.alert-critical { background: var(--alert-critical-bg); border-left-color: var(--alert-critical-border);
                  color: #721c24; }
.alert-critical .alert-title { color: var(--red); }
.alert-high { background: var(--alert-high-bg); border-left-color: var(--alert-high-border);
              color: #856404; }
.alert-high .alert-title { color: var(--orange); }
.alert-info { background: var(--alert-info-bg); border-left-color: var(--alert-info-border);
              color: #0c5460; }
.alert-info .alert-title { color: var(--blue); }
.alert-good { background: var(--alert-good-bg); border-left-color: var(--alert-good-border);
              color: #155724; }
.alert-good .alert-title { color: var(--green); }

/* Two-column layout (A3) */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 16px 0; }

/* Wolf pack (deal-breakers) */
.wolf-pack { margin-bottom: 32px; }
.wolf-pack h2 { color: var(--red); font-size: 1.3em; }
.wolf-card { background: var(--bg-secondary); border-left: 4px solid; border-radius: var(--radius-sm);
             padding: 20px 24px; margin-bottom: 16px;
             box-shadow: var(--shadow-sm); border: 1px solid var(--border-light);
             border-left-width: 4px; transition: box-shadow 0.15s; }
.wolf-card:hover { box-shadow: var(--shadow-md); }
.wolf-card .wolf-title { font-weight: 700; font-size: 1.05em; margin-bottom: 6px;
                         color: var(--text-primary); }
.wolf-card .wolf-meta { color: var(--text-muted); font-size: 0.82em; }
.wolf-card .wolf-quote { background: var(--bg-tertiary); padding: 10px 14px; margin-top: 10px;
                          border-radius: 6px; font-style: italic; color: var(--text-secondary);
                          font-size: 0.88em; line-height: 1.5; }

/* Heatmap */
.heatmap { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
           gap: 16px; margin-bottom: 32px; }
.heatmap-cell { background: var(--bg-secondary); border-radius: var(--radius); padding: 24px 20px;
                text-align: center; box-shadow: var(--shadow-sm); cursor: pointer;
                transition: transform 0.15s, box-shadow 0.15s; border-top: 4px solid;
                border: 1px solid var(--border-light); border-top-width: 4px; }
.heatmap-cell:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
.heatmap-cell .domain-name { font-weight: 700; font-size: 0.85em; text-transform: uppercase;
                             letter-spacing: 0.3px; }
.heatmap-cell .domain-risk { font-size: 0.9em; margin: 8px 0; font-weight: 700; }
.heatmap-cell .domain-counts { font-size: 0.78em; color: var(--text-muted); }

/* Severity cards (E2) */
.severity-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 20px 0; }
.severity-card { border-radius: var(--radius); padding: 20px 16px; text-align: center;
                 border: 1px solid var(--border-light); }
.severity-card .sev-count { font-size: 2.2em; font-weight: 800; letter-spacing: -0.02em; }
.severity-card .sev-label { font-size: 0.72em; text-transform: uppercase; letter-spacing: 0.8px;
                            color: var(--text-muted); margin-top: 4px; }

/* Domain sections */
.domain-section { background: var(--bg-secondary); border-radius: var(--radius); margin-bottom: 20px;
                  border: 1px solid var(--border-light); overflow: hidden; }
.domain-header { padding: 18px 24px; cursor: pointer; display: flex;
                 justify-content: space-between; align-items: center;
                 border-left: 4px solid; transition: background 0.15s; }
.domain-header:hover { background: var(--bg-tertiary); }
.domain-header h2 { margin: 0; font-size: 1.1em; font-weight: 700; }
.domain-body { padding: 0 24px 24px; display: none; }
.domain-body.open { display: block; }

/* Severity distribution bar */
.sev-bar { display: flex; width: 100%; height: 6px; border-radius: 3px; overflow: hidden;
           margin: 4px 0; background: #e8ecf0; }
.sev-bar span { display: block; min-width: 6px; }

/* Category groups */
.category-group { border: 1px solid var(--border-light); border-radius: var(--radius-sm); margin: 12px 0;
                  overflow: hidden; }
.category-header { padding: 12px 18px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center; background: var(--bg-tertiary); }
.category-header:hover { background: var(--border-light); }
.category-body { padding: 16px 18px; display: none; }
.category-body.open { display: block; }

/* Subject sections */
.subject-section { background: var(--bg-secondary); border-radius: var(--radius-sm); margin: 14px 0;
                    border: 1px solid var(--border-light); overflow: hidden; }
.subject-header { padding: 14px 20px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center;
                   background: var(--bg-tertiary); transition: background 0.15s; }
.subject-header:hover { background: var(--border-light); }
.subject-body { padding: 18px 20px; display: none; }
.subject-body.open { display: block; }

/* Finding cards */
.finding-card { border-left: 4px solid #ccc; padding: 14px 18px; margin: 10px 0;
                background: var(--bg-secondary); border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
                cursor: pointer; transition: background 0.15s, box-shadow 0.15s;
                border: 1px solid var(--border-light); border-left-width: 4px; }
.finding-card:hover { background: var(--bg-tertiary); box-shadow: var(--shadow-sm); }
.finding-card .fc-title { font-weight: 600; font-size: 0.95em; }
.finding-card .fc-meta { color: var(--text-muted); font-size: 0.82em; margin-top: 4px; }
.conf-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-left: 4px;
  vertical-align: middle; }
.conf-high { background: #198754; }
.conf-medium { background: #fd7e14; }
.conf-low { background: #dc3545; }
.finding-detail { display: none; padding: 16px 18px; background: var(--bg-tertiary);
                  border-left: 4px solid #ccc; margin: 0 0 10px;
                  border-radius: 0 0 var(--radius-sm) 0; }
.finding-detail.open { display: block; }
.finding-detail .fd-description { margin-bottom: 10px; line-height: 1.6; font-size: 0.92em; }
.finding-detail .fd-badges { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }

/* Generic badge */
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
         font-size: 0.85em; font-weight: 600; }

/* Severity badge */
.severity-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
                  color: white; font-weight: 600; font-size: 0.8em; }
.severity-badge.sev-p1 { color: #333; }  /* Dark text on orange — WCAG AA contrast (4.9:1) */
.severity-badge.sev-p2 { color: #333; }  /* Dark text on yellow — WCAG AA contrast (12.6:1) */

/* Verification badge */
.verification-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
                      font-size: 0.75em; font-weight: 600; }
.vb-verified { background: #d4edda; color: #155724; }
.vb-failed { background: #f8d7da; color: #721c24; }
.vb-unchecked { background: var(--bg-tertiary); color: #495057; }

/* Recommendation cards (B6) */
.rec-card { background: var(--bg-secondary); border-radius: var(--radius-sm); padding: 18px 22px;
            margin: 14px 0; border: 1px solid var(--border-light); border-left: 4px solid; }
.rec-timeline { font-size: 0.72em; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.5px; padding: 3px 10px; border-radius: 10px;
                display: inline-block; margin-bottom: 6px; }
.rec-title { font-weight: 700; font-size: 1em; margin: 6px 0; color: var(--text-primary); }
.rec-desc { font-size: 0.9em; color: var(--text-secondary); line-height: 1.6; }

/* Subject summary table */
.subject-table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.88em; }
.subject-table th, .subject-table td { padding: 12px 16px; border-bottom: 1px solid var(--border-light);
                                          text-align: left; }
.subject-table th { background: var(--bg-tertiary); font-weight: 600; font-size: 0.78em;
                     text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }
.subject-table tr:hover { background: var(--bg-tertiary); }

/* Health tier badges */
.tier-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
              font-size: 0.75em; font-weight: 600; }
.tier-1 { background: var(--sev-p0-bg); color: var(--red); border: 1px solid var(--red); }
.tier-2 { background: var(--sev-p1-bg); color: var(--orange); border: 1px solid var(--orange); }
.tier-3 { background: var(--sev-p3-bg); color: var(--gray); border: 1px solid var(--gray); }

/* Citations */
.citation { background: var(--bg-tertiary); padding: 12px 16px; margin: 8px 0; border-radius: 6px;
            font-size: 0.88em; border-left: 3px solid var(--border-medium); }
.citation .source { font-weight: 600; color: var(--text-primary); font-size: 0.9em; }
.citation .location { color: var(--text-muted); font-size: 0.82em; }
.citation .quote { font-style: italic; color: var(--text-secondary); margin-top: 6px; padding: 8px 12px;
                   background: var(--bg-primary); border-radius: 4px; display: block;
                   line-height: 1.5; font-size: 0.92em; }

/* Cross-reference */
.xref-mismatch { background: var(--sev-p0-bg); border-left: 3px solid var(--red); }
.xref-match { background: #f0fff0; }
.xref-unverified { background: var(--bg-hover); }

/* Gap analysis */
.gap-summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }

/* Governance bars */
.gov-bar-container { display: flex; align-items: center; gap: 10px; margin: 4px 0; }
.gov-bar { height: 20px; border-radius: 4px; transition: width 0.3s; }
.gov-label { min-width: 150px; font-size: 0.9em; }
.gov-pct { font-size: 0.85em; font-weight: 600; min-width: 50px; }

/* Tables */
table.sortable { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.88em; }
table.sortable th, table.sortable td { padding: 11px 14px; border-bottom: 1px solid var(--border-light);
                                        text-align: left; }
table.sortable th { background: var(--bg-tertiary); cursor: pointer; user-select: none;
                    white-space: nowrap; font-size: 0.78em; text-transform: uppercase;
                    letter-spacing: 0.4px; color: var(--text-muted); font-weight: 600; }
table.sortable th:hover { background: var(--border-light); }
table.sortable th::after { content: ' \\2195'; color: #ccc; font-size: 0.8em; }
table.sortable tr:hover td { background: var(--bg-tertiary); }
table.sortable caption { caption-side: top; text-align: left; font-size: 0.78em;
  color: var(--text-muted); padding: 0 0 6px; }

/* Arrow toggle */
.arrow { font-size: 0.8em; transition: transform 0.2s; display: inline-block; }
.arrow.open { transform: rotate(90deg); }

/* Responsive */
@media (max-width: 900px) {
    .heatmap, .severity-cards { grid-template-columns: repeat(2, 1fr); }
    .metrics-strip { grid-template-columns: repeat(2, 1fr); }
    .gap-summary-grid, .two-col { grid-template-columns: 1fr; }
    .nav-toggle { top: 12px; left: 12px; }
}
@media (max-width: 600px) {
    .heatmap, .severity-cards { grid-template-columns: 1fr; }
    .content { padding: 24px 16px; }
    .nav-toggle { top: 8px; left: 8px; padding: 6px 10px; }
}

/* Waterfall chart (Issue #102) */
.waterfall { margin: 16px 0; }
.waterfall-row { display: flex; align-items: center; margin-bottom: 6px; }
.waterfall-label { width: 220px; flex-shrink: 0; font-size: 0.85em; padding-right: 12px;
                   text-align: right; }
.waterfall-bar-container { flex: 1; height: 32px; position: relative;
                           background: var(--bg-light, #f8f9fa); border-radius: 4px;
                           overflow: hidden; }
.waterfall-bar { height: 100%; display: flex; align-items: center;
                 padding: 0 8px; font-size: 0.8em; color: #fff; white-space: nowrap; }
.waterfall-bar--total { background: var(--navy, #1a365d); border-radius: 4px; }
.waterfall-bar--adjusted { background: var(--sev-p3, #198754); border-radius: 4px; }
/* Stacked risk row: dark "remaining" portion + pink "deduction" portion side by side */
.waterfall-risk-stack { display: flex; width: 100%; height: 100%; }
.waterfall-risk-stack .remaining { background: var(--navy, #1a365d); opacity: 0.25; }
.waterfall-risk-stack .deduction { background: var(--sev-p1, #fd7e14);
                 display: flex; align-items: center; padding: 0 8px;
                 font-size: 0.8em; color: #fff; white-space: nowrap; }
.waterfall-deduction-label { font-size: 0.8em; color: var(--sev-p1, #fd7e14);
                 padding-left: 8px; white-space: nowrap; line-height: 32px; }
.data-note { font-size: 0.8em; color: #6c757d; margin-top: 16px; font-style: italic; }

/* Print mode (E5) */
@page { margin: 2cm 1.5cm; }
@media print {
    .sidebar, .skip-link, .nav-toggle, .sidebar-overlay { display: none !important; }
    .domain-body, .subject-body, .category-body, .finding-detail { display: block !important; }
    body { background: white; font-size: 11pt; orphans: 3; widows: 3; }
    .deal-header { border-bottom: 2px solid #333; }
    .severity-badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .sev-bar span { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .rag-dot { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .alert { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .content { max-width: 100%; padding: 0; }
    .heatmap-cell, .metric-card, .finding-card, .wolf-card, .subject-section,
    .domain-section, .category-group, .citation, table.sortable,
    .alert, .rec-card, .cross-domain-card, .priority-finding,
    .domain-card { break-inside: avoid; }
    .report-section > h2 { break-after: avoid; }
    h3, h4 { break-after: avoid; }
    a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 0.8em; color: var(--text-secondary);
                             word-break: break-all; }
    .sidebar a::after { content: none !important; }
    .arrow { display: none !important; }
}

/* Accessibility: skip link */
.skip-link { position: absolute; top: -40px; left: 0; background: var(--navy); color: white;
             padding: 8px 16px; z-index: 10000; font-size: 0.9em; text-decoration: none;
             transition: top 0.15s; }
.skip-link:focus { top: 0; }

/* Accessibility: focus styles (E8) */
*:focus { outline: 2px solid var(--blue); outline-offset: 2px; }
*:focus:not(:focus-visible) { outline: none; }
*:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.finding-card:focus-visible, .category-header:focus-visible,
.domain-header:focus-visible, .subject-header:focus-visible {
    outline: 2px solid var(--blue); outline-offset: -2px;
    box-shadow: 0 0 0 3px rgba(74,144,217,0.3); }

/* Layer dividers — progressive disclosure */
.layer-divider { text-align: center; padding: 40px 0; position: relative; }
.layer-divider::before { content: ''; position: absolute; top: 50%; left: 10%; right: 10%;
                         height: 1px; background: var(--border-light); }
.layer-toggle { position: relative; z-index: 1; background: #ffffff;
                border: 2px solid var(--border-medium); border-radius: 28px;
                padding: 12px 32px; font-size: 0.92em; font-weight: 700;
                color: var(--text-primary); cursor: pointer;
                transition: all 0.2s; letter-spacing: -0.01em; }
.layer-toggle:hover { border-color: var(--blue); color: var(--blue);
                      box-shadow: var(--shadow-md); transform: translateY(-1px); }
.layer-toggle.active { border-color: var(--blue); color: var(--blue); background: #eff6ff; }
.layer-toggle--muted { font-size: 0.85em; padding: 10px 26px; color: var(--text-muted);
                       border-color: var(--border-light); }
.deep-dive-layer { animation: fadeIn 0.3s ease; padding-top: 8px; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(12px); }
                    to { opacity: 1; transform: translateY(0); } }

/* Utility */
.hidden { display: none !important; }
.text-muted { color: var(--text-secondary); }
.text-small { font-size: 0.85em; }
.mt-8 { margin-top: 8px; }
.mb-8 { margin-bottom: 8px; }
.mb-16 { margin-bottom: 16px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }

/* --- Issue #108: Presentation Mode --- */
.presentation-btn {
    display: block; margin: 8px auto; padding: 4px 12px;
    background: var(--blue); color: #fff; border: none; border-radius: 4px;
    cursor: pointer; font-size: 0.75em; }
.presentation-btn:hover { background: #357abd; }

.presentation-mode .sidebar, .presentation-mode .nav-toggle { display: none; }
.presentation-mode .content { max-width: 100%; padding: 40px 60px; font-size: 18px; }
.presentation-mode .report-section { page-break-before: always; }
.presentation-mode .category-body,
.presentation-mode .domain-body,
.presentation-mode .subject-body { display: block !important; max-height: none !important; }
.presentation-mode .arrow { display: none; }
.presentation-mode h2 { font-size: 2em; }
.presentation-mode .metric-card .value { font-size: 2.5em; }

/* --- Issue #108: Print Styles --- */
@media print {
    .sidebar, .skip-link, .presentation-btn, #btn-presentation, .nav-toggle,
    .sidebar-overlay { display: none !important; }
    .content { max-width: 100% !important; padding: 20px !important; }
    .report-section { page-break-before: always; page-break-inside: avoid; }
    .category-body, .domain-body, .subject-body { display: block !important; max-height: none !important; }
    .finding-detail { display: block !important; }
    table { page-break-inside: avoid; }
    @page { margin: 2cm; size: A4; }
    @page :first { margin-top: 4cm; }
    a[href]::after { content: none !important; }
}
"""
    from dd_agents.reporting.html_cross_domain import CROSS_DOMAIN_CSS
    from dd_agents.reporting.html_domain_summary import DOMAIN_SUMMARY_CSS
    from dd_agents.reporting.html_filter_bar import FILTER_BAR_CSS

    return base + FILTER_BAR_CSS + DOMAIN_SUMMARY_CSS + CROSS_DOMAIN_CSS + HERO_ZONE_CSS


# ---------------------------------------------------------------------------
# Hero Zone CSS — executive viewport redesign
# ---------------------------------------------------------------------------

HERO_ZONE_CSS = """
/* Hero Zone — executive viewport */
.hero-zone { padding-bottom: 32px; border-bottom: 1px solid var(--border-light); margin-bottom: 40px; }
.hero-zone h2 { display: none; }

.deal-header { padding: 0 0 20px; border-bottom: none; margin-bottom: 24px; }
.deal-parties { font-size: 1.5em; font-weight: 800; color: var(--text-primary);
                letter-spacing: -0.03em; }
.deal-arrow { color: var(--blue); margin: 0 6px; font-weight: 400; }
.deal-type { display: inline-block; margin-left: 14px; padding: 3px 12px; border-radius: 14px;
             background: var(--bg-tertiary); font-size: 0.7em; font-weight: 700;
             color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.8px;
             vertical-align: middle; }
.deal-context-summary { margin: 12px 0 0; color: var(--text-secondary); font-size: 0.93em;
                        line-height: 1.7; max-width: 800px; }

/* Hero Verdict */
.hero-verdict { border-left: 6px solid var(--verdict-color, #ffc107); background: var(--bg-secondary);
                border-radius: var(--radius); padding: 28px 32px; margin-bottom: 28px;
                box-shadow: var(--shadow-md); border: 1px solid var(--border-light);
                border-left-width: 6px; }
.hero-verdict-signal { font-size: 2.2em; font-weight: 900; color: var(--verdict-color);
                       letter-spacing: -0.03em; }
.hero-verdict-score { color: var(--text-muted); margin: 8px 0; font-size: 0.9em; }
.hero-verdict-rationale { color: var(--text-primary); line-height: 1.7; margin-top: 10px;
                          font-size: 0.95em; font-weight: 500; }
.hero-verdict-narrative { color: var(--text-secondary); line-height: 1.7; margin-top: 12px;
                          font-size: 0.9em; border-top: 1px solid var(--border-light);
                          padding-top: 12px; }
.verdict-factors { margin: 12px 0 0; padding-left: 18px; color: var(--text-secondary);
                   font-size: 0.88em; line-height: 1.8; }

/* Key Takeaways */
.hero-takeaways { margin-bottom: 28px; }
.hero-takeaways h3 { margin: 0 0 14px; font-size: 1.05em; font-weight: 700; }
.takeaway-list { margin: 0; padding-left: 0; list-style: none; }
.takeaway-list li { margin-bottom: 14px; line-height: 1.7; font-size: 0.95em;
                    padding: 12px 16px; background: var(--bg-secondary); border-radius: var(--radius-sm);
                    border: 1px solid var(--border-light); }
.takeaway-icon { font-size: 0.9em; margin-right: 4px; }
.takeaway-text { color: var(--text-primary); }
.takeaway-domains { color: var(--text-muted); font-size: 0.82em; display: block; margin-top: 4px; }

/* Domain Grid */
.domain-grid-section { margin-bottom: 28px; }
.donut-container { text-align: center; margin-bottom: 20px; }
.domain-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
               gap: 12px; margin-bottom: 20px; }
.domain-card { display: flex; flex-direction: column; align-items: center; justify-content: center;
               padding: 18px 12px; border-radius: var(--radius); border: 1.5px solid var(--border-light);
               background: var(--bg-secondary); text-decoration: none; color: inherit;
               transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
               text-align: center; min-height: 100px; }
.domain-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg);
                     border-color: var(--domain-color, var(--border-medium)); }
.domain-card-name { font-size: 0.78em; font-weight: 700; color: var(--domain-color);
                    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.domain-card-rag { font-size: 0.7em; font-weight: 700; padding: 3px 10px; border-radius: 10px;
                   margin-bottom: 6px; }
.domain-card-count { font-size: 1.2em; font-weight: 700; color: var(--text-primary); }
.rag-red .domain-card-rag { background: #dc354515; color: #dc3545; }
.rag-amber .domain-card-rag { background: #fd7e1415; color: #d97706; }
.rag-green .domain-card-rag { background: #28a74515; color: #28a745; }
.rag-red { border-color: #dc354530; }
.rag-amber { border-color: #fd7e1430; }
.rag-green { border-color: #28a74530; }

/* Domain Strip — compact risk rows */
.domain-strip { margin: 24px 0 32px; }
.domain-row { display: flex; align-items: center; gap: 12px; padding: 12px 16px;
              border-radius: 8px; text-decoration: none; color: inherit;
              transition: background 0.15s; margin-bottom: 4px; }
.domain-row:hover { background: var(--bg-tertiary); }
.domain-row-name { font-weight: 600; font-size: 0.9em; min-width: 120px;
                   color: var(--domain-color, var(--text-primary)); }
.domain-row-bar { flex: 1; height: 8px; border-radius: 4px; display: flex;
                  overflow: hidden; background: var(--bg-tertiary); }
.domain-row-bar span { display: block; min-width: 4px; }
.domain-row-badge { font-size: 0.78em; font-weight: 700; min-width: 60px;
                    text-align: right; }
.domain-row-count { font-size: 0.9em; font-weight: 700; min-width: 24px;
                    text-align: right; color: var(--text-muted); }
.domain-row--clean { opacity: 0.6; }
.domain-row--clean .domain-row-name { font-weight: 400; color: var(--text-muted); }

/* Hero Stats (alongside domain grid) */
.hero-stats { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 16px; }
.hero-stat { text-align: center; padding: 10px 18px; background: var(--bg-secondary);
             border-radius: var(--radius-sm); border: 1px solid var(--border-light); }
.hero-stat-value { display: block; font-size: 1.6em; font-weight: 800; color: var(--text-primary);
                   letter-spacing: -0.02em; }
.hero-stat-label { display: block; font-size: 0.7em; color: var(--text-muted);
                   text-transform: uppercase; letter-spacing: 0.8px; margin-top: 2px; }

/* Open Items Panel */
.open-items-panel { background: var(--bg-secondary); border-radius: var(--radius); padding: 20px 24px;
                    margin-bottom: 28px; border: 1px solid var(--border-light); }
.open-items-panel h3 { margin: 0 0 14px; font-size: 1.05em; font-weight: 700; }
.open-items-grid { display: flex; gap: 14px; flex-wrap: wrap; }
.open-item-card { display: flex; flex-direction: column; align-items: center; padding: 14px 20px;
                  background: var(--bg-tertiary); border-radius: var(--radius-sm); min-width: 110px; }
.open-item-icon { font-size: 1.4em; margin-bottom: 6px; }
.open-item-count { font-size: 1.5em; font-weight: 800; color: var(--text-primary); }
.open-item-label { font-size: 0.7em; color: var(--text-muted); text-transform: uppercase;
                   letter-spacing: 0.5px; text-align: center; margin-top: 2px; }
.open-item-urgent { font-size: 0.7em; color: var(--red); font-weight: 700; margin-top: 4px; }

/* Executive Narrative */
.executive-narrative { background: var(--bg-secondary); border-radius: var(--radius); padding: 20px 24px;
                       margin-bottom: 28px; border: 1px solid var(--border-light); }
.executive-narrative h3 { margin: 0 0 12px; font-size: 1.05em; font-weight: 700; }
.narrative-body { line-height: 1.8; color: var(--text-primary); font-size: 0.93em; }

/* Config Guidance Banner */
.config-guidance { display: flex; align-items: flex-start; gap: 14px; padding: 16px 20px;
                   background: var(--bg-tertiary); border: 1px solid var(--border-light);
                   border-radius: var(--radius-sm); margin-top: 20px; font-size: 0.88em;
                   line-height: 1.7; }
.config-guidance-icon { font-size: 1.4em; flex-shrink: 0; }
.config-guidance-body { color: var(--text-secondary); }
.config-guidance-body code { background: var(--bg-primary); padding: 2px 6px; border-radius: 4px;
                             font-size: 0.88em; color: var(--blue); }

/* Deal Breaker List */
.deal-breaker-list { padding-left: 0; list-style: none; }
.deal-breaker-list li { margin-bottom: 14px; line-height: 1.7; padding: 12px 16px;
                        background: var(--sev-p0-bg); border-radius: var(--radius-sm);
                        border-left: 4px solid var(--red); }

@media (max-width: 768px) {
    .domain-grid { grid-template-columns: repeat(3, 1fr); }
    .hero-verdict { padding: 20px; }
    .hero-verdict-signal { font-size: 1.6em; }
    .deal-parties { font-size: 1.2em; }
    .open-items-grid { flex-direction: column; }
    .takeaway-list li { padding: 10px 12px; }
}
@media print {
    .hero-zone { page-break-after: always; }
    .config-guidance { display: none; }
    .domain-card:hover { transform: none; box-shadow: none; }
}
"""

# ---------------------------------------------------------------------------
# JS (Issue #113: sidebar scroll tracking)
# ---------------------------------------------------------------------------


def render_js() -> str:
    """Return the full JavaScript for the report."""
    base = """
(function() {
    'use strict';

    // --- Toggle collapsible sections (click + keyboard) ---
    function toggleSection(header) {
        var body = header.nextElementSibling;
        if (!body) return;
        var isOpen = body.classList.toggle('open');
        var arrow = header.querySelector('.arrow');
        if (arrow) arrow.classList.toggle('open');
        header.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
    function setupToggles(headerSel, bodySel) {
        document.querySelectorAll(headerSel).forEach(function(header) {
            header.addEventListener('click', function(e) {
                if (e.target.tagName === 'A') return;
                toggleSection(this);
            });
            header.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleSection(this);
                }
            });
        });
    }
    setupToggles('.subject-header', '.subject-body');
    setupToggles('.domain-header', '.domain-body');
    setupToggles('.category-header', '.category-body');

    // --- Finding card expand (click + keyboard) ---
    function toggleFinding(card) {
        var detail = card.nextElementSibling;
        if (detail && detail.classList.contains('finding-detail')) {
            var isOpen = detail.classList.toggle('open');
            var arrow = card.querySelector('.arrow');
            if (arrow) arrow.classList.toggle('open');
            card.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        }
    }
    document.querySelectorAll('.finding-card').forEach(function(card) {
        card.addEventListener('click', function() { toggleFinding(this); });
        card.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleFinding(this);
            }
        });
    });

    // --- Sortable tables ---
    document.querySelectorAll('table.sortable th').forEach(function(th) {
        th.addEventListener('click', function() {
            var table = this.closest('table');
            var tbody = table.querySelector('tbody');
            if (!tbody) return;
            var rows = Array.from(tbody.querySelectorAll('tr'));
            var col = Array.from(this.parentNode.children).indexOf(this);
            var asc = this.dataset.sort !== 'asc';
            rows.sort(function(a, b) {
                var va = (a.children[col] || {}).textContent || '';
                var vb = (b.children[col] || {}).textContent || '';
                va = va.trim(); vb = vb.trim();
                var na = parseFloat(va), nb = parseFloat(vb);
                if (!isNaN(na) && !isNaN(nb)) return asc ? na - nb : nb - na;
                return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            });
            rows.forEach(function(row) { tbody.appendChild(row); });
            this.dataset.sort = asc ? 'asc' : 'desc';
        });
    });

    // --- Sidebar scroll tracking (A1) ---
    var sections = document.querySelectorAll('[id^="sec-"]');
    var sidebarLinks = document.querySelectorAll('.sidebar a[href^="#"]');
    if (sections.length && sidebarLinks.length) {
        window.addEventListener('scroll', function() {
            var scrollY = window.scrollY + 100;
            var activeId = '';
            sections.forEach(function(sec) {
                if (sec.offsetTop <= scrollY) {
                    activeId = sec.id;
                }
            });
            sidebarLinks.forEach(function(l) {
                l.classList.toggle('active', l.getAttribute('href') === '#' + activeId);
            });
        });
    }

    // --- Issue #108: Presentation mode toggle ---
    var presBtn = document.getElementById('btn-presentation');
    if (presBtn) {
        presBtn.addEventListener('click', function() {
            document.body.classList.toggle('presentation-mode');
            var active = document.body.classList.contains('presentation-mode');
            this.textContent = active ? '\\u25C0 Exit' : '\\u25B6 Present';
            this.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }
})();
"""
    from dd_agents.reporting.html_filter_bar import FILTER_BAR_JS

    # Remove sidebar links whose target section doesn't exist on the page
    sidebar_cleanup_js = """
// --- Sidebar: hide links to non-existent sections ---
(function() {
    'use strict';
    document.querySelectorAll('.sidebar a[href^=\"#\"]').forEach(function(a) {
        var id = a.getAttribute('href').slice(1);
        if (id && !document.getElementById(id)) {
            a.style.display = 'none';
        }
    });
    // Hide empty toc-groups (all links hidden)
    document.querySelectorAll('.toc-group').forEach(function(g) {
        var visible = g.querySelectorAll('a:not([style*=\"display: none\"])');
        if (visible.length === 0) g.style.display = 'none';
    });
})();
"""

    # Sidebar toggle (hamburger menu)
    sidebar_toggle_js = """
// --- Sidebar hamburger toggle ---
(function() {
    'use strict';
    var btn = document.getElementById('nav-toggle');
    var sidebar = document.getElementById('sidebar-nav');
    var overlay = document.getElementById('sidebar-overlay');
    if (!btn || !sidebar) return;
    function openNav() { sidebar.classList.add('open'); if (overlay) overlay.classList.add('open'); }
    function closeNav() { sidebar.classList.remove('open'); if (overlay) overlay.classList.remove('open'); }
    btn.addEventListener('click', function() {
        sidebar.classList.contains('open') ? closeNav() : openNav();
    });
    if (overlay) overlay.addEventListener('click', closeNav);
    sidebar.querySelectorAll('a').forEach(function(a) {
        a.addEventListener('click', closeNav);
    });
})();
"""

    # Progressive disclosure — toggle collapsed layers
    layer_toggle_js = """
// --- Layer toggle buttons ---
(function() {
    'use strict';
    var layers = [
        {btn: 'toggle-actions', content: 'actions-content'},
        {btn: 'toggle-deep-dive', content: 'deep-dive-content'},
        {btn: 'toggle-appendix', content: 'appendix-content'}
    ];

    function expandLayer(contentId) {
        var content = document.getElementById(contentId);
        if (!content || content.style.display !== 'none') return;
        var cfg = layers.find(function(l) { return l.content === contentId; });
        if (!cfg) return;
        var btn = document.getElementById(cfg.btn);
        if (!btn) return;
        content.style.display = 'block';
        btn.setAttribute('aria-expanded', 'true');
        btn.classList.add('active');
    }

    function setupToggle(btnId, contentId) {
        var btn = document.getElementById(btnId);
        var content = document.getElementById(contentId);
        if (!btn || !content) return;
        var origText = btn.textContent;
        btn.addEventListener('click', function() {
            var expanded = content.style.display !== 'none';
            content.style.display = expanded ? 'none' : 'block';
            btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            btn.textContent = expanded ? origText : origText.replace(/^/, '\\u2212 ');
            btn.classList.toggle('active', !expanded);
            if (!expanded) {
                setTimeout(function() {
                    content.scrollIntoView({behavior: 'smooth', block: 'start'});
                }, 50);
            }
        });
    }
    layers.forEach(function(l) { setupToggle(l.btn, l.content); });

    // Sidebar links: expand parent layer if target is inside a collapsed one
    document.querySelectorAll('.sidebar a[href^=\"#\"]').forEach(function(a) {
        a.addEventListener('click', function(e) {
            var id = this.getAttribute('href').slice(1);
            var target = document.getElementById(id);
            if (!target) return;
            // Check if target is inside a collapsed layer
            layers.forEach(function(l) {
                var container = document.getElementById(l.content);
                if (container && container.contains(target) && container.style.display === 'none') {
                    expandLayer(l.content);
                }
            });
            // Scroll to target after brief delay for DOM to reflow
            setTimeout(function() {
                target.scrollIntoView({behavior: 'smooth', block: 'start'});
            }, 60);
            e.preventDefault();
        });
    });
})();
"""

    return base + FILTER_BAR_JS + sidebar_cleanup_js + sidebar_toggle_js + layer_toggle_js


# ---------------------------------------------------------------------------
# Sidebar navigation (A1)
# ---------------------------------------------------------------------------


def render_nav_bar(section_rag: dict[str, str] | None = None) -> str:
    """Render a minimal fixed sidebar with only high-level navigation."""
    rag = section_rag or {}

    def _rag(key: str) -> str:
        status = rag.get(key, "")
        if not status:
            return ""
        color = RAG_COLORS.get(status, "#6c757d")
        label = status.capitalize()
        esc = _html.escape(label, quote=True)
        return f"<span class='rag-dot' style='background:{color}' title='{esc}' aria-label='Status: {esc}'></span>"

    return (
        "<a href='#main-content' class='skip-link'>Skip to main content</a>"
        "<button class='nav-toggle' id='nav-toggle' aria-label='Open navigation' "
        "type='button'>&#9776;</button>"
        "<div class='sidebar-overlay' id='sidebar-overlay'></div>"
        "<nav class='sidebar' id='sidebar-nav' role='navigation' aria-label='Report sections'>"
        "<div class='sidebar-brand'>"
        "<span>DD Report</span>"
        "<span class='confidential'>Confidential</span>"
        "</div>"
        # Decision
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Decision</div>"
        f"<a href='#sec-executive'>{_rag('executive')} Verdict</a>"
        "<a href='#sec-action-items'>Action Items</a>"
        "</div>"
        # Domains
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Domains</div>"
        f"<a href='#sec-domain-legal'>{_rag('domain-legal')} Legal</a>"
        f"<a href='#sec-domain-finance'>{_rag('domain-finance')} Finance</a>"
        f"<a href='#sec-domain-commercial'>{_rag('domain-commercial')} Commercial</a>"
        f"<a href='#sec-domain-producttech'>{_rag('domain-producttech')} Product &amp; Tech</a>"
        f"<a href='#sec-domain-overview'>{_rag('cross_domain')} All Domains</a>"
        "</div>"
        # Analysis
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Analysis</div>"
        "<a href='#sec-financial'>Financial Impact</a>"
        f"<a href='#sec-valuation'>{_rag('valuation')} Valuation</a>"
        f"<a href='#sec-cross-domain'>{_rag('cross_domain')} Cross-Domain</a>"
        "</div>"
        # Evidence
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Evidence</div>"
        "<a href='#sec-subjects'>Entity Detail</a>"
        f"<a href='#sec-gaps'>{_rag('gaps')} Data Gaps</a>"
        "<a href='#sec-methodology'>Methodology</a>"
        "</div>"
        "<div class='sidebar-footer'>"
        "<button id='btn-presentation' class='presentation-btn' "
        "title='Toggle Presentation Mode' aria-label='Toggle Presentation Mode'>"
        "&#9654; Present</button>"
        "</div>"
        "</nav>"
        # Main wrapper
        "<div class='main-wrapper'>"
        "<div class='content' role='main' id='main-content'>"
    )
