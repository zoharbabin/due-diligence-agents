"""6-pass cascading entity resolver.

Matches subject names across contracts, databases, directories, and
financial data.  Implements a deterministic 6-pass cascade with
short-name guards, an exclusion list, per-entry cache invalidation,
and comprehensive match logging.

Passes
------
1. Exact match after preprocessing
2. Alias lookup  (``entity_aliases.canonical_to_variants``)
3. Fuzzy matching  (``rapidfuzz.fuzz.token_sort_ratio``)
4. TF-IDF cosine similarity  (``sklearn`` character n-grams)
5. Parent-child corporate hierarchy lookup
6. Manual review queue  (unmatched gap logged)
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import numpy as np
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from dd_agents.entity_resolution.cache import EntityResolutionCache
from dd_agents.entity_resolution.logging import MatchLogger
from dd_agents.utils.constants import (
    FUZZY_THRESHOLD_LONG,
    FUZZY_THRESHOLD_MEDIUM,
    SHORT_NAME_MAX_LEN,
    TFIDF_THRESHOLD,
)
from dd_agents.utils.naming import preprocess_name

if TYPE_CHECKING:
    from pathlib import Path

    from dd_agents.entity_resolution.dedup import CrossDocumentDeduplicator

# ======================================================================
# Individual pass functions
# ======================================================================


def _pass_1_exact_match(
    preprocessed_source: str,
    target_names: dict[str, str],
) -> str | None:
    """Exact string comparison after normalisation.

    Returns the original (un-preprocessed) target name, or ``None``.
    """
    return target_names.get(preprocessed_source)


def _pass_2_alias_lookup(
    source_name: str,
    preprocessed_source: str,
    canonical_to_variants: dict[str, list[str]],
) -> str | None:
    """Check ``entity_aliases.canonical_to_variants`` from deal-config.

    Both the raw *source_name* and *preprocessed_source* are checked
    against all variants (also preprocessed).  Returns the canonical name.
    """
    for canonical, variants in canonical_to_variants.items():
        preprocessed_variants = [preprocess_name(v) for v in variants]
        # Check raw name
        if source_name in variants:
            return canonical
        # Check preprocessed name
        if preprocessed_source in preprocessed_variants:
            return canonical
        # Check if canonical itself matches
        if preprocessed_source == preprocess_name(canonical):
            return canonical

    return None


def _pass_3_fuzzy_match(
    preprocessed_source: str,
    target_names: dict[str, str],
    preprocessed_guards: list[str],
) -> tuple[str | None, float]:
    """Fuzzy matching with length-based thresholds and short name guard.

    Returns ``(matched_original_name, score)`` or ``(None, best_score)``.
    """
    source_len = len(preprocessed_source)

    # Short Name Guard: names <= 5 chars after preprocessing are NEVER
    # eligible for fuzzy matching.
    if source_len <= SHORT_NAME_MAX_LEN:
        return (None, 0.0)

    # Also check the explicit short_name_guard list
    if preprocessed_source in preprocessed_guards:
        return (None, 0.0)

    # Determine threshold based on length
    threshold = FUZZY_THRESHOLD_LONG if source_len > 8 else FUZZY_THRESHOLD_MEDIUM

    best_match: str | None = None
    best_score: float = 0.0

    for preprocessed_target, original_target in target_names.items():
        score = fuzz.token_sort_ratio(preprocessed_source, preprocessed_target)

        if score > best_score:
            best_score = score
            if score >= threshold:
                best_match = original_target

    return (best_match, best_score)


def _pass_4_tfidf_match(
    preprocessed_source: str,
    target_names: dict[str, str],
    preprocessed_guards: list[str],
) -> tuple[str | None, float]:
    """TF-IDF cosine similarity on character 3-grams and 4-grams.

    Returns ``(matched_original_name, score)`` or ``(None, best_score)``.
    """
    source_len = len(preprocessed_source)

    # Same short name guard as fuzzy matching
    if source_len <= SHORT_NAME_MAX_LEN:
        return (None, 0.0)

    if preprocessed_source in preprocessed_guards:
        return (None, 0.0)

    # Build TF-IDF matrix for all target names
    target_list = list(target_names.keys())
    if not target_list:
        return (None, 0.0)

    all_names = [preprocessed_source] + target_list

    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 4),
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(all_names)
    except ValueError:
        # Too few characters for n-grams
        return (None, 0.0)

    # Compute cosine similarity between source (index 0) and all targets
    similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])[0]

    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    if best_score >= TFIDF_THRESHOLD:
        best_preprocessed = target_list[best_idx]
        return (target_names[best_preprocessed], best_score)

    return (None, best_score)


def _pass_5_parent_child(
    source_name: str,
    preprocessed_source: str,
    parent_child: dict[str, list[str]],
    target_names: dict[str, str],
) -> str | None:
    """Check parent-child corporate relationships.

    ``parent_child`` maps ``parent_name -> [child_name, ...]``.
    If *source* matches a child, return the parent as canonical.
    Also checks transitively: ``WidgetCo -> DataFlow -> Apex Digital``.
    """
    # Build child -> parent lookup
    child_to_parent: dict[str, str] = {}
    for parent, children in parent_child.items():
        for child in children:
            child_to_parent[preprocess_name(child)] = parent

    # Walk the child -> parent chain (handles both direct and transitive).
    # We keep walking until we either find a parent in target_names or
    # exhaust the chain.
    visited: set[str] = set()
    current = preprocessed_source

    while current in child_to_parent and current not in visited:
        visited.add(current)
        parent_raw = child_to_parent[current]
        preprocessed_parent = preprocess_name(parent_raw)
        if preprocessed_parent in target_names:
            return target_names[preprocessed_parent]
        current = preprocessed_parent

    # If we found a parent but it was not in targets, do NOT return it.
    # Returning a constructed parent name that doesn't exist in the known
    # entity set produces phantom matches.  Only target-validated parents
    # are returned (handled inside the loop above).
    return None


def _pass_6_manual_review(
    source_name: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Log unmatched name for manual review.

    Returns the unmatched entry for ``entity_matches.json``.
    """
    return {
        "source_name": source_name,
        "source": "reference_file",  # overridden by caller
        "attempts": attempts,
        "resolution": "unmatched_gap_logged",
    }


def _is_excluded(
    name: str,
    preprocessed_name_val: str,
    exclusions: list[str],
) -> bool:
    """Check if a name is on the exclusion list."""
    preprocessed_exclusions = [preprocess_name(e) for e in exclusions]
    return name in exclusions or preprocessed_name_val in preprocessed_exclusions


# ======================================================================
# EntityResolver
# ======================================================================


class EntityResolver:
    """6-pass cascading entity resolution matcher.

    Parameters
    ----------
    subjects_csv:
        List of dicts with at least a ``"subject_name"`` key.
    entity_aliases:
        The ``entity_aliases`` section from ``deal-config.json``.
    cache_path:
        Filesystem path to the PERMANENT cache file.
    run_id:
        Current pipeline run identifier.
    """

    def __init__(
        self,
        subjects_csv: list[dict[str, Any]] | None = None,
        entity_aliases: dict[str, Any] | None = None,
        cache_path: Path | None = None,
        run_id: str = "",
    ) -> None:
        if cache_path is None:
            raise TypeError("cache_path is required")
        _csv = subjects_csv or []
        _aliases = entity_aliases or {}
        self.subjects = _csv
        self.run_id = run_id

        # Parse alias config (with safe defaults if absent)
        self.canonical_to_variants: dict[str, list[str]] = _aliases.get("canonical_to_variants", {})
        self.short_name_guard: list[str] = _aliases.get("short_name_guard", [])
        self.exclusions: list[str] = _aliases.get("exclusions", [])
        self.parent_child: dict[str, list[str]] = _aliases.get("parent_child", {})

        # Pre-compute the preprocessed guard list once (avoids re-computing per resolve call)
        self._preprocessed_guards: list[str] = [preprocess_name(n) for n in self.short_name_guard]

        # Build target name lookup: preprocessed -> original
        # Skip entries that preprocess to empty string (e.g. "Inc.") to avoid
        # false-positive exact matches and dictionary key collisions.
        self.target_names: dict[str, str] = {}
        for entry in _csv:
            original = entry.get("subject_name", "")
            preprocessed = preprocess_name(original)
            if preprocessed:
                self.target_names[preprocessed] = original

        # Load cache
        self.cache = EntityResolutionCache(cache_path)
        self._entity_aliases = _aliases
        self.config_hash = self._compute_config_hash(_aliases)

        # Match logger
        self._logger = MatchLogger()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_config_hash(entity_aliases: dict[str, Any]) -> str:
        """SHA-256 of the ``entity_aliases`` section for cache invalidation."""
        content = json.dumps(entity_aliases, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Single-name resolution
    # ------------------------------------------------------------------

    def resolve_name(
        self,
        source_name: str,
        source_type: str = "reference_file",
    ) -> str | None:
        """Resolve a single name through the 6-pass cascade.

        Parameters
        ----------
        source_name:
            The name to resolve.
        source_type:
            Where the name came from (``"reference_file"``, ``"database"``, etc.).

        Returns
        -------
        str | None
            Canonical subject name from ``subjects.csv``, or ``None`` if
            unmatched.
        """
        preprocessed = preprocess_name(source_name)
        attempts: list[dict[str, Any]] = []

        # Check exclusion list first
        if _is_excluded(source_name, preprocessed, self.exclusions):
            self._logger.add_rejected(
                {
                    "source_name": source_name,
                    "source": source_type,
                    "reason": "in exclusion list",
                }
            )
            return None

        # Check cache before running passes
        cached_result = self.cache.lookup(source_name, self.config_hash, self.target_names)
        if cached_result is not None:
            canonical: str = cached_result["canonical"]
            self.cache.confirm_entry(source_name, self.run_id)
            self._logger.add_match(
                source_name=source_name,
                source_type=source_type,
                matched_name=canonical,
                pass_num=cached_result["match_pass"],
                method="cache_hit",
                confidence=cached_result["confidence"],
                canonical_name=canonical,
            )
            return canonical

        # ------ Pass 1: Exact match after preprocessing ------
        match = _pass_1_exact_match(preprocessed, self.target_names)
        attempts.append(
            {
                "pass": 1,
                "method": "exact",
                "result": "match" if match else "no_match",
            }
        )
        if match:
            self._record_match(
                source_name,
                match,
                source_type,
                pass_num=1,
                method="exact",
                confidence=1.0,
            )
            return match

        # ------ Pass 2: Alias lookup ------
        match = _pass_2_alias_lookup(
            source_name,
            preprocessed,
            self.canonical_to_variants,
        )
        attempts.append(
            {
                "pass": 2,
                "method": "alias_lookup",
                "result": "match" if match else "no_match",
            }
        )
        if match:
            self._record_match(
                source_name,
                match,
                source_type,
                pass_num=2,
                method="alias_lookup",
                confidence=1.0,
            )
            return match

        # ------ Pass 3: Fuzzy match (with short name guard) ------
        fuzzy_match, fuzzy_score = _pass_3_fuzzy_match(
            preprocessed,
            self.target_names,
            self._preprocessed_guards,
        )
        attempt_info: dict[str, Any] = {"pass": 3, "method": "fuzzy"}
        if fuzzy_match:
            # Check exclusion on the matched name
            if _is_excluded(fuzzy_match, preprocess_name(fuzzy_match), self.exclusions):
                attempt_info.update(
                    {
                        "best_match": fuzzy_match,
                        "score": fuzzy_score,
                        "result": "excluded",
                    }
                )
                self._logger.add_rejected(
                    {
                        "source_name": source_name,
                        "source": source_type,
                        "rejected_match": fuzzy_match,
                        "match_pass": 3,
                        "score": fuzzy_score,
                        "reason": "matched name in exclusion list",
                    }
                )
                fuzzy_match = None
            else:
                attempt_info.update(
                    {
                        "best_match": fuzzy_match,
                        "score": fuzzy_score,
                        "result": "match",
                    }
                )
        elif fuzzy_score > 0:
            attempt_info.update(
                {
                    "best_match": None,
                    "score": fuzzy_score,
                    "result": "below_threshold",
                }
            )
        else:
            attempt_info.update(
                {
                    "result": ("no_match_short_name_guard" if len(preprocessed) <= SHORT_NAME_MAX_LEN else "no_match"),
                }
            )
        attempts.append(attempt_info)

        if fuzzy_match:
            self._record_match(
                source_name,
                fuzzy_match,
                source_type,
                pass_num=3,
                method="fuzzy",
                confidence=round(fuzzy_score / 100.0, 2),
            )
            return fuzzy_match

        # ------ Pass 4: TF-IDF cosine similarity ------
        tfidf_match, tfidf_score = _pass_4_tfidf_match(
            preprocessed,
            self.target_names,
            self._preprocessed_guards,
        )
        attempt_info = {"pass": 4, "method": "tfidf"}
        if tfidf_match:
            if _is_excluded(tfidf_match, preprocess_name(tfidf_match), self.exclusions):
                attempt_info.update(
                    {
                        "best_match": tfidf_match,
                        "score": tfidf_score,
                        "result": "excluded",
                    }
                )
                self._logger.add_rejected(
                    {
                        "source_name": source_name,
                        "source": source_type,
                        "rejected_match": tfidf_match,
                        "match_pass": 4,
                        "score": tfidf_score,
                        "reason": "matched name in exclusion list",
                    }
                )
                tfidf_match = None
            else:
                attempt_info.update(
                    {
                        "best_match": tfidf_match,
                        "score": tfidf_score,
                        "result": "match",
                    }
                )
        elif tfidf_score > 0:
            attempt_info.update(
                {
                    "best_match": None,
                    "score": tfidf_score,
                    "result": "below_threshold",
                }
            )
        else:
            attempt_info.update({"result": "no_match"})
        attempts.append(attempt_info)

        if tfidf_match:
            self._record_match(
                source_name,
                tfidf_match,
                source_type,
                pass_num=4,
                method="tfidf",
                confidence=round(tfidf_score, 2),
            )
            return tfidf_match

        # ------ Pass 5: Parent-child lookup ------
        match = _pass_5_parent_child(
            source_name,
            preprocessed,
            self.parent_child,
            self.target_names,
        )
        attempts.append(
            {
                "pass": 5,
                "method": "parent_child",
                "result": "match" if match else "no_match",
            }
        )
        if match:
            self._record_match(
                source_name,
                match,
                source_type,
                pass_num=5,
                method="parent_child",
                confidence=0.9,
            )
            return match

        # ------ Pass 6: Manual review (no match found) ------
        unmatched_entry = _pass_6_manual_review(source_name, attempts)
        unmatched_entry["source"] = source_type
        self._logger.add_unmatched(unmatched_entry)
        return None

    # ------------------------------------------------------------------
    # Batch resolution
    # ------------------------------------------------------------------

    def resolve_all(
        self,
        names: list[str],
        source_type: str = "reference_file",
    ) -> dict[str, str | None]:
        """Resolve a list of names.

        Calls :meth:`cache.compute_invalidation` before resolution and
        :meth:`cache.save` after resolution completes so that the
        PERMANENT cache is always up to date.

        Returns ``{source_name: canonical_name | None}``.
        """
        self.cache.compute_invalidation(self._entity_aliases, self.config_hash)

        results: dict[str, str | None] = {}
        for name in names:
            results[name] = self.resolve_name(name, source_type)

        self.cache.save(self.run_id)
        return results

    # ------------------------------------------------------------------
    # Batch resolution with cross-document dedup (Issue #11)
    # ------------------------------------------------------------------

    def resolve_all_with_dedup(
        self,
        names_by_source: dict[str, list[str]],
        source_type: str = "reference_file",
    ) -> tuple[dict[str, str | None], CrossDocumentDeduplicator]:
        """Resolve names grouped by source file, tracking cross-document dedup.

        Parameters
        ----------
        names_by_source:
            ``{source_file: [name1, name2, ...]}``.
        source_type:
            Source type label for the match log.

        Returns
        -------
        tuple[dict[str, str | None], CrossDocumentDeduplicator]
            A flat ``{source_name: canonical | None}`` resolution map
            and the populated deduplicator.
        """
        from dd_agents.entity_resolution.dedup import CrossDocumentDeduplicator

        self.cache.compute_invalidation(self._entity_aliases, self.config_hash)

        dedup = CrossDocumentDeduplicator()
        all_results: dict[str, str | None] = {}

        for source_file, names in names_by_source.items():
            for name in names:
                canonical = self.resolve_name(name, source_type)
                all_results[name] = canonical
                if canonical is not None:
                    dedup.add_resolution(name, canonical, source_file)

        self.cache.save(self.run_id)
        return all_results, dedup

    # ------------------------------------------------------------------
    # Match log
    # ------------------------------------------------------------------

    def get_match_log(self) -> dict[str, Any]:
        """Return the complete match log for ``entity_matches.json``."""
        return self._logger.get_match_log()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_match(
        self,
        source_name: str,
        matched_name: str,
        source_type: str,
        pass_num: int,
        method: str,
        confidence: float,
    ) -> None:
        """Record a successful match and update cache."""
        self._logger.add_match(
            source_name=source_name,
            source_type=source_type,
            matched_name=matched_name,
            pass_num=pass_num,
            method=method,
            confidence=confidence,
            canonical_name=matched_name,
        )

        # Update cache
        self.cache.add_entry(
            source_name=source_name,
            canonical=matched_name,
            match_pass=pass_num,
            match_type=method,
            confidence=confidence,
            run_id=self.run_id,
        )
