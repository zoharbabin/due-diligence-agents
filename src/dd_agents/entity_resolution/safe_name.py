"""Thin wrapper re-exporting name utilities for entity resolution convenience.

Delegates to ``dd_agents.utils.naming`` which holds the canonical implementations
of ``subject_safe_name`` and ``preprocess_name``.
"""

from __future__ import annotations

from dd_agents.utils.naming import preprocess_name, subject_safe_name

__all__ = ["subject_safe_name", "preprocess_name"]
