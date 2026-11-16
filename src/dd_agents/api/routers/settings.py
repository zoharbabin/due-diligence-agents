"""Provider settings. The desktop shell keeps secrets in the OS keychain and pushes them here at launch."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["settings"])

# Only provider routing and credentials. Anything else (PATH, DD_*, proxies) is refused.
SETTABLE_ENV = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "ANTHROPIC_VERTEX_PROJECT_ID",
        "CLOUD_ML_REGION",
    }
)
MAX_VALUE_LENGTH = 4096


class EnvUpdate(BaseModel):
    values: dict[str, str]


def _problem(name: str, value: str) -> str | None:
    if name not in SETTABLE_ENV:
        return f"{name} cannot be set here"
    if len(value) > MAX_VALUE_LENGTH:
        return f"{name} is too long"
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return f"{name} contains control characters"
    return None


def _current() -> list[str]:
    return sorted(n for n in SETTABLE_ENV if os.environ.get(n))


@router.get("/settings/env", summary="Read-only. Names of provider variables that are set. Never returns values.")
def get_env() -> dict[str, list[str]]:
    return {"set": _current(), "settable": sorted(SETTABLE_ENV)}


@router.put(
    "/settings/env",
    summary="Sets provider variables in server memory only (never on disk). An empty value clears one.",
)
def put_env(body: EnvUpdate) -> dict[str, list[str]]:
    problems = [p for n, v in body.values.items() if (p := _problem(n, v))]
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    for name, value in body.values.items():
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
    return {"set": _current()}
