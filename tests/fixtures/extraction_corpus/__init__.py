"""Typed access to the synthetic extraction corpus.

Every file is invented (see ``README.md``). ``ground_truth.json`` says what each
file contains and what an extractor must recover::

    from extraction_corpus import load_ground_truth, path_for

    for name, entry in load_ground_truth().items():
        text = my_extractor(path_for(name))
        assert all(phrase_in(text, p) for p in entry.key_phrases)

This module has no dependencies outside the standard library.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
GROUND_TRUTH_PATH = CORPUS_DIR / "ground_truth.json"
SCHEMA_VERSION = 1

KINDS = frozenset({"pdf", "docx", "xlsx", "pptx", "html"})
PAGE_KINDS = frozenset({"text", "scanned"})
LANGUAGES = frozenset({"en", "de", "fr", "es", "ja", "zh", "ko"})
EXPECTED_FAILURES = frozenset({"encrypted", "unreadable"})


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    date_of_birth: str
    appointed: str


@dataclass(frozen=True)
class TrackedChanges:
    inserted: tuple[str, ...]
    deleted: tuple[str, ...]


@dataclass(frozen=True)
class CorpusEntry:
    """Ground truth for one corpus file."""

    name: str
    kind: str
    category: str
    language: str
    has_text_layer: bool
    # "text" or "scanned" per page. Empty for non-PDF files.
    page_kinds: tuple[str, ...]
    key_phrases: tuple[str, ...]
    # Phrases per page (PDF files only, same length as page_kinds).
    page_key_phrases: tuple[tuple[str, ...], ...] | None
    # Table rows, header first. Empty when the file has no table.
    table_cells: tuple[tuple[str, ...], ...]
    numeric_cells: tuple[float, ...]
    # Phrases that must appear in this order.
    reading_order: tuple[str, ...]
    persons: tuple[Person, ...]
    tracked_changes: TrackedChanges | None
    watermark_text: str | None
    # "encrypted" (needs a password) or "unreadable" (damaged beyond repair), else None.
    expected_failure: str | None
    # How the file is damaged: truncated, owner_password, user_password.
    damage: str | None
    # Password that opens the file, when one is needed.
    password: str | None
    # Same content: the text copy of a scan (and back), or the source file of a damaged copy.
    pair: str | None
    purpose: str

    @property
    def path(self) -> Path:
        return CORPUS_DIR / self.name

    @property
    def flat_table_cells(self) -> tuple[str, ...]:
        return tuple(cell for row in self.table_cells for cell in row if cell)


def normalize(text: str) -> str:
    """Remove all whitespace. Phrase checks ignore line breaks and spacing."""
    return "".join(text.split())


def phrase_in(text: str, phrase: str) -> bool:
    """True when *phrase* occurs in *text*, ignoring whitespace."""
    return normalize(phrase) in normalize(text)


def _entry(name: str, raw: dict[str, object]) -> CorpusEntry:
    def strings(key: str) -> tuple[str, ...]:
        value = raw[key]
        assert isinstance(value, list)
        return tuple(str(v) for v in value)

    page_phrases = raw["page_key_phrases"]
    tracked = raw["tracked_changes"]
    persons = raw["persons"]
    table = raw["table_cells"]
    numbers = raw["numeric_cells"]
    assert isinstance(persons, list) and isinstance(table, list) and isinstance(numbers, list)

    tracked_obj = None
    if tracked is not None:
        assert isinstance(tracked, dict)
        tracked_obj = TrackedChanges(tuple(tracked["inserted"]), tuple(tracked["deleted"]))

    def opt_str(key: str) -> str | None:
        value = raw[key]
        return None if value is None else str(value)

    return CorpusEntry(
        name=name,
        kind=str(raw["kind"]),
        category=str(raw["category"]),
        language=str(raw["language"]),
        has_text_layer=bool(raw["has_text_layer"]),
        page_kinds=strings("page_kinds"),
        key_phrases=strings("key_phrases"),
        page_key_phrases=None if page_phrases is None else tuple(tuple(p) for p in page_phrases),  # type: ignore[attr-defined]
        table_cells=tuple(tuple(str(c) for c in row) for row in table),
        numeric_cells=tuple(float(n) for n in numbers),
        reading_order=strings("reading_order"),
        persons=tuple(
            Person(p["name"], p["role"], p["date_of_birth"], p["appointed"])
            for p in persons  # type: ignore[misc]
        ),
        tracked_changes=tracked_obj,
        watermark_text=opt_str("watermark_text"),
        expected_failure=opt_str("expected_failure"),
        damage=opt_str("damage"),
        password=opt_str("password"),
        pair=opt_str("pair"),
        purpose=str(raw["purpose"]),
    )


@cache
def load_ground_truth() -> dict[str, CorpusEntry]:
    """Parse ``ground_truth.json``. Keys are file names, sorted."""
    payload = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"unsupported ground truth schema {payload['schema_version']!r}")
    return {name: _entry(name, raw) for name, raw in payload["files"].items()}


def path_for(name: str) -> Path:
    """Absolute path of a corpus file. Raises ``KeyError`` for an unknown name."""
    if name not in load_ground_truth():
        raise KeyError(f"{name!r} is not in the extraction corpus")
    return CORPUS_DIR / name
