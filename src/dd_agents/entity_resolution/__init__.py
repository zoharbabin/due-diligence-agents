"""Entity resolution subpackage -- 6-pass cascading matcher with cache."""

from __future__ import annotations

from dd_agents.entity_resolution.matcher import EntityResolver
from dd_agents.entity_resolution.safe_name import customer_safe_name

# Convenience alias used by downstream modules (e.g. inventory.customers)
compute_safe_name = customer_safe_name

__all__ = [
    "EntityResolver",
    "compute_safe_name",
    "customer_safe_name",
]
