"""OFAC Specially Designated Nationals (SDN) list, US Treasury.

* URL: ``https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML``.
  The older ``https://www.treasury.gov/ofac/downloads/sdn.xml`` answers with a 302 to
  this endpoint, which then redirects (HTTPS) to a signed object-storage URL.
* Format: one XML document, root ``<sdnList>``, one ``<sdnEntry>`` per listed party.
  Publication date is ``publshInformation/Publish_Date`` (``MM/DD/YYYY``). The
  element name ``publshInformation`` is spelled that way in the real file.
* Verified 2026-11-14: downloaded the live file with curl (HTTP 200, text/xml) and
  read its element structure. Entry detail pages exist at
  ``https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}``.
* Terms: US Government work published for public download on
  https://ofac.treasury.gov/sanctions-list-service. No token or registration.
* The file has no per-entry listing date, so ``listed_on`` is always empty.
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

SOURCE_ID = "ofac_sdn"
LABEL = "OFAC SDN (US Treasury)"
URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
DETAIL_URL = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={uid}"

_KINDS: dict[str, EntryKind] = {
    "individual": "person",
    "entity": "organization",
    "vessel": "vessel",
    "aircraft": "aircraft",
}


def _entry(element: Element) -> ListEntry:
    uid = child_text(element, "uid")
    name = join_name(child_text(element, "firstName"), child_text(element, "lastName"))
    if not uid or not name:
        raise SourceParseError(f"{SOURCE_ID}: sdnEntry without uid or name")
    aliases = [
        join_name(child_text(aka, "firstName"), child_text(aka, "lastName")) for aka in element.findall("akaList/aka")
    ]
    countries = (
        descendant_texts(element, "nationalityList/nationality/country")
        + descendant_texts(element, "citizenshipList/citizenship/country")
        + descendant_texts(element, "addressList/address/country")
    )
    return ListEntry(
        source=SOURCE_ID,
        uid=uid,
        name=name,
        aliases=unique(aliases, exclude=[name]),
        kind=_KINDS.get(child_text(element, "sdnType").casefold(), "unknown"),
        birth_years=birth_years(descendant_texts(element, "dateOfBirthList/dateOfBirthItem/dateOfBirth")),
        countries=unique(countries),
        programs=unique(descendant_texts(element, "programList/program")),
        url=DETAIL_URL.format(uid=uid),
        remarks=short_remarks(child_text(element, "title"), child_text(element, "remarks")),
    )


def parse(raw: bytes) -> tuple[list[ListEntry], str]:
    """Parse an ``SDN.XML`` file into entries and the ISO publication date.

    Raises:
        SourceParseError: the file is not a well-formed SDN document.
    """
    entries: list[ListEntry] = []
    published = ""
    for child in stream_children(raw, "sdnList", {}):
        if child.tag == "publshInformation":
            published = iso_date(child_text(child, "Publish_Date"), "mdy")
        elif child.tag == "sdnEntry":
            entries.append(_entry(child))
    return require_entries(entries, SOURCE_ID), published
