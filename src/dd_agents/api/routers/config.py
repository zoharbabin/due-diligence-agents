"""Deal config: schema, validate, read, write (fail-closed)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from dd_agents.api.context import AppContext, get_ctx
from dd_agents.api.projects_util import CONFIG_NAME, Project, atomic_write_json, config_path_of, room_of
from dd_agents.api.schemas import ConfigError, ConfigValidation
from dd_agents.config import ConfigValidationError, validate_deal_config
from dd_agents.models.config import DealConfig

router = APIRouter(tags=["config"])


def _errors(exc: ConfigValidationError) -> list[ConfigError]:
    return [
        ConfigError(loc=" -> ".join(str(p) for p in e["loc"]), msg=e["msg"], type=e["type"])
        for e in exc.validation_error.errors()
    ]


@router.get("/config/schema", summary="Read-only. JSON Schema of the deal config.")
def config_schema() -> dict[str, Any]:
    return DealConfig.model_json_schema()


@router.post("/config/validate", summary="Read-only. Check a config without saving it.")
def validate_config(data: dict[str, Any]) -> ConfigValidation:
    try:
        validate_deal_config(data)
    except ConfigValidationError as exc:
        return ConfigValidation(valid=False, errors=_errors(exc))
    return ConfigValidation(valid=True)


@router.get("/projects/{slug}/config", summary="Read-only. The project's deal config as saved.")
def get_config(project: Project) -> dict[str, Any]:
    path = config_path_of(project)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This project has no deal config yet")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Saved config cannot be read: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Saved config is not a JSON object")
    return data


@router.put(
    "/projects/{slug}/config",
    summary="Writes deal-config.json in the data room. Rejects an invalid config and leaves the old file alone.",
)
def put_config(project: Project, data: dict[str, Any], ctx: Annotated[AppContext, Depends(get_ctx)]) -> dict[str, Any]:
    room = room_of(project)
    # The data room is fixed by the project. A client cannot point a run at another folder.
    data_room = data.get("data_room")
    data["data_room"] = {**(data_room if isinstance(data_room, dict) else {}), "path": str(room)}
    try:
        cfg = validate_deal_config(data)
    except ConfigValidationError as exc:
        raise HTTPException(
            status_code=422, detail={"message": "Config is not valid", "errors": [e.model_dump() for e in _errors(exc)]}
        ) from exc
    path = room / CONFIG_NAME
    atomic_write_json(path, data)
    ctx.registry.update_project(
        project.slug,
        config_path=str(path),
        buyer=cfg.buyer.name,
        target=cfg.target.name,
    )
    return data
