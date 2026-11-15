"""Pipeline step 26: screen names against local sanctions and watchlists (Issue #274).

Deterministic. No LLM call and no network call. The step builds the list of
names to screen, runs :class:`ScreeningService` once, and writes two things:

* ``findings/external_screening/<stem>.json``: one finding per screened name
  that has at least one possible match. Severity, confidence and citation
  rules are fixed here. The merge step stays the one severity authority.
* ``screening/coverage.json``: what was screened and against which lists, even
  when nothing matched. A missing, stale or unreadable list is a gap there, so
  "no hits" never reads as clean.

Every hit is a possible match that needs human review. Text never says a
party "is sanctioned".
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.agents.severity_thresholds import (
    SCREENING_SEVERITY_EXACT,
    SCREENING_SEVERITY_POSSIBLE,
    SCREENING_SEVERITY_STRONG,
)
from dd_agents.models.enums import AgentName
from dd_agents.screening.matcher import normalize_name
from dd_agents.screening.service import ScreeningReport, ScreeningService, ScreenTarget
from dd_agents.screening.sources import SOURCES

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dd_agents.models.config import DealConfig
    from dd_agents.screening.models import MatchBand, ScreenHit

logger = logging.getLogger(__name__)

SCREENING_AGENT = AgentName.EXTERNAL_SCREENING.value
#: Stem for hits on the target company and its executives. Leading underscore =
#: synthetic deal-wide subject (see ``utils.constants.SYNTHETIC_SUBJECT_KEYS``).
TARGET_STEM = "_target_screening"
TARGET_LABEL = "Target company and executives"
SCREENING_RUN_DIR = "screening"
COVERAGE_FILE = "coverage.json"
CATEGORY = "sanctions_watchlist_screening"

#: At most this many hits are written into one finding (strongest first).
MAX_HITS_PER_FINDING = 3

_BAND_SEVERITY: dict[MatchBand, str] = {
    "exact": SCREENING_SEVERITY_EXACT,
    "strong": SCREENING_SEVERITY_STRONG,
    "possible": SCREENING_SEVERITY_POSSIBLE,
}
_BAND_RANK: dict[MatchBand, int] = {"exact": 3, "strong": 2, "possible": 1}

#: What the step does not screen. Written to coverage.json and shown in the report.
NOT_COVERED: tuple[str, ...] = (
    "UN Security Council consolidated list, as its own list. It is not bundled because its terms forbid "
    "derived indexes. The UK and EU lists carry the UN designations.",
    "US SAM.gov exclusions and HHS-OIG exclusions, unless added as a user list under dd-config/screening/.",
    "Politically exposed persons, adverse media and beneficial ownership.",
    "Any list not named in the coverage table.",
)


@dataclass
class OwnedTarget:
    """A screened name, the finding file it belongs to, and why it was screened."""

    target: ScreenTarget
    stem: str
    subject: str
    roles: list[str] = field(default_factory=list)


@dataclass
class ScreeningOutcome:
    """Counts only. Never holds names, so it is safe to log."""

    targets_by_kind: dict[str, int]
    targets_with_hits: int
    hits_total: int
    findings_written: int
    gaps: int
    complete: bool


def _dedupe_key(name: str, kind: str) -> tuple[str, str]:
    return kind, normalize_name(name, "person" if kind == "person" else "organization")


def build_targets(
    config: DealConfig,
    subjects: Sequence[tuple[str, str]],
    extra_people: Sequence[tuple[str, str]] = (),
) -> list[OwnedTarget]:
    """Return the names to screen, de-duplicated by normalized name.

    *subjects* is ``[(name, safe_name), ...]`` from the subject registry. Subjects
    come first, so a name that is both a subject and the target is reported
    under the subject. Roles of duplicates are merged. *extra_people* is
    ``[(name, role), ...]`` for officers found by discovery (screened as people
    of the target when ``screening.people`` is on).
    """
    screening = config.screening
    found: dict[tuple[str, str], OwnedTarget] = {}

    def add(name: str, kind: str, role: str, stem: str, subject: str) -> None:
        clean = name.strip()
        if not clean:
            return
        key = _dedupe_key(clean, kind)
        if not key[1]:
            return
        existing = found.get(key)
        if existing is not None:
            if role not in existing.roles:
                existing.roles.append(role)
            return
        found[key] = OwnedTarget(
            target=ScreenTarget(
                name=clean,
                kind="person" if kind == "person" else "organization",
                context=role,
            ),
            stem=stem,
            subject=subject,
            roles=[role],
        )

    if screening.companies:
        for name, safe_name in subjects:
            add(name, "organization", "data room entity", safe_name, name)
        add(config.target.name, "organization", "target company", TARGET_STEM, TARGET_LABEL)
        for sub in config.target.subsidiaries:
            add(sub, "organization", "subsidiary of the target", TARGET_STEM, TARGET_LABEL)
        for prev in config.target.previous_names:
            add(prev.name, "organization", "previous name of the target", TARGET_STEM, TARGET_LABEL)
    if screening.people:
        for person in config.key_executives:
            role = f"key executive of the target ({person.title})" if person.title else "key executive of the target"
            add(person.name, "person", role, TARGET_STEM, TARGET_LABEL)
        for name, role in extra_people:
            add(name, "person", role, TARGET_STEM, TARGET_LABEL)
    return list(found.values())


def _hit_sort_key(hit: ScreenHit) -> tuple[int, float]:
    return (-_BAND_RANK[hit.band], -hit.score)


def _list_label(source_id: str) -> str:
    source = SOURCES.get(source_id)
    return source.label if source is not None else source_id.removeprefix("user:") + " (user list)"


def _citation(
    hit: ScreenHit, screened: str, service: ScreeningService, list_dates: dict[str, str], run_date: str
) -> dict[str, Any]:
    entry = hit.entry
    url = entry.url
    if not url:
        source = SOURCES.get(entry.source)
        if source is not None:
            url = source.url
        else:
            origin = service.user_list_origin(entry.source)
            if origin is not None:
                file_name, source_url = origin
                url = source_url or f"dd-config/screening/{file_name}"
    return {
        "source_type": "database",
        "source_path": url or f"screening list {entry.source}",
        # The merge step de-duplicates on (source_path, location). The screened name keeps two
        # names that hit the same list entry from collapsing into one finding.
        "location": f"{entry.source}:{entry.uid} | screened: {screened}",
        "exact_quote": entry.name,
        "access_date": list_dates.get(entry.source) or run_date,
    }


def _hit_line(index: int, hit: ScreenHit) -> str:
    entry = hit.entry
    programs = ", ".join(entry.programs) if entry.programs else "not stated"
    notes = "; ".join(hit.corroboration) if hit.corroboration else "none available"
    listed = f" Listed on {entry.listed_on}." if entry.listed_on else ""
    return (
        f"{index}. {hit.band.capitalize()} name match on {_list_label(entry.source)}. "
        f"Listed name: {entry.name}. Matched name: {hit.matched_name}. Score: {hit.score:.0f}. "
        f"Program: {programs}. Corroboration: {notes}.{listed}"
    )


def _confidence(hits: Sequence[ScreenHit]) -> str:
    """Medium only for an exact match with agreeing detail. Never high."""
    for hit in hits:
        if hit.band == "exact" and any(note.endswith("agrees") for note in hit.corroboration):
            return "medium"
    return "low"


def build_finding(
    owned: OwnedTarget,
    hits: Sequence[ScreenHit],
    service: ScreeningService,
    list_dates: dict[str, str],
    run_date: str,
) -> dict[str, Any]:
    """One finding for one screened name with at least one hit."""
    ordered = sorted(hits, key=_hit_sort_key)
    shown = ordered[:MAX_HITS_PER_FINDING]
    top = ordered[0]
    kind_word = "person" if owned.target.kind == "person" else "company"
    title = f"Possible match, needs review: {owned.target.name} on {_list_label(top.entry.source)}"
    lines = [
        "Possible match, needs review. This is a name match only. "
        "It does not show that the screened party is the listed party.",
        f"Screened name: {owned.target.name} ({kind_word}; {', '.join(owned.roles)}).",
        *[_hit_line(i, h) for i, h in enumerate(shown, start=1)],
    ]
    if len(ordered) > len(shown):
        lines.append(f"{len(ordered) - len(shown)} more possible match(es) are in the finding metadata.")
    lines.append(
        "Next step: compare date of birth, address and registration number with the list entry. "
        "Decide with counsel. A match here is not a conclusion."
    )
    citations = [_citation(h, owned.target.name, service, list_dates, run_date) for h in shown]
    return {
        "severity": _BAND_SEVERITY[top.band],
        "category": CATEGORY,
        "title": title[:120],
        "description": "\n".join(lines),
        "confidence": _confidence(ordered),
        "citations": citations,
        "metadata": {
            "screening": {
                "screened_name": owned.target.name,
                "screened_kind": owned.target.kind,
                "roles": list(owned.roles),
                "hits": [
                    {
                        "source": h.entry.source,
                        "list": _list_label(h.entry.source),
                        "uid": h.entry.uid,
                        "listed_name": h.entry.name,
                        "matched_name": h.matched_name,
                        "band": h.band,
                        "score": round(h.score, 1),
                        "programs": list(h.entry.programs),
                        "corroboration": list(h.corroboration),
                    }
                    for h in ordered
                ],
            }
        },
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_findings(
    run_dir: Path,
    owned_by_stem: dict[str, list[tuple[OwnedTarget, list[ScreenHit]]]],
    report: ScreeningReport,
    service: ScreeningService,
    run_date: str,
) -> int:
    list_dates = {row.source: row.list_date for row in report.coverage if row.list_date}
    folder = run_dir / "findings" / SCREENING_AGENT
    # A re-run must not leave files from an earlier run behind.
    if folder.is_dir():
        for stale in folder.glob("*.json"):
            stale.unlink()
    written = 0
    for stem, owners in owned_by_stem.items():
        findings = [build_finding(o, hits, service, list_dates, run_date) for o, hits in owners if hits]
        if not findings:
            continue
        _write_json(
            folder / f"{stem}.json",
            {
                "agent": SCREENING_AGENT,
                "subject": owners[0][0].subject,
                "subject_safe_name": stem,
                "findings": findings,
                "gaps": [],
                "cross_references": [],
            },
        )
        written += len(findings)
    return written


def _write_coverage(
    run_dir: Path,
    run_id: str,
    report: ScreeningReport,
    service: ScreeningService,
    owned: Sequence[OwnedTarget],
    outcome: ScreeningOutcome,
    now: datetime,
) -> None:
    _write_json(
        run_dir / SCREENING_RUN_DIR / COVERAGE_FILE,
        {
            "run_id": run_id,
            "generated_at": now.isoformat(),
            "complete": report.complete,
            "coverage": [row.model_dump() for row in report.coverage],
            "gaps": list(report.gaps),
            "user_errors": list(report.user_errors),
            "user_lists_hash": service.user_content_hash,
            "targets_screened": dict(outcome.targets_by_kind),
            "targets_with_hits": outcome.targets_with_hits,
            "hits_total": outcome.hits_total,
            "reference_notes": [ref.name for ref in report.references],
            "not_covered": list(NOT_COVERED),
            "targets_total": len(owned),
        },
    )


def run_screening(
    *,
    config: DealConfig,
    subjects: Sequence[tuple[str, str]],
    project_dir: Path,
    run_dir: Path,
    run_id: str = "",
    service: ScreeningService | None = None,
    now: datetime | None = None,
    extra_people: Sequence[tuple[str, str]] = (),
) -> ScreeningOutcome:
    """Screen, write findings and coverage, return counts. Never raises on a list problem."""
    moment = now or datetime.now(UTC)
    owned = build_targets(config, subjects, extra_people)
    svc = service or ScreeningService.load(project_dir, source_ids=config.screening.sources, now=moment)
    report = svc.screen([o.target for o in owned])

    owned_by_stem: dict[str, list[tuple[OwnedTarget, list[ScreenHit]]]] = {}
    for item, result in zip(owned, report.results, strict=True):
        owned_by_stem.setdefault(item.stem, []).append((item, result.hits))

    written = _write_findings(run_dir, owned_by_stem, report, svc, moment.date().isoformat())
    kinds: dict[str, int] = {"person": 0, "organization": 0}
    for item in owned:
        kinds[item.target.kind] += 1
    with_hits = [r for r in report.results if r.hits]
    outcome = ScreeningOutcome(
        targets_by_kind=kinds,
        targets_with_hits=len(with_hits),
        hits_total=sum(len(r.hits) for r in with_hits),
        findings_written=written,
        gaps=len(report.gaps),
        complete=report.complete,
    )
    _write_coverage(run_dir, run_id, report, svc, owned, outcome, moment)
    logger.info(
        "Screening: %d organizations, %d people screened; %d with possible matches; %d list gap(s)",
        kinds["organization"],
        kinds["person"],
        outcome.targets_with_hits,
        outcome.gaps,
    )
    return outcome
