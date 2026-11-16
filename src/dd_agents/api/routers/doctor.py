"""First-run pre-flight: is a provider configured, and can the CLI be found?"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from dd_agents.llm import (
    PROVIDER_CREDENTIAL_HINTS,
    credential_present,
    probe_provider,
    resolve_provider,
    scrub_secrets,
)

router = APIRouter(tags=["doctor"])


def _cli_source() -> str | None:
    """Where the Claude CLI would come from. Mirrors ``resolve_sdk_cli_path``. Never returns a path."""
    env_path = os.environ.get("DD_AGENTS_CLI_PATH")
    if env_path and Path(env_path).is_file():
        return "env"
    if shutil.which("claude"):
        return "system"
    try:
        import claude_agent_sdk

        if (Path(claude_agent_sdk.__file__).parent / "_bundled").is_dir():
            return "sdk"
    except ImportError:
        return None
    return None


@router.get(
    "/doctor",
    summary="Read-only. Provider, credential and CLI status. Never returns secret values or paths.",
)
def doctor() -> dict[str, Any]:
    info = resolve_provider()
    has_credential = credential_present(info)
    source = _cli_source()
    return {
        "provider": info.provider,
        "base_url": info.safe_base_url,
        "credential_present": has_credential,
        "credential_env": list(PROVIDER_CREDENTIAL_HINTS.get(info.provider, ())),
        "cli": {"found": source is not None, "source": source},
        "ready": has_credential and source is not None,
    }


@router.post(
    "/doctor/probe",
    summary="Sends one minimal live query to the configured LLM provider. Uses a few tokens.",
)
def probe() -> dict[str, Any]:
    ok, detail = probe_provider()
    return {"ok": ok, "detail": scrub_secrets(detail)}
