"""US Consolidated Screening List (CSL), International Trade Administration.

The SDN is one of the US restricted-party lists, not all of them. The CSL merges the export-control and sanctions
lists of Commerce, State and Treasury: the BIS Entity List, Military End User (MEU) List, Unverified List (UVL) and
Denied Persons List, State's ITAR debarments and nonproliferation sanctions, and the OFAC non-SDN lists (Sectoral
Sanctions, Non-SDN Chinese Military-Industrial Complex, Menu-Based, Palestinian Legislative Council, CAPTA).

* URL: ``https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.json``.
* Format: one JSON object. ``results`` holds one record per listed party, each with ``source`` (the list), ``name``,
  ``alt_names``, ``addresses``, ``type`` (Treasury lists only), ``programs``, ``start_date`` (when the list gives
  one) and ``source_information_url``. ``sources_used`` gives each list's ``source_last_updated``.
* Verified 2026-11-20: downloaded the live file with curl (HTTP 200, application/json) and read its structure.
* Terms: US Government work published for public download, no key needed for the downloadable file.
* SDN records are left out: the ``ofac_sdn`` source reads them from OFAC itself, so keeping them here would report
  every SDN hit twice.
* The published date is the newest ``source_last_updated`` among the lists kept.
"""

from __future__ import annotations

import json
from typing import Any

from dd_agents.screening.models import EntryKind, ListEntry
from dd_agents.screening.sources.base import (
    SourceParseError,
    birth_years,
    clean,
    iso_date_prefix,
    require_entries,
    short_remarks,
    unique,
)

SOURCE_ID = "us_csl"
LABEL = "US Consolidated Screening List (trade.gov, without the SDN)"
URL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.json"

_SDN_SOURCE = "Specially Designated Nationals (SDN) - Treasury Department"
_KINDS: dict[str, EntryKind] = {
    "individual": "person",
    "entity": "organization",
    "vessel": "vessel",
    "aircraft": "aircraft",
}


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _list_code(source: str) -> str:
    """``"Entity List (EL) - Bureau of Industry and Security"`` -> ``"Entity List (EL)"``."""
    return clean(source.split(" - ", 1)[0])


def _entry(record: dict[str, Any]) -> ListEntry:
    source = clean(record.get("source"))
    name = clean(record.get("name"))
    uid = clean(str(record.get("id") or ""))
    if not uid or not name or not source:
        raise SourceParseError(f"{SOURCE_ID}: record without id, name or source")
    countries = [clean(a.get("country")) for a in record.get("addresses") or [] if isinstance(a, dict)]
    countries += (
        _texts(record.get("nationalities")) + _texts(record.get("citizenships")) + _texts(record.get("country"))
    )
    return ListEntry(
        source=SOURCE_ID,
        uid=uid,
        name=name,
        aliases=unique(_texts(record.get("alt_names")), exclude=[name]),
        kind=_KINDS.get(clean(record.get("type")).casefold(), "unknown"),
        birth_years=birth_years(_texts(record.get("dates_of_birth"))),
        countries=unique(countries),
        programs=unique([_list_code(source), *_texts(record.get("programs"))]),
        url=clean(record.get("source_information_url")) or clean(record.get("source_list_url")),
        listed_on=iso_date_prefix(record.get("start_date")),
        remarks=short_remarks(record.get("remarks"), record.get("federal_register_notice")),
    )


def parse(raw: bytes) -> tuple[list[ListEntry], str]:
    """Parse ``consolidated.json`` into entries (SDN records excluded) and the ISO publication date.

    Raises:
        SourceParseError: the file is not a CSL document.
    """
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceParseError(f"{SOURCE_ID}: not JSON ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SourceParseError(f"{SOURCE_ID}: no results list")
    entries = [
        _entry(record)
        for record in data["results"]
        if isinstance(record, dict) and clean(record.get("source")) != _SDN_SOURCE
    ]
    kept = {e.programs[0] for e in entries}
    dates = [
        iso_date_prefix(s.get("source_last_updated"))
        for s in data.get("sources_used") or []
        if isinstance(s, dict) and _list_code(clean(s.get("source"))) in kept
    ]
    return require_entries(entries, SOURCE_ID), max((d for d in dates if d), default="")
