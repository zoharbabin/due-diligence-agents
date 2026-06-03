"""Shared persona opening lines for prompt assembly.

Several prompts across the codebase open with the same analyst/role
description. This module centralises those opening fragments as
``Final[str]`` constants so the wording stays consistent across call
sites. Each call site keeps its own distinct continuation inline; only
the shared opening is extracted here.

Extracting these is **behaviour-preserving**: the assembled prompt at
each call site remains byte-identical to before.
"""

from __future__ import annotations

from typing import Final

# Shared opening for the chunked legal analyzer prompts
# (search/analyzer.py). Each site appends its own distinct continuation
# (e.g. " reviewing subject contracts.", " resolving conflicting ...").
DD_LEGAL_ANALYST: Final[str] = "You are a meticulous legal due-diligence analyst"

# Shared opening for chat/query analyst prompts. Each site appends its
# own continuation (e.g. " reviewing the results of ...", ". Answer ...").
DD_ANALYST: Final[str] = "You are a due diligence analyst"

# NOTE: The buyer-strategy and SPA opening lines that formerly lived here as
# ``M_AND_A_STRATEGIST`` / ``M_AND_A_LAWYER_SPA`` now live in the editable prompt
# markdown (``agents/prompts/auto_config/buyer_strategy.md`` and
# ``spa_extraction.md``) — they were single-call-site openers, so the markdown is
# now their single source of truth.
