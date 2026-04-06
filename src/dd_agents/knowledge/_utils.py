"""Shared utilities for the knowledge package (Issue #178).

Small helpers used across multiple knowledge submodules. Centralised here
to avoid duplicate definitions and private-symbol cross-imports.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat()
