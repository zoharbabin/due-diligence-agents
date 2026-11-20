"""Adapters for the official sanctions lists (Issue #274).

Each adapter module exposes ``SOURCE_ID``, ``LABEL``, ``URL`` and a pure
``parse(raw: bytes) -> (entries, published_iso_date)``. :data:`SOURCES` maps each
source id to a :class:`Source` built from those module attributes.

To add a source: write the module, then add it to ``_MODULES`` below. Check the
publisher's terms first. A source whose terms forbid automated download or local
derived indexes, or that needs a per-user token, does not belong here. The UN
Security Council list is left out for this reason (its site terms allow
"personal, non-commercial use, without any right to ... compile or create
derivative works"). The UK and EU lists carry the UN designations.
"""

from __future__ import annotations

from dd_agents.screening.sources import csl, eu, ofac, uk
from dd_agents.screening.sources.base import Source, SourceParseError

_MODULES = (ofac, csl, uk, eu)

SOURCES: dict[str, Source] = {
    module.SOURCE_ID: Source(source_id=module.SOURCE_ID, label=module.LABEL, url=module.URL, parse=module.parse)
    for module in _MODULES
}

__all__ = ["SOURCES", "Source", "SourceParseError"]
