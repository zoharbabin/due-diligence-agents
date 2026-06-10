"""Request-list reconciliation (Issue #192).

Declare what documents are *expected* in a data room (a request list) and
reconcile it against what was *discovered*, producing received / missing /
unexpected views. Missing **required** items become standard
:class:`~dd_agents.models.finding.Gap` records (``GapType.MISSING_DOC``,
``DetectionMethod.FILE_INVENTORY``) so they flow through the existing gaps
pipeline + report renderer with no parallel model.

Pure + dependency-free: the reconciler takes the typed config items and a flat
list of discovered file paths (relative to the data room) and returns a
structured result. The CLI/engine supply the file list; this module does no I/O.

Off by default — absent ``request_list`` config means nothing runs (parity).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dd_agents.models.enums import DetectionMethod, GapType, Severity
from dd_agents.models.finding import Gap

if TYPE_CHECKING:
    from dd_agents.models.config import RequestedDocument

# Split a category label into lowercase keyword tokens (drops short/stop words).
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS: frozenset[str] = frozenset({"the", "a", "an", "of", "and", "or", "for", "to", "doc", "document"})


def _category_keywords(item: RequestedDocument) -> list[str]:
    """Keywords that satisfy *item*: explicit ones, else derived from category."""
    if item.keywords:
        return [k.strip().lower() for k in item.keywords if k.strip()]
    return [t for t in _TOKEN_RE.findall(item.category.lower()) if t not in _STOPWORDS and len(t) > 2]


def _matches(keywords: list[str], haystack: str) -> bool:
    """True if every keyword token appears in *haystack* (AND match)."""
    return bool(keywords) and all(k in haystack for k in keywords)


@dataclass(frozen=True)
class RequestItemStatus:
    """Reconciliation outcome for one expected item."""

    category: str
    subject: str | None
    required: bool
    received: bool
    matched_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconciliationResult:
    """Full request-list reconciliation against discovered files."""

    items: list[RequestItemStatus]
    unexpected_files: list[str]

    @property
    def received(self) -> list[RequestItemStatus]:
        return [i for i in self.items if i.received]

    @property
    def missing(self) -> list[RequestItemStatus]:
        return [i for i in self.items if not i.received]

    @property
    def missing_required(self) -> list[RequestItemStatus]:
        return [i for i in self.items if not i.received and i.required]

    def summary(self) -> str:
        """One-line, human-readable completeness summary for `assess`."""
        total = len(self.items)
        recv = len(self.received)
        miss_req = len(self.missing_required)
        return (
            f"{recv}/{total} expected items received"
            f"{f', {miss_req} required missing' if miss_req else ''}"
            f"{f', {len(self.unexpected_files)} unexpected file(s)' if self.unexpected_files else ''}."
        )


def reconcile(
    items: list[RequestedDocument],
    discovered_paths: list[str],
    *,
    subject_of: dict[str, str] | None = None,
) -> ReconciliationResult:
    """Reconcile expected *items* against *discovered_paths*.

    Parameters
    ----------
    items:
        Expected documents from ``request_list.items``.
    discovered_paths:
        Data-room-relative file paths (e.g. ``"Acme/msa_signed.pdf"``).
    subject_of:
        Optional map ``relative_path -> subject`` so a subject-scoped item only
        matches files under that subject. When omitted, item ``subject`` is
        matched against the path text (best-effort).

    A file counts as "matched" when all of an item's keywords appear in its
    lowercased path (and, for a subject-scoped item, the file belongs to that
    subject). ``unexpected_files`` are discovered files that matched no item —
    informational only (never a gap; data rooms legitimately hold extra docs).
    """
    lowered = {p: p.lower() for p in discovered_paths}
    statuses: list[RequestItemStatus] = []
    matched_any: set[str] = set()

    for item in items:
        keywords = _category_keywords(item)
        subj = (item.subject or "").strip().lower()
        matches: list[str] = []
        for path, low in lowered.items():
            if subj:
                # Subject scoping: prefer the explicit map, else path contains subject.
                file_subject = (subject_of or {}).get(path, "").lower()
                in_subject = subj in file_subject if file_subject else subj in low
                if not in_subject:
                    continue
            if _matches(keywords, low):
                matches.append(path)
        if matches:
            matched_any.update(matches)
        statuses.append(
            RequestItemStatus(
                category=item.category,
                subject=item.subject,
                required=item.required,
                received=bool(matches),
                matched_files=sorted(matches),
            )
        )

    unexpected = sorted(p for p in discovered_paths if p not in matched_any)
    return ReconciliationResult(items=statuses, unexpected_files=unexpected)


def to_gaps(result: ReconciliationResult, *, run_id: str | None = None) -> list[Gap]:
    """Convert missing **required** items into standard Gap records.

    Reuses the existing Gap/GapType/DetectionMethod contract so request-list
    gaps render in the report's gaps section exactly like any other gap. Missing
    *optional* items are intentionally NOT gaps (they're nice-to-haves).
    """
    gaps: list[Gap] = []
    for item in result.missing_required:
        subject = item.subject or "Deal-wide"
        gaps.append(
            Gap(
                subject=subject,
                priority=Severity.P2,
                gap_type=GapType.MISSING_DOC,
                missing_item=item.category[:200],
                why_needed=f"'{item.category}' is on the deal's request list as a required document.",
                risk_if_missing="Expected document not found in the data room; diligence on this item is incomplete.",
                request_to_company=f"Please provide: {item.category}.",
                evidence="Declared in request_list; no matching file discovered in the data room.",
                detection_method=DetectionMethod.FILE_INVENTORY,
                run_id=run_id,
            )
        )
    return gaps


def seed_from_vdr_categories(categories: dict[str, str]) -> list[RequestedDocument]:
    """Build a baseline request list from detected VDR categories (Issue #193 → #192).

    Each recognized VDR category becomes a required expected item, so a numbered
    VDR export yields a sensible default checklist with no manual config.
    *categories* maps folder name → normalized category label
    (from ``vdr_conventions.detect_convention(...).categories``).
    """
    from dd_agents.models.config import RequestedDocument

    seen: set[str] = set()
    items: list[RequestedDocument] = []
    for label in categories.values():
        if label in seen:
            continue
        seen.add(label)
        items.append(RequestedDocument(category=label, required=True))
    return items
