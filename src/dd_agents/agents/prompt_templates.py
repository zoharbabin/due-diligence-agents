"""Search prompt templates library (Issue #141).

Ready-to-use legal analysis prompt templates for the ``dd-agents search``
command. Each template contains a set of columns (questions) designed for
specific M&A due diligence provisions.

Based on Addleshaw Goddard RAG Report (2024) — AG-4: provision-specific
prompts outperform generic extraction.
"""

from __future__ import annotations

import json
from typing import Any

from dd_agents.agents.prompts.loader import load_search_templates

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
#
# Source of truth is the editable markdown at
# ``agents/prompts/search/templates/*.md`` (front-matter id/name/description +
# ``### Column`` blocks). Loaded once here so M&A reviewers edit markdown, not
# Python, while ``get_template``/``list_templates``/``export_template`` are
# unchanged.
PROMPT_TEMPLATES: dict[str, dict[str, Any]] = load_search_templates()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_template(name: str) -> dict[str, Any] | None:
    """Return a template by name, or None if not found."""
    return PROMPT_TEMPLATES.get(name)


def list_templates() -> list[str]:
    """Return all template names."""
    return list(PROMPT_TEMPLATES.keys())


def export_template(name: str) -> str:
    """Export a template as JSON string ready for ``dd-agents search``."""
    tpl = PROMPT_TEMPLATES.get(name)
    if tpl is None:
        raise KeyError(f"Unknown template: {name}")
    return json.dumps(tpl, indent=2)
