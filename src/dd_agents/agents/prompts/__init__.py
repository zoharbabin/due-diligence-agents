"""Editable, packaged Markdown source-of-truth for built-in agent prompts.

The prose an M&A reviewer would want to read, audit, and fork — specialist
personas, domain guidance, search-column templates, synthesis and auto-config
prompts — lives here as Markdown rather than buried in Python string literals.

Layout::

    prompts/
      specialists/{legal,finance,…,esg}.md   # ## Role / ## Specialist Focus / ## Domain Guidance
      synthesis/{judge,executive_synthesis,…}.md
      search/templates/{change_of_control,…}.md
      auto_config/{entity_resolution,buyer_strategy,spa_extraction}.md

Loaded via :mod:`dd_agents.agents.prompts.loader`. Numbers are NOT written as
literals — they use ``{TFC_REVENUE_PCT}``-style placeholders resolved from
:mod:`dd_agents.agents.severity_thresholds` at load time, so severity thresholds
stay single-source. The non-removable safety floor is NOT here; it stays
code-enforced in :mod:`dd_agents.agents.prompt_constants`.
"""

from __future__ import annotations

from dd_agents.agents.prompts.loader import (
    BuiltinPrompt,
    load_builtin_specialist,
    load_named_prompt,
    load_search_templates,
    resolve_thresholds,
    split_on_marker,
)

__all__ = [
    "BuiltinPrompt",
    "load_builtin_specialist",
    "load_named_prompt",
    "load_search_templates",
    "resolve_thresholds",
    "split_on_marker",
]
