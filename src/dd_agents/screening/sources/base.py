"""Shared types and helpers for the list adapters.

Every adapter parses bytes into :class:`~dd_agents.screening.models.ListEntry`
objects. Parsing is pure: no network, no disk. Bad input raises
:class:`SourceParseError`. An adapter never returns a partial result.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from xml.etree.ElementTree import Element

    from dd_agents.screening.models import ListEntry

    ParseFn = Callable[[bytes], tuple[list[ListEntry], str]]

REMARKS_MAX_CHARS = 300
MIN_BIRTH_YEAR = 1800
MAX_BIRTH_YEAR = 2100
MAX_RANGE_SPAN = 25

_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEAR_RANGE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d).{0,20}?\bto\b.{0,20}?(?<!\d)(\d{4})(?!\d)", re.IGNORECASE)


class SourceParseError(ValueError):
    """A downloaded list file is malformed or does not look like the expected format."""


@dataclass(frozen=True)
class Source:
    """One downloadable official list."""

    source_id: str
    label: str
    url: str
    parse: ParseFn


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def clean(text: str | None) -> str:
    """Collapse whitespace. ``None`` becomes an empty string."""
    return " ".join((text or "").split())


def join_name(*parts: str | None) -> str:
    """Join the non-empty parts of a name with single spaces."""
    return " ".join(p for p in (clean(x) for x in parts) if p)


def unique(values: Iterable[str], *, exclude: Iterable[str] = ()) -> list[str]:
    """Keep first occurrences, drop empties and case-insensitive duplicates, drop ``exclude``."""
    seen = {v.casefold() for v in exclude}
    out: list[str] = []
    for value in values:
        cleaned = clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def short_remarks(*parts: str | None) -> str:
    """Join non-empty parts with ``; `` and cut to :data:`REMARKS_MAX_CHARS`."""
    text = "; ".join(p for p in (clean(x) for x in parts) if p)
    if len(text) > REMARKS_MAX_CHARS:
        return text[: REMARKS_MAX_CHARS - 3].rstrip() + "..."
    return text


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def birth_years(values: Iterable[str]) -> list[int]:
    """Extract birth years from free-text dates of any precision.

    ``"10 Dec 1948"``, ``"Dec 1948"``, ``"circa 1948"``, ``"dd/mm/1948"`` and
    ``"1948"`` all give ``1948``. ``"1948 to 1950"`` gives 1948, 1949, 1950.
    Text without a plausible year is ignored.
    """
    years: set[int] = set()
    for value in values:
        text = clean(value)
        found = [int(y) for y in _YEAR_RE.findall(text)]
        found = [y for y in found if MIN_BIRTH_YEAR <= y <= MAX_BIRTH_YEAR]
        years.update(found)
        span = _YEAR_RANGE_RE.search(text)
        if span:
            start, end = int(span.group(1)), int(span.group(2))
            if start <= end and end - start <= MAX_RANGE_SPAN and start >= MIN_BIRTH_YEAR and end <= MAX_BIRTH_YEAR:
                years.update(range(start, end + 1))
    return sorted(years)


def year_range(start: str, end: str) -> list[int]:
    """Years from ``start`` to ``end`` inclusive, when both are plausible and the span is small."""
    return birth_years([f"{start} to {end}"]) if start and end else birth_years([start or end])


def iso_date(text: str | None, order: str) -> str:
    """Turn a numeric date into ``YYYY-MM-DD``. ``order`` is ``"mdy"``, ``"dmy"`` or ``"ymd"``.

    Returns ``""`` when the text is empty or not a valid calendar date.
    """
    match = re.fullmatch(r"(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})", clean(text))
    if not match:
        return ""
    a, b, c = (int(g) for g in match.groups())
    try:
        if order == "mdy":
            return date(c, a, b).isoformat()
        if order == "dmy":
            return date(c, b, a).isoformat()
        return date(a, b, c).isoformat()
    except ValueError:
        return ""


def iso_date_prefix(text: str | None) -> str:
    """Return the ``YYYY-MM-DD`` part of an ISO date or datetime. ``""`` if not valid."""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", clean(text))
    if not match:
        return ""
    try:
        return date(*(int(g) for g in match.groups())).isoformat()
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def local_name(tag: Any) -> str:
    """Strip the ``{namespace}`` prefix from an element tag."""
    return str(tag).rpartition("}")[2]


def stream_children(raw: bytes, root_tag: str, root_attrs: dict[str, str]) -> Iterator[Element]:
    """Safely parse ``raw`` and yield each direct child of the root element once it is complete.

    Namespaces are stripped from tag names. ``root_attrs`` is filled with the root
    element's attributes before the first child is yielded. Each child is cleared
    after the caller moves on, so memory stays low on large files. DTDs, entity
    expansion and external entities are rejected.

    Raises:
        SourceParseError: not well-formed XML, a forbidden XML construct, or the
            root element is not ``root_tag``.
    """
    depth = 0
    seen_root = False
    try:
        for event, element in SafeET.iterparse(io.BytesIO(raw), events=("start", "end"), forbid_dtd=True):
            if event == "start":
                element.tag = local_name(element.tag)
                depth += 1
                if depth == 1:
                    seen_root = True
                    if element.tag != root_tag:
                        raise SourceParseError(f"Unexpected root element <{element.tag}>, expected <{root_tag}>")
                    root_attrs.update(element.attrib)
            else:
                depth -= 1
                if depth == 1:
                    yield element
                    element.clear()
    except SourceParseError:
        raise
    except DefusedXmlException as exc:
        raise SourceParseError(f"Forbidden XML construct: {exc}") from exc
    except SafeET.ParseError as exc:
        raise SourceParseError(f"Not well-formed XML: {exc}") from exc
    if not seen_root:
        raise SourceParseError("Empty document")


def child_text(element: Element, tag: str) -> str:
    """Whitespace-collapsed text of the first child ``tag``. ``""`` if missing."""
    child = element.find(tag)
    return clean(child.text) if child is not None else ""


def descendant_texts(element: Element, path: str) -> list[str]:
    """Collapsed, non-empty texts of every element matching ``path``."""
    return [t for t in (clean(e.text) for e in element.findall(path)) if t]


def require_entries(entries: list[ListEntry], source_id: str) -> list[ListEntry]:
    """Fail when a file parsed without a single entry. An empty list is never a valid download."""
    if not entries:
        raise SourceParseError(f"{source_id}: file contains no list entries")
    return entries
