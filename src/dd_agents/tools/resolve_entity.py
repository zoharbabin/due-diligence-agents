"""resolve_entity MCP tool.

Checks the entity resolution cache for a given name and returns the
canonical name, match method, and confidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def resolve_entity(
    name: str,
    cache_path: str | Path,
) -> dict[str, Any]:
    """Look up *name* in the entity resolution cache.

    The cache file is a JSON file with an ``entries`` dict mapping
    variant names to objects with ``canonical``, ``match_pass``,
    ``match_type``, and ``confidence`` fields.

    Args:
        name: The entity name to look up.
        cache_path: Path to the ``entity_resolution_cache.json`` file.

    Returns:
        ``{"canonical": str, "match_pass": ..., "match_type": ..., "confidence": ...}``
        if found, or ``{"status": "unresolved", "name": str}`` otherwise.
    """
    cache_file = Path(cache_path)

    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"status": "unresolved", "name": name}

        entries = cache.get("entries", {})
        if name in entries:
            entry = entries[name]
            return {
                "canonical": entry.get("canonical", name),
                "match_pass": entry.get("match_pass"),
                "match_type": entry.get("match_type"),
                "confidence": entry.get("confidence"),
            }

    return {"status": "unresolved", "name": name}
