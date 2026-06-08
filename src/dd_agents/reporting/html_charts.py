"""Inline SVG chart generators for HTML reports (Issue #199).

All charts are pure SVG strings — no external dependencies, no temp files.
Each function returns an SVG string or empty string if data is insufficient.

Accessibility: every SVG includes role="img", aria-label, <title>, and <desc>.
Print-safe: all use viewBox for responsive scaling.
Colorblind-safe: combines color with text indicators (P0:▲, P1:●, P2:◆, P3:○).
"""

from __future__ import annotations

import html as _html
import math
import re as _re
from typing import Any

from dd_agents.reporting.html_base import SEVERITY_COLORS
from dd_agents.utils.constants import ALL_SEVERITIES, SEVERITY_P0, SEVERITY_P1, SEVERITY_P2, SEVERITY_P3


def _esc(text: str) -> str:
    """Escape text for safe SVG/HTML embedding."""
    return _html.escape(text, quote=True)


_SAFE_COLOR_RE = _re.compile(r"^#[0-9a-fA-F]{3,8}$|^rgb\(\d{1,3},\s*\d{1,3},\s*\d{1,3}\)$")


def _safe_color(color: str) -> str:
    """Validate a color string; return fallback if suspicious."""
    if _SAFE_COLOR_RE.match(color):
        return color
    return "#ccc"


# Text indicators for colorblind accessibility
SEVERITY_INDICATORS: dict[str, str] = {
    SEVERITY_P0: "▲",  # ▲
    SEVERITY_P1: "●",  # ●
    SEVERITY_P2: "◆",  # ◆
    SEVERITY_P3: "○",  # ○
}


def render_donut_chart(
    segments: dict[str, int],
    size: int = 180,
    title: str = "Severity Distribution",
) -> str:
    """Render a donut chart showing severity distribution.

    Parameters
    ----------
    segments:
        Mapping of severity label (P0, P1, P2, P3) to count.
    size:
        SVG viewBox size in logical pixels.
    title:
        Accessible chart title.

    Returns empty string if all segments are zero.
    """
    total = sum(segments.values())
    if total == 0:
        return ""

    safe_title = _esc(title)
    cx = size / 2
    cy = size / 2
    radius = size * 0.35
    inner_radius = size * 0.22

    paths: list[str] = []
    start_angle = -90.0  # Start at 12 o'clock

    for sev in ALL_SEVERITIES:
        count = segments.get(sev, 0)
        if count == 0:
            continue
        pct = count / total
        sweep = pct * 360

        # Arc calculation
        end_angle = start_angle + sweep
        start_rad = math.radians(start_angle)
        end_rad = math.radians(end_angle)

        # Outer arc
        x1 = cx + radius * math.cos(start_rad)
        y1 = cy + radius * math.sin(start_rad)
        x2 = cx + radius * math.cos(end_rad)
        y2 = cy + radius * math.sin(end_rad)

        # Inner arc (reverse)
        x3 = cx + inner_radius * math.cos(end_rad)
        y3 = cy + inner_radius * math.sin(end_rad)
        x4 = cx + inner_radius * math.cos(start_rad)
        y4 = cy + inner_radius * math.sin(start_rad)

        large_arc = 1 if sweep > 180 else 0
        color = SEVERITY_COLORS.get(sev, "#ccc")

        if pct >= 0.999:
            # Full circle — stroke centered on midpoint so ring matches arc segments
            mid_r = (radius + inner_radius) / 2
            paths.append(
                f"<circle cx='{cx}' cy='{cy}' r='{mid_r:.1f}' fill='none' "
                f"stroke='{color}' stroke-width='{radius - inner_radius:.1f}' />"
            )
        else:
            path = (
                f"M {x1:.1f} {y1:.1f} "
                f"A {radius:.1f} {radius:.1f} 0 {large_arc} 1 {x2:.1f} {y2:.1f} "
                f"L {x3:.1f} {y3:.1f} "
                f"A {inner_radius:.1f} {inner_radius:.1f} 0 {large_arc} 0 {x4:.1f} {y4:.1f} Z"
            )
            paths.append(f"<path d='{path}' fill='{color}' />")

        start_angle = end_angle

    # Center text
    paths.append(
        f"<text x='{cx}' y='{cy - 6}' text-anchor='middle' font-size='24' font-weight='700' fill='#333'>{total}</text>"
    )
    paths.append(f"<text x='{cx}' y='{cy + 14}' text-anchor='middle' font-size='11' fill='#666'>findings</text>")

    # Legend
    legend_y = size + 10
    legend_items: list[str] = []
    for i, sev in enumerate(ALL_SEVERITIES):
        count = segments.get(sev, 0)
        if count == 0:
            continue
        lx = 10 + (i % 2) * (size / 2)
        ly = legend_y + (i // 2) * 18
        color = SEVERITY_COLORS.get(sev, "#ccc")
        indicator = SEVERITY_INDICATORS.get(sev, "")
        legend_items.append(
            f"<text x='{lx}' y='{ly}' font-size='11' fill='{color}' font-weight='600'>{indicator} {sev}: {count}</text>"
        )

    legend_height = 18 * math.ceil(sum(1 for s in ALL_SEVERITIES if segments.get(s, 0) > 0) / 2) + 10
    total_height = size + legend_height + 10

    svg = (
        f"<svg viewBox='0 0 {size} {total_height}' "
        f"width='{size}' role='img' aria-label='{safe_title}' "
        f"style='max-width:100%;height:auto'>"
        f"<title>{safe_title}</title>"
        f"<desc>Donut chart: {', '.join(f'{s}={segments.get(s, 0)}' for s in ALL_SEVERITIES)}</desc>"
        f"{''.join(paths)}"
        f"{''.join(legend_items)}"
        f"</svg>"
    )
    return svg


def render_heatmap_grid(
    cells: list[dict[str, Any]],
    columns: int = 3,
    title: str = "Domain Risk Heatmap",
) -> str:
    """Render an SVG heatmap grid with labeled cells.

    Parameters
    ----------
    cells:
        List of dicts with keys: label, value, color.
    columns:
        Number of columns in the grid.
    title:
        Accessible chart title.

    Returns empty string if cells is empty.
    """
    if not cells:
        return ""

    safe_title = _esc(title)
    cell_w = 120
    cell_h = 60
    padding = 4
    rows = math.ceil(len(cells) / columns)
    width = columns * (cell_w + padding) + padding
    height = rows * (cell_h + padding) + padding

    rects: list[str] = []
    for i, cell in enumerate(cells):
        col = i % columns
        row = i // columns
        x = padding + col * (cell_w + padding)
        y = padding + row * (cell_h + padding)
        label = _esc(str(cell.get("label", "")))
        value = _esc(str(cell.get("value", "")))
        color = _safe_color(str(cell.get("color", "#f0f0f0")))

        rects.append(f"<rect x='{x}' y='{y}' width='{cell_w}' height='{cell_h}' rx='4' fill='{color}' opacity='0.2' />")
        rects.append(
            f"<text x='{x + cell_w / 2}' y='{y + 24}' text-anchor='middle' "
            f"font-size='10' font-weight='600' fill='#333'>{label}</text>"
        )
        rects.append(
            f"<text x='{x + cell_w / 2}' y='{y + 44}' text-anchor='middle' "
            f"font-size='14' font-weight='700' fill='{color}'>{value}</text>"
        )

    svg = (
        f"<svg viewBox='0 0 {width} {height}' "
        f"width='{width}' role='img' aria-label='{safe_title}' "
        f"style='max-width:100%;height:auto'>"
        f"<title>{safe_title}</title>"
        f"<desc>Heatmap grid with {len(cells)} cells</desc>"
        f"{''.join(rects)}"
        f"</svg>"
    )
    return svg


def render_waterfall_chart(
    start_value: float,
    deductions: list[dict[str, Any]],
    width: int = 600,
    title: str = "Financial Impact Waterfall",
    end_value: float | None = None,
) -> str:
    """Render an SVG waterfall chart showing financial deductions.

    Parameters
    ----------
    start_value:
        Starting value (total ARR/revenue).
    deductions:
        List of dicts with keys: label, amount (positive = deduction).
    width:
        SVG width in logical pixels.
    title:
        Accessible chart title.
    end_value:
        Authoritative final ("Adjusted") value. Use this when the per-category
        deduction amounts may overlap (e.g. one subject at risk across two
        categories) so that summing them would double-count: pass the
        independently de-duplicated total here and it drives the final bar and
        clamps the intermediate running value. When ``None`` the final value is
        the sequential ``start_value - sum(deductions)``.

    Returns empty string if start_value is zero or no deductions.
    """
    if start_value <= 0 or not deductions:
        return ""

    # Floor the running total at the authoritative de-duped end value (if given)
    # so overlapping category deductions never drive the chart below the truth.
    running_floor = max(0.0, end_value) if end_value is not None else 0.0

    safe_title = _esc(title)
    bar_height = 28
    spacing = 8
    label_width = 180
    chart_width = width - label_width - 20
    valid_deductions = [d for d in deductions if float(d.get("amount", 0)) > 0]
    n_bars = len(valid_deductions) + 2  # start + valid deductions + end
    height = n_bars * (bar_height + spacing) + 20

    running = start_value
    bars: list[str] = []
    y = 10

    # Start bar
    bars.append(
        f"<text x='{label_width - 8}' y='{y + bar_height / 2 + 4}' "
        f"text-anchor='end' font-size='11' fill='#333'>Total Revenue</text>"
    )
    bars.append(f"<rect x='{label_width}' y='{y}' width='{chart_width}' height='{bar_height}' rx='3' fill='#1a1a2e' />")
    bars.append(
        f"<text x='{label_width + 8}' y='{y + bar_height / 2 + 4}' "
        f"font-size='11' fill='white'>${start_value:,.0f}</text>"
    )
    y += bar_height + spacing

    # Deductions
    for ded in deductions:
        label = _esc(str(ded.get("label", ""))[:30])
        amount = float(ded.get("amount", 0))
        if amount <= 0:
            continue

        remaining_pct = max(0, (running - amount) / start_value)
        deduction_pct = min(amount / start_value, running / start_value)
        remaining_w = remaining_pct * chart_width
        deduction_w = deduction_pct * chart_width

        bars.append(
            f"<text x='{label_width - 8}' y='{y + bar_height / 2 + 4}' "
            f"text-anchor='end' font-size='10' fill='#666'>{label}</text>"
        )
        # Remaining portion
        if remaining_w > 0:
            bars.append(
                f"<rect x='{label_width}' y='{y}' width='{remaining_w:.1f}' "
                f"height='{bar_height}' fill='#1a1a2e' opacity='0.25' />"
            )
        # Deduction portion
        bars.append(
            f"<rect x='{label_width + remaining_w:.1f}' y='{y}' "
            f"width='{max(deduction_w, 2):.1f}' height='{bar_height}' "
            f"rx='0' fill='#fd7e14' />"
        )
        if deduction_w > 50:
            bars.append(
                f"<text x='{label_width + remaining_w + 6:.1f}' y='{y + bar_height / 2 + 4}' "
                f"font-size='10' fill='white'>-${amount:,.0f}</text>"
            )

        running = max(running_floor, running - amount)
        y += bar_height + spacing

    # End bar (adjusted value). Prefer the authoritative de-duped end value.
    final_value = max(0.0, end_value) if end_value is not None else running
    end_w = max(final_value / start_value * chart_width, 2)
    bars.append(
        f"<text x='{label_width - 8}' y='{y + bar_height / 2 + 4}' "
        f"text-anchor='end' font-size='11' font-weight='600' fill='#333'>Adjusted</text>"
    )
    bars.append(f"<rect x='{label_width}' y='{y}' width='{end_w:.1f}' height='{bar_height}' rx='3' fill='#28a745' />")
    bars.append(
        f"<text x='{label_width + 8}' y='{y + bar_height / 2 + 4}' "
        f"font-size='11' fill='white'>${final_value:,.0f}</text>"
    )

    svg = (
        f"<svg viewBox='0 0 {width} {height}' "
        f"width='{width}' role='img' aria-label='{safe_title}' "
        f"style='max-width:100%;height:auto'>"
        f"<title>{safe_title}</title>"
        f"<desc>Waterfall chart starting at ${start_value:,.0f} with "
        f"{len(valid_deductions)} deductions</desc>"
        f"{''.join(bars)}"
        f"</svg>"
    )
    return svg


def render_timeline_chart(
    events: list[dict[str, Any]],
    width: int = 700,
    title: str = "Critical Dates Timeline",
) -> str:
    """Render a horizontal timeline chart of critical dates.

    Parameters
    ----------
    events:
        List of dicts with keys: label, date (str), severity (optional).
    width:
        SVG width in logical pixels.
    title:
        Accessible chart title.

    Returns empty string if no events.
    """
    if not events:
        return ""

    safe_title = _esc(title)
    capped_events = events[:12]
    n = len(capped_events)
    height = 80 + n * 24
    line_y = 40
    padding = 60

    parts: list[str] = []

    # Timeline line
    parts.append(
        f"<line x1='{padding}' y1='{line_y}' x2='{width - padding}' y2='{line_y}' stroke='#dee2e6' stroke-width='2' />"
    )

    # Events distributed evenly
    for i, event in enumerate(capped_events):
        label = _esc(str(event.get("label", ""))[:35])
        date = _esc(str(event.get("date", "")))
        sev = str(event.get("severity", SEVERITY_P3))
        color = SEVERITY_COLORS.get(sev, "#6c757d")

        x = padding + (i / max(n - 1, 1)) * (width - 2 * padding) if n > 1 else width / 2
        # Alternate above/below
        text_y = line_y - 16 if i % 2 == 0 else line_y + 28

        # Dot
        parts.append(f"<circle cx='{x:.1f}' cy='{line_y}' r='5' fill='{color}' />")
        # Label
        parts.append(f"<text x='{x:.1f}' y='{text_y}' text-anchor='middle' font-size='9' fill='#333'>{label}</text>")
        # Date
        date_y = text_y + 12 if i % 2 == 0 else text_y - 12
        parts.append(f"<text x='{x:.1f}' y='{date_y}' text-anchor='middle' font-size='8' fill='#999'>{date}</text>")

    svg = (
        f"<svg viewBox='0 0 {width} {height}' "
        f"width='{width}' role='img' aria-label='{safe_title}' "
        f"style='max-width:100%;height:auto'>"
        f"<title>{safe_title}</title>"
        f"<desc>Timeline with {n} events</desc>"
        f"{''.join(parts)}"
        f"</svg>"
    )
    return svg
