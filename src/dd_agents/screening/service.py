"""Screen names against stored official lists and the user's own lists (Issue #274).

Matching is local. Nothing here uses the network. A list that is missing,
stale or unreadable is reported as a coverage gap, so "no hits" is never
presented as clearance unless :attr:`ScreeningReport.complete` is true, and
even then it means "no possible match found", not "cleared".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from dd_agents.screening import store
from dd_agents.screening.matcher import ScreeningIndex
from dd_agents.screening.models import Coverage, ListEntry, ScreenHit
from dd_agents.screening.sources import SOURCES
from dd_agents.screening.user_lists import UserScreeningConfig, load_user_screening

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime
    from pathlib import Path

DEFAULT_HITS_PER_TARGET = 10


class ScreenTarget(BaseModel):
    """A person or company to screen."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    kind: Literal["person", "organization"]
    birth_year: int | None = None
    country: str | None = None
    context: str = Field(default="", description="Where the name came from, e.g. role and source document")


class TargetResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: ScreenTarget
    hits: list[ScreenHit] = Field(default_factory=list)


class ReferenceNote(BaseModel):
    """A user reference note (kind ``reference``). Context for analysts and agents, not matched."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    source_url: str = ""
    body: str = ""


class ScreeningReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage: list[Coverage]
    results: list[TargetResult]
    references: list[ReferenceNote] = Field(default_factory=list)
    user_errors: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, description="One line per list that was not fully screened")

    @property
    def complete(self) -> bool:
        """True only when every list was fresh and readable. Even then, not a clearance."""
        return not self.gaps


class ScreeningService:
    """Loaded lists plus an index. Build with :meth:`load`, call :meth:`screen`."""

    def __init__(self, coverage: list[Coverage], index: ScreeningIndex, user: UserScreeningConfig) -> None:
        self._coverage = coverage
        self._index = index
        self._user = user

    @classmethod
    def load(
        cls,
        project_dir: Path | None,
        *,
        source_ids: Iterable[str] | None = None,
        now: datetime | None = None,
    ) -> ScreeningService:
        """Read the stored official lists and ``<project_dir>/dd-config/screening/``.

        ``project_dir=None`` skips user lists. Stale lists are still searched
        (and flagged). Missing and failed lists are skipped (and flagged).
        """
        ids = list(source_ids) if source_ids is not None else list(SOURCES)
        rows = store.coverage(ids, now=now)
        entries: list[ListEntry] = []
        for row in rows:
            if row.status not in ("screened", "stale"):
                continue
            try:
                snapshot = store.load_snapshot(row.source)
            except store.StoreError as exc:
                row.status, row.detail = "failed", str(exc)
                continue
            if snapshot is not None:
                entries.extend(snapshot.entries)

        user = load_user_screening(project_dir) if project_dir is not None else UserScreeningConfig()
        for item in user.lists:
            if item.kind != "watchlist":
                continue
            entries.extend(item.entries)
            rows.append(
                Coverage(
                    source=item.source_id,
                    status="screened",
                    entry_count=len(item.entries),
                    detail=f"User list ({item.file})",
                )
            )
        for error in user.errors:
            file_name = error.split(":", 1)[0]
            rows.append(Coverage(source=f"user:{file_name}", status="failed", detail=error))
        return cls(rows, ScreeningIndex(entries), user)

    @property
    def coverage(self) -> list[Coverage]:
        return list(self._coverage)

    @property
    def user_content_hash(self) -> str:
        """Hash of the user's screening files. Empty when there are none."""
        return self._user.content_hash()

    def user_list_origin(self, source_id: str) -> tuple[str, str] | None:
        """``(file name, source_url)`` of the user watchlist behind *source_id*, else ``None``."""
        for item in self._user.lists:
            if item.kind == "watchlist" and item.source_id == source_id:
                return item.file, item.source_url
        return None

    def screen(self, targets: Sequence[ScreenTarget], *, limit: int = DEFAULT_HITS_PER_TARGET) -> ScreeningReport:
        results = [
            TargetResult(
                target=t,
                hits=self._index.search(t.name, t.kind, birth_year=t.birth_year, country=t.country, limit=limit),
            )
            for t in targets
        ]
        gaps = [
            f"{row.source}: {row.status}. {row.detail}".strip() for row in self._coverage if row.status != "screened"
        ]
        references = [
            ReferenceNote(name=n.name, description=n.description, source_url=n.source_url, body=n.body)
            for n in self._user.references()
        ]
        return ScreeningReport(
            coverage=self.coverage,
            results=results,
            references=references,
            user_errors=list(self._user.errors),
            gaps=gaps,
        )
