"""EU consolidated list of persons, groups and entities subject to EU financial sanctions.

* URL: ``https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw``.
  The ``token`` query value is a fixed public constant, the same for every user.
  It is part of the download URL that the EU open data catalogue publishes with
  access right PUBLIC. Without it the server answers 403. No registration or
  per-user credential is involved.
* Format: one XML document, root ``<export>`` (namespace
  ``http://eu.europa.ec/fpi/fsd/export``), one ``<sanctionEntity>`` per listed
  party. Names are ``nameAlias`` elements (the file marks no primary name), birth
  data are ``birthdate`` elements, programmes are on ``regulation`` elements.
  Publication date is the ``generationDate`` attribute of the root.
* Verified 2026-11-14: URL and licence read from the data.europa.eu catalogue
  entry "consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions",
  then the live file downloaded with curl (HTTP 200, application/xml).
* Terms: the catalogue lists licence "European Commission reuse notice"
  (Decision 2011/833/EU) and carries this disclaimer: "Only the information
  published in the Official Journal of the EU is deemed authentic. Please note
  that the information in this dataset may not be fully up to date because
  updates are delayed compared to the relevant publications in the EU's Official
  Journal."
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.screening.models import EntryKind, ListEntry
from dd_agents.screening.sources.base import (
    SourceParseError,
    birth_years,
    clean,
    iso_date_prefix,
    join_name,
    require_entries,
    short_remarks,
    stream_children,
    unique,
    year_range,
)

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

SOURCE_ID = "eu"
LABEL = "EU consolidated financial sanctions list"
URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"

_KINDS: dict[str, EntryKind] = {
    "person": "person",
    "enterprise": "organization",
}


def _alias_name(alias: Element) -> str:
    whole = clean(alias.get("wholeName"))
    return whole or join_name(alias.get("firstName"), alias.get("middleName"), alias.get("lastName"))


def _pick_primary(aliases: list[Element]) -> str:
    """First name written in the default language (no language tag, or English), else the first name."""
    named = [(a, _alias_name(a)) for a in aliases]
    named = [(a, n) for a, n in named if n]
    if not named:
        return ""
    for alias, name in named:
        if clean(alias.get("nameLanguage")).upper() in ("", "EN"):
            return name
    return named[0][1]


def _entry(element: Element) -> ListEntry:
    uid = clean(element.get("euReferenceNumber")) or clean(element.get("logicalId"))
    aliases = element.findall("nameAlias")
    name = _pick_primary(aliases)
    if not uid or not name:
        raise SourceParseError(f"{SOURCE_ID}: sanctionEntity without reference number or name")
    subject = element.find("subjectType")
    years: list[int] = []
    for birth in element.findall("birthdate"):
        if clean(birth.get("year")):
            years += birth_years([birth.get("year") or ""])
        elif clean(birth.get("birthdate")):
            years += birth_years([birth.get("birthdate") or ""])
        else:
            years += year_range(clean(birth.get("yearRangeFrom")), clean(birth.get("yearRangeTo")))
    regulations = element.findall("regulation")
    latest = max(regulations, key=lambda r: clean(r.get("publicationDate")), default=None)
    url = clean(latest.findtext("publicationUrl")) if latest is not None else ""
    return ListEntry(
        source=SOURCE_ID,
        uid=uid,
        name=name,
        aliases=unique((_alias_name(a) for a in aliases), exclude=[name]),
        kind=_KINDS.get(clean(subject.get("code")).casefold() if subject is not None else "", "unknown"),
        birth_years=sorted(set(years)),
        countries=unique(
            clean(c.get("countryDescription")).title()
            for c in [*element.findall("citizenship"), *element.findall("address")]
        ),
        programs=unique(clean(r.get("programme")) for r in regulations),
        url=url,
        listed_on=iso_date_prefix(element.get("designationDate")),
        remarks=short_remarks(element.findtext("remark")),
    )


def parse(raw: bytes) -> tuple[list[ListEntry], str]:
    """Parse the EU full sanctions XML into entries and the ISO publication date.

    Raises:
        SourceParseError: the file is not a well-formed EU sanctions export.
    """
    entries: list[ListEntry] = []
    root_attrs: dict[str, str] = {}
    for child in stream_children(raw, "export", root_attrs):
        if child.tag == "sanctionEntity":
            entries.append(_entry(child))
    return require_entries(entries, SOURCE_ID), iso_date_prefix(root_attrs.get("generationDate"))
