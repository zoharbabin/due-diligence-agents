"""dd_agents.hooks subpackage -- hook function exports."""

from __future__ import annotations

from dd_agents.hooks.factory import build_hooks_for_agent
from dd_agents.hooks.post_tool import (
    validate_audit_entry,
    validate_customer_json,
    validate_manifest_json,
)
from dd_agents.hooks.pre_tool import (
    BASH_BLOCKLIST,
    BLOCKED_FILENAMES,
    DEFAULT_MAX_BYTES,
    SCOPE_CHECKED_PREFIXES,
    bash_guard,
    file_size_guard,
    path_guard,
)
from dd_agents.hooks.stop import (
    check_audit_log,
    check_coverage,
    check_manifest,
)

__all__ = [
    # Factory
    "build_hooks_for_agent",
    # PreToolUse
    "bash_guard",
    "path_guard",
    "file_size_guard",
    # PostToolUse
    "validate_customer_json",
    "validate_manifest_json",
    "validate_audit_entry",
    # Stop
    "check_coverage",
    "check_manifest",
    "check_audit_log",
    # Constants
    "BASH_BLOCKLIST",
    "SCOPE_CHECKED_PREFIXES",
    "BLOCKED_FILENAMES",
    "DEFAULT_MAX_BYTES",
]
