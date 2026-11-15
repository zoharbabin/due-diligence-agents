"""UK Sanctions List, published by the Foreign, Commonwealth and Development Office.

* URL: ``https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml``.
* Format: one XML document, root ``<Designations>``, one ``<Designation>`` per
  listed party. ``<DateGenerated>`` is the publication date (``DD/MM/YYYY``).
  Names sit in ``Names/Name`` with parts ``Name1`` to ``Name6`` (``Name6`` is the
  surname or the whole name of a non-person). Non-Latin script names sit in
  ``NonLatinNames``. Dates of birth are free text, often ``dd/mm/YYYY`` where only
  the year is known.
* Verified 2026-11-14: URL and XML link read from
  https://www.gov.uk/government/publications/the-uk-sanctions-list, then the live
  file downloaded with curl (HTTP 200, text/xml) and its structure read.
* Terms: gov.uk states "All content is available under the Open Government
  Licence v3.0, except where otherwise stated". No token or registration.
* The UK list replaced the OFSI Consolidated List on 2026-01-28. The file has no
  stable per-entry web page, so ``url`` is empty.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.screening.models import EntryKind, ListEntry
from dd_agents.screening.sources.base import (
    SourceParseError,
    birth_years,
    child_text,
    descendant_texts,
    iso_date,
    join_name,
    require_entries,
    short_remarks,
    stream_children,
    unique,
)

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

SOURCE_ID = "uk"
LABEL = "UK Sanctions List (FCDO)"
URL = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"

_KINDS: dict[str, EntryKind] = {
    "individual": "person",
    "entity": "organization",
    "ship": "vessel",
}
_NAME_PARTS = ("Name1", "Name2", "Name3", "Name4", "Name5", "Name6")


def _is_primary(name_type: str) -> bool:
    """``Primary Name`` and ``Primary name`` are the main name. ``... variation`` is not."""
    lowered = name_type.casefold()
    return lowered.startswith("primary name") and "variation" not in lowered


def _entry(element: Element) -> ListEntry:
    uid = child_text(element, "UniqueID")
    primary: list[str] = []
    others: list[str] = []
    for name_el in element.findall("Names/Name"):
        full = join_name(*(child_text(name_el, part) for part in _NAME_PARTS))
        if not full:
            continue
        (primary if _is_primary(child_text(name_el, "NameType")) else others).append(full)
    if not uid or not primary:
        raise SourceParseError(f"{SOURCE_ID}: Designation without UniqueID or primary name")
    name = primary[0]
    non_latin = descendant_texts(element, "NonLatinNames/NonLatinName/NameNonLatinScript")
    countries = descendant_texts(element, "IndividualDetails/Individual/Nationalities/Nationality") + descendant_texts(
        element, "Addresses/Address/AddressCountry"
    )
    return ListEntry(
        source=SOURCE_ID,
        uid=uid,
        name=name,
        aliases=unique([*primary[1:], *others, *non_latin], exclude=[name]),
        kind=_KINDS.get(child_text(element, "IndividualEntityShip").casefold(), "unknown"),
        birth_years=birth_years(descendant_texts(element, "IndividualDetails/Individual/DOBs/DOB")),
        countries=unique(countries),
        programs=unique([child_text(element, "RegimeName")]),
        listed_on=iso_date(child_text(element, "DateDesignated"), "dmy"),
        remarks=short_remarks(child_text(element, "OtherInformation")),
    )


def parse(raw: bytes) -> tuple[list[ListEntry], str]:
    """Parse ``UK-Sanctions-List.xml`` into entries and the ISO publication date.

    Raises:
        SourceParseError: the file is not a well-formed UK Sanctions List document.
    """
    entries: list[ListEntry] = []
    published = ""
    for child in stream_children(raw, "Designations", {}):
        if child.tag == "DateGenerated":
            published = iso_date(child.text, "dmy")
        elif child.tag == "Designation":
            entries.append(_entry(child))
    return require_entries(entries, SOURCE_ID), published
