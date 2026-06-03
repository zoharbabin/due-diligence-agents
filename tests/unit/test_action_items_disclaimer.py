"""Unconditional AI-assisted disclosure in the Action Items section (audit §1.3/§8.2).

The advisory disclaimer must appear in the report even when there are zero
recommendations (empty material findings, no narrative).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dd_agents.reporting.html_action_items import ActionItemsRenderer


def _renderer(*, material: list[Any] | None = None, narrative: Any = None) -> ActionItemsRenderer:
    data = SimpleNamespace(material_findings=material or [], narrative=narrative)
    return ActionItemsRenderer(data=data, merged_data={}, config={})  # type: ignore[arg-type]


def test_disclaimer_renders_with_zero_recommendations() -> None:
    html = _renderer(material=[], narrative=None).render()
    assert html != ""
    assert "sec-action-items" in html
    assert "Advisory Notice" in html
    assert "AI-assisted analysis — verify with qualified advisors" in html


def test_disclaimer_renders_when_material_yields_no_recommendations() -> None:
    # Findings present but none match a recommendation template → still disclaim.
    bogus = [
        {
            "severity": "P3",
            "title": "zzz no template match",
            "description": "nothing actionable here",
            "agent": "legal",
            "category": "uncategorized",
            "citations": [],
        }
    ]
    html = _renderer(material=bogus, narrative=None).render()
    assert "Advisory Notice" in html
    assert "AI-assisted analysis — verify with qualified advisors" in html
