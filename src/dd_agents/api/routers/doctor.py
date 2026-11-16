"""First-run pre-flight: is a provider configured, and can the CLI be found?"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.llm import (
    PROVIDER_CREDENTIAL_HINTS,
    credential_present,
    probe_provider,
    resolve_provider,
    scrub_secrets,
)
from dd_agents.llm.cli_provision import managed_cli_path

router = APIRouter(tags=["doctor"])


def _sdk_bundles_cli() -> bool:
    try:
        import claude_agent_sdk
    except ImportError:
        return False
    return (Path(claude_agent_sdk.__file__).parent / "_bundled").is_dir()


def _cli_source() -> str | None:
    """Where the Claude CLI would come from. Mirrors ``resolve_sdk_cli_path``. Never returns a path."""
    env_path = os.environ.get("DD_AGENTS_CLI_PATH")
    if env_path and Path(env_path).is_file():
        return "env"
    if shutil.which("claude"):
        return "system"
    if managed_cli_path():
        return "managed"
    return "sdk" if _sdk_bundles_cli() else None


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


@router.get(
    "/cli/install",
    summary="Read-only. State of the Claude CLI download: idle, downloading, done or error.",
)
def cli_install_status(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # noqa: B008
    return ctx.cli_installer.status()


@router.post(
    "/cli/install",
    status_code=202,
    summary="Downloads the pinned Claude CLI from the npm registry into the user data folder. Idempotent.",
)
def cli_install_start(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # noqa: B008
    return ctx.cli_installer.start()
