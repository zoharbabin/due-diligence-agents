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

DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

DOMAIN_DISPLAY: dict[str, str] = {
    "legal": "Legal",
    "finance": "Finance",
    "commercial": "Commercial",
    "producttech": "Product & Tech",
}

DOMAIN_COLORS: dict[str, str] = {
    "legal": "#4a90d9",
    "finance": "#2d8a4e",
    "commercial": "#7c3aed",
    "producttech": "#d97706",
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
        """Render a colored severity badge."""
        color = SEVERITY_COLORS.get(severity, "#6c757d")
        extra_cls = " sev-p1" if severity == "P1" else (" sev-p2" if severity == "P2" else "")
        return f"<span class='severity-badge{extra_cls}' style='background:{color}'>{_html.escape(severity)}</span>"

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
        p0 = sev.get("P0", 0)
        if p0 >= 3:
            return "Critical"
        if p0 > 0:
            return "High"
        p1 = sev.get("P1", 0)
        if p1 >= 3:
            return "High"
        if p1 > 0 or sev.get("P2", 0) >= 5:
            return "Medium"
        if sev.get("P2", 0) > 0:
            return "Low"
        if sev.get("P3", 0) > 0:
            return "Low"
        return "Clean"

    def _resolve_display_name(self, item: dict[str, Any]) -> str:
        """Resolve the display name for a finding/gap using CSN-first lookup.

        Looks up ``_customer_safe_name`` first (canonical key in display_names),
        then falls back to ``_customer``/``customer`` raw value.
        """
        csn = str(item.get("_customer_safe_name", ""))
        raw = str(item.get("_customer", item.get("customer", "")))
        if self.data:
            return self.data.display_names.get(csn, self.data.display_names.get(raw, raw))
        return raw

    @staticmethod
    def agent_to_domain(agent: str) -> str:
        """Map an agent name to one of the 4 domains."""
        agent = agent.lower().strip()
        if agent in DOMAIN_AGENTS:
            return agent
        if "legal" in agent:
            return "legal"
        if "financ" in agent:
            return "finance"
        if "commerc" in agent:
            return "commercial"
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
        severity = str(finding.get("severity", "P3"))
        color = SEVERITY_COLORS.get(severity, "#ccc")
        title = self.escape(str(finding.get("title", "Untitled")))
        display_name = self._resolve_display_name(finding)
        customer = self.escape(display_name)
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
            f"<div class='fc-meta'>Source: {customer} | Agent: {agent}</div>"
            f"</div>"
        )

    def render_finding_detail(self, finding: Any) -> str:
        """Render expanded finding detail with description, badges, and citations."""
        if not isinstance(finding, dict):
            return ""
        severity = str(finding.get("severity", "P3"))
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
        sr_parts = [f"{s}: {severity_counts.get(s, 0)}" for s in ("P0", "P1", "P2", "P3") if severity_counts.get(s, 0)]
        sr_text = self.escape(", ".join(sr_parts) or "No findings")
        parts: list[str] = [f"<div class='sev-bar' role='img' aria-label='Severity distribution: {sr_text}'>"]
        for s in ("P0", "P1", "P2", "P3"):
            pct = (severity_counts.get(s, 0) / total) * 100
            if pct > 0:
                parts.append(f"<span style='width:{pct:.1f}%;background:{SEVERITY_COLORS[s]}'></span>")
        parts.append("</div>")
        return "".join(parts)

    def render_category_group(self, category: str, findings: list[dict[str, Any]]) -> str:
        """Render a collapsible category group with findings grouped by customer."""
        sev_counts: dict[str, int] = defaultdict(int)
        for f in findings:
            sev_counts[f.get("severity", "P3")] += 1
        sev_str = self.escape(", ".join(f"{k}:{v}" for k, v in sorted(sev_counts.items()) if v > 0))

        parts: list[str] = [
            "<div class='category-group'>",
            f"<div class='category-header' tabindex='0' role='button' aria-expanded='false'>"
            f"<span><strong>{self.escape(category)}</strong> ({len(findings)} findings, {sev_str})</span>"
            f"<span class='arrow'>&#9654;</span></div>",
            "<div class='category-body'>",
        ]

        by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in findings:
            by_customer[str(f.get("_customer_safe_name", f.get("_customer", "Unknown")))].append(f)

        for cust, cust_findings in sorted(by_customer.items()):
            display = self.data.display_names.get(cust, cust) if self.data else cust
            parts.append(f"<h3>{self.escape(display)}</h3>")
            for f in cust_findings:
                parts.append(self.render_finding_card(f))
                parts.append(self.render_finding_detail(f))

        parts.extend(["</div>", "</div>"])
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# CSS (Issue #113: CSS variables, sidebar nav, alert boxes, two-column)
# ---------------------------------------------------------------------------


def render_css() -> str:
    """Return the full CSS for the report."""
    return """
/* CSS Custom Properties (E1) */
:root {
    --navy: #1a1a2e;
    --navy-light: #16213e;
    --red: #dc3545;
    --orange: #fd7e14;
    --yellow: #ffc107;
    --green: #28a745;
    --blue: #4a90d9;
    --purple: #7c3aed;
    --amber: #d97706;
    --gray: #6c757d;
    --gray-light: #a8b2d1;
    --gray-dark: #333;
    --bg-primary: #f4f5f7;
    --bg-secondary: #ffffff;
    --bg-tertiary: #e9ecef;
    --bg-hover: #f8f9fa;
    --text-primary: #1a1a2e;
    --text-secondary: #666;
    --text-muted: #999;
    --border-light: #e0e0e0;
    --border-medium: #dee2e6;
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.08);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.12);
    --sidebar-width: 240px;
    --header-height: 0px;
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
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; padding: 0; background: var(--bg-primary); color: var(--text-primary); line-height: 1.5; }

/* Sidebar Navigation (A1) */
.sidebar { position: fixed; top: 0; left: 0; width: var(--sidebar-width); height: 100vh;
           background: var(--navy); color: white; overflow-y: auto; z-index: 1000;
           padding: 0; display: flex; flex-direction: column; }
.sidebar-brand { padding: 20px 16px 12px; font-weight: 700; font-size: 0.95em;
                 color: white; border-bottom: 1px solid rgba(255,255,255,0.1);
                 display: flex; align-items: center; gap: 8px; }
.sidebar-brand .confidential { background: var(--red); color: white; font-size: 0.6em;
                                padding: 2px 6px; border-radius: 3px; font-weight: 600;
                                letter-spacing: 1px; text-transform: uppercase; }
.toc-group { padding: 8px 0; }
.toc-group-label { padding: 4px 16px; font-size: 0.7em; font-weight: 600;
                   text-transform: uppercase; letter-spacing: 0.8px; color: var(--gray-light);
                   opacity: 0.7; }
.sidebar a { display: flex; align-items: center; gap: 8px; color: var(--gray-light);
             text-decoration: none; padding: 6px 16px; font-size: 0.82em;
             transition: color 0.2s, background 0.2s; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
.sidebar a:hover, .sidebar a.active { color: white; background: rgba(255,255,255,0.08); }
.sidebar a .rag-dot { flex-shrink: 0; }

/* RAG dots */
.rag-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
           flex-shrink: 0; }

/* Content area (shifted right for sidebar) */
.main-wrapper { margin-left: var(--sidebar-width); }

/* Content wrapper */
.content { max-width: 1200px; margin: 0 auto; padding: 24px; }

/* Report sections */
.report-section { margin-bottom: 32px; }
.report-section > h2 { color: var(--text-primary); font-size: 1.3em;
                        border-bottom: 2px solid var(--text-primary);
                        padding-bottom: 8px; margin-bottom: 16px; }

/* Deal header */
.deal-header { background: linear-gradient(135deg, var(--navy), var(--navy-light)); color: white;
               padding: 32px; border-radius: 12px; margin-bottom: 24px; }
.deal-header h1 { margin: 0 0 8px; font-size: 1.8em; }
.deal-header .deal-meta { color: var(--gray-light); font-size: 0.95em; }
.deal-header .risk-badge { display: inline-block; padding: 6px 20px; border-radius: 20px;
                           font-weight: 700; font-size: 1.1em; margin-top: 12px; }
.deal-header .run-id { color: #6c7a96; font-size: 0.8em; margin-top: 8px; }
.deal-header .timestamp { color: #6c7a96; font-size: 0.75em; margin-top: 4px; }

/* Key metrics strip */
.metrics-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                 gap: 12px; margin-bottom: 24px; }
.metric-card { background: var(--bg-secondary); border-radius: 8px; padding: 16px;
               text-align: center; box-shadow: var(--shadow-sm); }
.metric-card .value { font-size: 1.8em; font-weight: 700; }
.metric-card .label { color: var(--text-secondary); font-size: 0.8em; text-transform: uppercase;
                      letter-spacing: 0.5px; }

/* Alert boxes (C1) */
.alert { border-radius: 8px; padding: 16px 20px; margin: 16px 0;
         border-left: 5px solid; }
.alert-title { font-weight: 700; font-size: 1em; margin-bottom: 4px; }
.alert-body { font-size: 0.9em; line-height: 1.5; }
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

/* Wolf pack */
.wolf-pack { margin-bottom: 24px; }
.wolf-pack h2 { color: var(--red); }
.wolf-card { background: var(--bg-secondary); border-left: 5px solid; border-radius: 4px 8px 8px 4px;
             padding: 16px 20px; margin-bottom: 12px;
             box-shadow: var(--shadow-sm); }
.wolf-card .wolf-title { font-weight: 700; font-size: 1.05em; margin-bottom: 4px; }
.wolf-card .wolf-meta { color: var(--text-secondary); font-size: 0.85em; }
.wolf-card .wolf-quote { background: var(--bg-hover); padding: 8px 12px; margin-top: 8px;
                          border-radius: 4px; font-style: italic; color: #555; font-size: 0.9em; }

/* Heatmap */
.heatmap { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.heatmap-cell { background: var(--bg-secondary); border-radius: 8px; padding: 20px;
                text-align: center; box-shadow: var(--shadow-sm); cursor: pointer;
                transition: transform 0.15s, box-shadow 0.15s; border-top: 4px solid; }
.heatmap-cell:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
.heatmap-cell .domain-name { font-weight: 700; font-size: 1.1em; }
.heatmap-cell .domain-risk { font-size: 0.9em; margin: 6px 0; font-weight: 600; }
.heatmap-cell .domain-counts { font-size: 0.8em; color: var(--text-secondary); }

/* Severity cards (E2) */
.severity-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }
.severity-card { border-radius: 8px; padding: 16px; text-align: center;
                 box-shadow: var(--shadow-sm); }
.severity-card .sev-count { font-size: 2em; font-weight: 700; }
.severity-card .sev-label { font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.5px; }

/* Domain sections */
.domain-section { background: var(--bg-secondary); border-radius: 8px; margin-bottom: 20px;
                  box-shadow: var(--shadow-sm); overflow: hidden; }
.domain-header { padding: 16px 24px; cursor: pointer; display: flex;
                 justify-content: space-between; align-items: center;
                 border-left: 5px solid; transition: background 0.15s; }
.domain-header:hover { background: var(--bg-hover); }
.domain-header h2 { margin: 0; font-size: 1.15em; }
.domain-body { padding: 0 24px 20px; display: none; }
.domain-body.open { display: block; }

/* Severity distribution bar */
.sev-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 8px 0; }
.sev-bar span { display: block; }

/* Category groups */
.category-group { border: 1px solid var(--bg-tertiary); border-radius: 6px; margin: 10px 0;
                  overflow: hidden; }
.category-header { padding: 10px 16px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center; background: var(--bg-hover); }
.category-header:hover { background: #f0f1f3; }
.category-body { padding: 12px 16px; display: none; }
.category-body.open { display: block; }

/* Customer sections */
.customer-section { background: var(--bg-secondary); border-radius: 8px; margin: 12px 0;
                    box-shadow: var(--shadow-sm); overflow: hidden; }
.customer-header { padding: 12px 20px; cursor: pointer; display: flex;
                   justify-content: space-between; align-items: center;
                   background: var(--bg-tertiary); transition: background 0.15s; }
.customer-header:hover { background: var(--border-medium); }
.customer-body { padding: 16px 20px; display: none; }
.customer-body.open { display: block; }

/* Finding cards */
.finding-card { border-left: 4px solid #ccc; padding: 10px 14px; margin: 8px 0;
                background: #fafafa; border-radius: 0 6px 6px 0; cursor: pointer;
                transition: background 0.15s; }
.finding-card:hover { background: #f0f0f0; }
.finding-card .fc-title { font-weight: 600; }
.finding-card .fc-meta { color: var(--text-secondary); font-size: 0.85em; margin-top: 2px; }
.conf-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-left: 4px;
  vertical-align: middle; }
.conf-high { background: #198754; }
.conf-medium { background: #fd7e14; }
.conf-low { background: #dc3545; }
.finding-detail { display: none; padding: 12px 14px; background: var(--bg-hover);
                  border-left: 4px solid #ccc; margin: 0 0 8px; border-radius: 0 0 6px 0; }
.finding-detail.open { display: block; }
.finding-detail .fd-description { margin-bottom: 8px; }
.finding-detail .fd-badges { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }

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
.rec-card { background: var(--bg-secondary); border-radius: 8px; padding: 16px 20px;
            margin: 12px 0; box-shadow: var(--shadow-sm); border-left: 5px solid; }
.rec-timeline { font-size: 0.75em; font-weight: 600; text-transform: uppercase;
                letter-spacing: 0.5px; padding: 2px 8px; border-radius: 10px;
                display: inline-block; margin-bottom: 4px; }
.rec-title { font-weight: 700; font-size: 1em; margin: 4px 0; }
.rec-desc { font-size: 0.9em; color: var(--text-secondary); line-height: 1.5; }

/* Customer summary table */
.customer-table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.9em; }
.customer-table th, .customer-table td { padding: 10px 14px; border-bottom: 1px solid var(--border-medium);
                                          text-align: left; }
.customer-table th { background: var(--bg-tertiary); font-weight: 600; font-size: 0.85em;
                     text-transform: uppercase; letter-spacing: 0.3px; }
.customer-table tr:hover { background: var(--bg-hover); }

/* Health tier badges */
.tier-badge { display: inline-block; padding: 2px 10px; border-radius: 12px;
              font-size: 0.75em; font-weight: 600; }
.tier-1 { background: var(--sev-p0-bg); color: var(--red); border: 1px solid var(--red); }
.tier-2 { background: var(--sev-p1-bg); color: var(--orange); border: 1px solid var(--orange); }
.tier-3 { background: var(--sev-p3-bg); color: var(--gray); border: 1px solid var(--gray); }

/* Citations */
.citation { background: #f0f0f0; padding: 10px 14px; margin: 6px 0; border-radius: 6px;
            font-size: 0.9em; border-left: 3px solid var(--gray-light); }
.citation .source { font-weight: 600; color: var(--text-primary); }
.citation .location { color: var(--text-secondary); font-size: 0.85em; }
.citation .quote { font-style: italic; color: #555; margin-top: 4px; padding: 6px 10px;
                   background: #e8e8e8; border-radius: 4px; display: block; }

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
table.sortable { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 0.9em; }
table.sortable th, table.sortable td { padding: 8px 12px; border: 1px solid var(--border-medium);
                                        text-align: left; }
table.sortable th { background: var(--bg-tertiary); cursor: pointer; user-select: none;
                    white-space: nowrap; }
table.sortable th:hover { background: var(--border-medium); }
table.sortable th::after { content: ' \\2195'; color: #aaa; font-size: 0.8em; }

/* Arrow toggle */
.arrow { font-size: 0.8em; transition: transform 0.2s; display: inline-block; }
.arrow.open { transform: rotate(90deg); }

/* Responsive */
@media (max-width: 900px) {
    .heatmap, .severity-cards { grid-template-columns: repeat(2, 1fr); }
    .metrics-strip { grid-template-columns: repeat(2, 1fr); }
    .gap-summary-grid, .two-col { grid-template-columns: 1fr; }
    .sidebar { display: none; }
    .main-wrapper { margin-left: 0; }
}
@media (max-width: 600px) {
    .heatmap, .severity-cards { grid-template-columns: 1fr; }
    .content { padding: 12px; }
}

/* Waterfall chart (Issue #102) */
.waterfall { margin: 16px 0; }
.waterfall-row { display: flex; align-items: center; margin-bottom: 6px; }
.waterfall-label { width: 220px; flex-shrink: 0; font-size: 0.85em; padding-right: 12px;
                   text-align: right; }
.waterfall-bar-container { flex: 1; height: 32px; position: relative;
                           background: var(--bg-light, #f8f9fa); border-radius: 4px; }
.waterfall-bar { height: 100%; border-radius: 4px; display: flex; align-items: center;
                 padding: 0 8px; font-size: 0.8em; color: #fff; white-space: nowrap;
                 overflow: hidden; position: absolute; top: 0; }
.waterfall-bar--total { background: var(--navy, #1a365d); }
.waterfall-bar--risk { background: var(--severity-p1, #d63384); }
.waterfall-bar--adjusted { background: var(--severity-p3, #198754); }
.data-note { font-size: 0.8em; color: #6c757d; margin-top: 16px; font-style: italic; }

/* Print mode (E5) */
@page { margin: 2cm 1.5cm; }
@media print {
    .sidebar, .skip-link { display: none !important; }
    .main-wrapper { margin-left: 0 !important; }
    .domain-body, .customer-body, .category-body, .finding-detail { display: block !important; }
    body { background: white; font-size: 11pt; orphans: 3; widows: 3; }
    .deal-header { background: var(--navy) !important; -webkit-print-color-adjust: exact;
                   print-color-adjust: exact; }
    .severity-badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .sev-bar span { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .rag-dot { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .alert { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .content { max-width: 100%; padding: 0; }
    .heatmap-cell, .metric-card, .finding-card, .wolf-card, .customer-section,
    .domain-section, .category-group, .citation, table.sortable,
    .alert, .rec-card { break-inside: avoid; }
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
.domain-header:focus-visible, .customer-header:focus-visible {
    outline: 2px solid var(--blue); outline-offset: -2px;
    box-shadow: 0 0 0 3px rgba(74,144,217,0.3); }

/* Utility */
.hidden { display: none !important; }
.text-muted { color: var(--text-secondary); }
.text-small { font-size: 0.85em; }
.mt-8 { margin-top: 8px; }
.mb-8 { margin-bottom: 8px; }
.mb-16 { margin-bottom: 16px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
"""


# ---------------------------------------------------------------------------
# JS (Issue #113: sidebar scroll tracking)
# ---------------------------------------------------------------------------


def render_js() -> str:
    """Return the full JavaScript for the report."""
    return """
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
    setupToggles('.customer-header', '.customer-body');
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
})();
"""


# ---------------------------------------------------------------------------
# Sidebar navigation (A1)
# ---------------------------------------------------------------------------


def render_nav_bar(section_rag: dict[str, str] | None = None) -> str:
    """Render the fixed left sidebar navigation with RAG indicators."""
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
        "<nav class='sidebar' role='navigation' aria-label='Report sections'>"
        "<div class='sidebar-brand'>"
        "<span>DD Report</span>"
        "<span class='confidential'>Confidential</span>"
        "</div>"
        # Deal Assessment
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Deal Assessment</div>"
        "<a href='#sec-red-flags'>Red Flag Assessment</a>"
        f"<a href='#sec-executive'>{_rag('executive')} Executive Summary</a>"
        f"<a href='#sec-wolf-pack'>{_rag('executive')} Deal Breakers</a>"
        "<a href='#sec-key-risks'>Key Risks</a>"
        "</div>"
        # Risk Analysis
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Risk Analysis</div>"
        "<a href='#sec-financial'>Financial Impact</a>"
        "<a href='#sec-saas'>SaaS Health Metrics</a>"
        f"<a href='#sec-valuation'>{_rag('valuation')} Valuation Bridge</a>"
        "<a href='#sec-p0-table'>P0 Critical Issues</a>"
        "<a href='#sec-p1-table'>P1 High Issues</a>"
        f"<a href='#sec-heatmap'>Risk Heatmap</a>"
        "</div>"
        # Workstream Detail
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Workstream Detail</div>"
        f"<a href='#sec-coc'>{_rag('coc')} Change of Control</a>"
        f"<a href='#sec-tfc'>{_rag('tfc')} TfC Revenue</a>"
        f"<a href='#sec-privacy'>{_rag('privacy')} Data Privacy</a>"
        f"<a href='#sec-domain-legal'>{_rag('domain-legal')} Legal</a>"
        f"<a href='#sec-domain-finance'>{_rag('domain-finance')} Finance</a>"
        f"<a href='#sec-domain-commercial'>{_rag('domain-commercial')} Commercial</a>"
        f"<a href='#sec-domain-producttech'>{_rag('domain-producttech')} Product&amp;Tech</a>"
        f"<a href='#sec-discount'>{_rag('discount')} Discount &amp; Pricing</a>"
        f"<a href='#sec-renewal'>{_rag('renewal')} Renewal Analysis</a>"
        f"<a href='#sec-compliance'>{_rag('compliance')} Compliance Risk</a>"
        f"<a href='#sec-entity'>{_rag('entity')} Entity Distribution</a>"
        f"<a href='#sec-timeline'>{_rag('timeline')} Contract Timeline</a>"
        "</div>"
        # Portfolio
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Portfolio</div>"
        "<a href='#sec-health'>Entity Health</a>"
        f"<a href='#sec-liability'>{_rag('liability')} Liability</a>"
        f"<a href='#sec-ip-risk'>{_rag('ip_risk')} IP Risk</a>"
        f"<a href='#sec-cross-domain'>{_rag('cross_domain')} Cross-Domain</a>"
        f"<a href='#sec-xref'>{_rag('xref')} Data Reconciliation</a>"
        "</div>"
        # Actions
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Actions</div>"
        "<a href='#sec-recommendations'>Recommendations</a>"
        "<a href='#sec-integration'>Integration Playbook</a>"
        "<a href='#sec-gov-graph'>Governance Graph</a>"
        "</div>"
        # Appendix (collapsed by default)
        "<div class='toc-group'>"
        "<div class='toc-group-label'>Appendix</div>"
        f"<a href='#sec-gaps'>{_rag('gaps')} Incomplete Data</a>"
        "<a href='#sec-customers'>Entity Detail</a>"
        "<a href='#sec-methodology'>Methodology</a>"
        f"<a href='#sec-governance'>{_rag('governance')} Data Quality</a>"
        "<a href='#sec-quality'>Quality Audit</a>"
        "<a href='#sec-audit-checks'>QA Checks</a>"
        "</div>"
        "</nav>"
        # Main wrapper
        "<div class='main-wrapper'>"
        "<div class='content' role='main' id='main-content'>"
    )
