"""Shared utility functions and constants."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from dd_agents.utils.naming import subject_safe_name

__all__ = [
    "resolve_sdk_cli_path",
    "subject_safe_name",
]

_logger = logging.getLogger(__name__)


def resolve_sdk_cli_path() -> str | None:
    """Resolve the Claude CLI binary path for ``claude-agent-sdk`` sessions.

    Check order:

    1. ``DD_AGENTS_CLI_PATH`` environment variable (explicit override).
    2. System-installed ``claude`` binary on ``$PATH``.
    3. ``None`` — let the SDK use its bundled binary.

    Using the system-installed CLI avoids version mismatches between the
    SDK's bundled binary and the latest release (e.g. Bedrock auth fixes
    that ship in newer CLI versions before the SDK updates its bundle).
    """
    env_path = os.environ.get("DD_AGENTS_CLI_PATH")
    if env_path:
        if Path(env_path).is_file():
            return env_path
        _logger.warning("DD_AGENTS_CLI_PATH=%s does not exist — ignoring", env_path)

    system_cli = shutil.which("claude")
    if system_cli:
        return system_cli

    return None
