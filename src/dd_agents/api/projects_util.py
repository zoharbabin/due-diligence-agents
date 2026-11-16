"""Helpers shared by the project-scoped routes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.models.project import ProjectEntry

SKILL_DIR = Path("_dd") / "forensic-dd"
CONFIG_NAME = "deal-config.json"


def project_or_404(slug: str, ctx: Annotated[AppContext, Depends(get_ctx)]) -> ProjectEntry:
    entry = ctx.registry.get_project(slug)
    if entry is None or entry.slug != slug:
        raise HTTPException(status_code=404, detail=f"No project '{slug}'")
    return entry


Project = Annotated[ProjectEntry, Depends(project_or_404)]


def room_of(entry: ProjectEntry) -> Path:
    return Path(entry.path)


def config_path_of(entry: ProjectEntry) -> Path:
    if entry.config_path and Path(entry.config_path).is_file():
        return Path(entry.config_path)
    return room_of(entry) / CONFIG_NAME


def skill_dir_of(entry: ProjectEntry) -> Path:
    return room_of(entry) / SKILL_DIR


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON so a crash never leaves a half-written file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
