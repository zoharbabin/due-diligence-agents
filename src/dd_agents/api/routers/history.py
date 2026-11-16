"""History: what happened in a project, from the analysis chronicle."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from dd_agents.api.projects_util import Project, skill_dir_of
from dd_agents.knowledge.chronicle import AnalysisChronicle, InteractionType

router = APIRouter(tags=["history"])

MAX_LIMIT = 500


@router.get("/projects/{slug}/history", summary="Read-only. Analysis chronicle entries, newest first.")
def history(
    project: Project,
    type: Annotated[InteractionType | None, Query()] = None,  # noqa: A002 - public query name
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 100,
) -> dict[str, Any]:
    chronicle = AnalysisChronicle(skill_dir_of(project) / "knowledge" / "chronicle.jsonl")
    stats = chronicle.get_stats()
    if type:
        entries = chronicle.read_by_type(type)
        total = len(entries)
    else:
        entries = chronicle.read_recent(limit=limit)
        total = stats["total_entries"]
    shown = [
        e.model_dump(mode="json", exclude={"details"})  # details can hold free text. The app does not need it
        for e in reversed(entries[-limit:])
    ]
    return {"entries": shown, "total": total, "by_type": stats["by_type"]}
