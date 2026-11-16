"""Specialist agents: read the built-in persona, edit the project's ``dd-config`` override, preview the prompt."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from dd_agents.agents.introspection import (
    ValidationIssue,
    describe_agent,
    list_agents,
    preview_prompt,
    validate_customizations,
)
from dd_agents.agents.registry import AgentRegistry
from dd_agents.api.projects_util import Project, room_of
from dd_agents.customization.loader import BUNDLED_PROFILES_DIR

router = APIRouter(tags=["agents"])

MAX_OVERRIDE_CHARS = 64_000


class OverrideBody(BaseModel):
    content: str = Field(max_length=MAX_OVERRIDE_CHARS)


def _agent_name(name: str) -> str:
    """Only registered agent names reach the file system, so a name can never be a path."""
    if name not in AgentRegistry.all_specialist_names():
        raise HTTPException(status_code=404, detail=f"No agent '{name}'")
    return name


def _override_path(room: Path, name: str) -> Path:
    return room / "dd-config" / "agents" / f"{name}.md"


def _read_override(room: Path, name: str) -> str | None:
    path = _override_path(room, name)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"The saved override cannot be read: {exc}") from exc


def _issues(items: list[ValidationIssue]) -> list[dict[str, str]]:
    return [{"level": i.level, "message": i.message} for i in items]


def _errors_in(name: str, content: str) -> list[ValidationIssue]:
    """Run the project's own validator on the text in a scratch folder. Nothing is written to the project."""
    with tempfile.TemporaryDirectory(prefix="dd-agent-check-") as scratch:
        target = _override_path(Path(scratch), name)
        target.parent.mkdir(parents=True)
        target.write_text(content, encoding="utf-8")
        return [i for i in validate_customizations(Path(scratch)) if i.level == "error"]


@router.get("/profiles", summary="Read-only. Bundled starting points for an agent override.")
def profiles() -> list[dict[str, str]]:
    return [
        {"name": p.stem, "content": p.read_text(encoding="utf-8")} for p in sorted(BUNDLED_PROFILES_DIR.glob("*.md"))
    ]


@router.get(
    "/projects/{slug}/agents", summary="Read-only. Every specialist agent and whether this project overrides it."
)
def list_project_agents(project: Project) -> list[dict[str, Any]]:
    room = room_of(project)
    return [
        {
            "name": a.name,
            "display_name": a.display_name,
            "status": a.status,
            "has_override": _override_path(room, a.name).is_file(),
        }
        for a in list_agents()
    ]


@router.get(
    "/projects/{slug}/agents/validate",
    summary="Read-only. Check every dd-config agent file in the project, including files edited outside the app.",
)
def validate_project_agents(project: Project) -> dict[str, list[dict[str, str]]]:
    return {"issues": _issues(validate_customizations(room_of(project)))}


@router.get("/projects/{slug}/agents/{name}", summary="Read-only. The built-in description and the saved override.")
def get_agent(project: Project, name: str) -> dict[str, Any]:
    _agent_name(name)
    return {"name": name, "description": describe_agent(name), "override": _read_override(room_of(project), name)}


@router.get(
    "/projects/{slug}/agents/{name}/preview",
    summary="Read-only. The full prompt the agent would get, with the saved override applied.",
)
def preview(project: Project, name: str) -> dict[str, str]:
    _agent_name(name)
    return {"prompt": preview_prompt(name, project_dir=room_of(project))}


@router.put(
    "/projects/{slug}/agents/{name}",
    summary="Writes dd-config/agents/{name}.md in the data room. Rejects an invalid override and keeps the old file.",
)
def put_agent(project: Project, name: str, body: OverrideBody) -> dict[str, str]:
    _agent_name(name)
    problems = _errors_in(name, body.content)
    if problems:
        raise HTTPException(
            status_code=422, detail={"message": "The override is not valid", "issues": _issues(problems)}
        )
    path = _override_path(room_of(project), name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(body.content, encoding="utf-8")
    os.replace(tmp, path)
    return {"content": body.content}


@router.delete(
    "/projects/{slug}/agents/{name}",
    status_code=204,
    summary="Deletes dd-config/agents/{name}.md so the agent uses its built-in persona. Idempotent.",
)
def delete_agent(project: Project, name: str) -> Response:
    _agent_name(name)
    _override_path(room_of(project), name).unlink(missing_ok=True)
    return Response(status_code=204)
