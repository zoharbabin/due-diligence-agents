"""Match a person or organization name against list entries (Issue #274).

Matching is local and deterministic. A hit is a *possible* match that needs
human review, never a conclusion. Bands:

- ``exact``: same words after normalization (order, case, accents, punctuation
  and, for organizations, legal suffixes are ignored).
- ``strong``: near-identical (typo level), same number of words.
- ``possible``: close spelling, or one name contains the other with at least
  two shared words.

A birth year that differs lowers the band one step. Agreement is noted only.
Single-word and very short names match exactly or not at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from rapidfuzz import fuzz, process

from dd_agents.screening.models import ListEntry, MatchBand, ScreenHit

if TYPE_CHECKING:
    from collections.abc import Iterable

QueryKind = Literal["person", "organization"]

# Scores are rapidfuzz ``ratio`` values (0-100) on word-sorted names.
STRONG_MIN_SCORE = 92.0
POSSIBLE_MIN_SCORE = 85.0
# Reported score for a "contains" match. Fixed so such hits rank below spelling matches.
CONTAINS_SCORE = 85.0
# Fewer characters than this: exact match only.
MIN_FUZZY_LENGTH = 4
# Shared words needed for a "contains" match.
MIN_SHARED_WORDS = 2
# Candidates examined per query before kind filtering and de-duplication.
CANDIDATE_LIMIT = 200

_PUNCTUATION = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACES = re.compile(r"\s+")

_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "llc", "llp", "lp", "ltd", "limited", "co", "company",
        "plc", "gmbh", "ag", "sa", "nv", "bv", "sas", "sarl", "srl", "spa", "pty", "ulc", "oy", "ab", "as",
        "kg", "ooo", "jsc", "pjsc", "ojsc", "fze", "fzco",
    }
)  # fmt: skip

_BAND_RANK: dict[MatchBand, int] = {"exact": 3, "strong": 2, "possible": 1}
_LOWER: dict[MatchBand, MatchBand] = {"exact": "strong", "strong": "possible", "possible": "possible"}


def normalize_name(name: str, kind: QueryKind) -> str:
    """Return the comparison form: casefolded, accents and punctuation removed, scripts kept.

    Organizations also lose trailing legal suffixes ("Co., Ltd.").
    """
    text = unicodedata.normalize("NFKC", name).casefold()
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    text = _SPACES.sub(" ", _PUNCTUATION.sub(" ", text)).strip()
    if kind == "organization":
        words = text.split()
        while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
            words.pop()
        text = " ".join(words)
    return text


def _sorted_key(normalized: str) -> str:
    return " ".join(sorted(normalized.split()))


@dataclass(frozen=True)
class _Candidate:
    entry_idx: int
    name: str
    key: str  # words sorted
    words: frozenset[str]


class _Group:
    """All names of one comparison group (person-like or organization-like)."""

    def __init__(self, kind: QueryKind) -> None:
        self.kind = kind
        self.candidates: list[_Candidate] = []
        self.by_key: dict[str, list[int]] = {}
        self._keys: list[str] | None = None

    def add(self, entry_idx: int, name: str) -> None:
        normalized = normalize_name(name, self.kind)
        if not normalized:
            return
        key = _sorted_key(normalized)
        self.by_key.setdefault(key, []).append(len(self.candidates))
        self.candidates.append(_Candidate(entry_idx, name, key, frozenset(normalized.split())))
        self._keys = None

    @property
    def keys(self) -> list[str]:
        if self._keys is None:
            self._keys = [c.key for c in self.candidates]
        return self._keys


class ScreeningIndex:
    """In-memory index over list entries. Build once, search many times."""

    def __init__(self, entries: Iterable[ListEntry]) -> None:
        self._entries: list[ListEntry] = list(entries)
        self._groups: dict[QueryKind, _Group] = {"person": _Group("person"), "organization": _Group("organization")}
        for idx, entry in enumerate(self._entries):
            kinds: tuple[QueryKind, ...]
            if entry.kind == "person":
                kinds = ("person",)
            elif entry.kind == "unknown":
                kinds = ("person", "organization")
            else:
                kinds = ("organization",)
            for kind in kinds:
                for name in [entry.name, *entry.aliases]:
                    self._groups[kind].add(idx, name)

    def __len__(self) -> int:
        return len(self._entries)

    def search(
        self,
        query: str,
        kind: QueryKind,
        *,
        birth_year: int | None = None,
        country: str | None = None,
        limit: int = 10,
    ) -> list[ScreenHit]:
        """Return possible matches, best first, one per entry."""
        normalized = normalize_name(query, kind)
        if not normalized:
            return []
        group = self._groups[kind]
        q_key = _sorted_key(normalized)
        q_words = frozenset(normalized.split())

        best: dict[int, tuple[MatchBand, float, str]] = {}

        def offer(entry_idx: int, band: MatchBand, score: float, name: str) -> None:
            current = best.get(entry_idx)
            if current is None or (_BAND_RANK[band], score) > (_BAND_RANK[current[0]], current[1]):
                best[entry_idx] = (band, score, name)

        for pos in group.by_key.get(q_key, []):
            cand = group.candidates[pos]
            offer(cand.entry_idx, "exact", 100.0, cand.name)

        if len(q_words) >= 2 and len(normalized) >= MIN_FUZZY_LENGTH:
            for _key, score, pos in process.extract(
                q_key, group.keys, scorer=fuzz.ratio, score_cutoff=POSSIBLE_MIN_SCORE, limit=CANDIDATE_LIMIT
            ):
                cand = group.candidates[pos]
                if cand.key == q_key or len(cand.words) < 2:
                    continue
                strong = score >= STRONG_MIN_SCORE and len(cand.words) == len(q_words)
                offer(cand.entry_idx, "strong" if strong else "possible", float(score), cand.name)
            for _key, _s, pos in process.extract(
                q_key, group.keys, scorer=fuzz.token_set_ratio, score_cutoff=100.0, limit=CANDIDATE_LIMIT
            ):
                cand = group.candidates[pos]
                if cand.key == q_key or len(cand.words) < 2:
                    continue
                shared = q_words & cand.words
                if len(shared) >= MIN_SHARED_WORDS and (shared == q_words or shared == cand.words):
                    offer(cand.entry_idx, "possible", CONTAINS_SCORE, cand.name)

        hits = [self._to_hit(query, kind, idx, *found, birth_year, country) for idx, found in best.items()]
        hits.sort(key=lambda h: (-_BAND_RANK[h.band], -h.score, h.entry.source, h.entry.uid))
        return hits[:limit]

    def _to_hit(
        self,
        query: str,
        kind: QueryKind,
        idx: int,
        band: MatchBand,
        score: float,
        matched: str,
        birth_year: int | None,
        country: str | None,
    ) -> ScreenHit:
        entry = self._entries[idx]
        notes: list[str] = []
        if birth_year is not None and entry.birth_years:
            if birth_year in entry.birth_years:
                notes.append("birth year agrees")
            else:
                notes.append("birth year differs")
                band = _LOWER[band]
        if country and entry.countries and country.casefold() in {c.casefold() for c in entry.countries}:
            notes.append("country agrees")
        return ScreenHit(
            query=query,
            query_kind=kind,
            entry=entry,
            matched_name=matched,
            score=score,
            band=band,
            corroboration=notes,
        )
