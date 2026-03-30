# 09 -- Entity Resolution (6-Pass Cascading Matcher)

## Overview

Matching customer names across contracts, databases, directories, and financial data is the single largest source of errors in due diligence. Names vary: "GAG" vs "Global Analytics Group", "AlpineSys" vs "Alpine Systems, Inc.", "Metro Solutions" vs "MetroSoft" (wrong match). Entity resolution runs at pipeline step 7 and must complete before agents start.

The module implements a deterministic 6-pass cascading matcher with short-name guards (defined in §3, Pass 3 below -- these prevent false-positive matches on common abbreviated names like 'AI', 'IT', 'US'), an exclusion list, per-entry cache invalidation, and comprehensive match logging. Every resolution decision is auditable.

---

## 1. Input Sources

The entity resolver receives names from four sources and matches them against each other:

| Source | Description | Loaded From |
|--------|-------------|-------------|
| **customers.csv** | Customer names derived from data room directory structure | `_dd/forensic-dd/inventory/customers.csv` |
| **deal-config.json entity_aliases** | Human-curated canonical-to-variant mappings, short name guards, exclusions, parent-child relationships | `deal-config.json` `entity_aliases` section |
| **Reference files** | Customer names found in financial, pricing, and operational data | `_dd/forensic-dd/inventory/reference_files.json` `customers_mentioned` arrays |
| **Customer database** | External customer list from `source_of_truth.customer_database` | If configured in deal-config.json |

The primary matching direction is: **reference file names -> customers.csv names**. The goal is to map every customer name found in reference data to its canonical entry in customers.csv.

---

## 2. Name Preprocessing

All names are normalized before any matching pass. Preprocessing is applied once and cached for all subsequent passes.

```python
# src/dd_agents/entity/preprocessing.py

import re
import unicodedata

# Legal suffixes to strip (case-insensitive)
LEGAL_SUFFIXES = [
    r"\bInc\.?$",
    r"\bCorp\.?$",
    r"\bCorporation$",
    r"\bLLC$",
    r"\bLtd\.?$",
    r"\bL\.?P\.?$",
    r"\bGmbH$",
    r"\bS\.?A\.?$",
    r"\bPty\.?$",
    r"\bULC$",
    r"\bLP$",
    r"\bLimited$",
    r"\bCompany$",
    r"\bCo\.?$",
    r"\bPLC$",
    r"\bAG$",
    r"\bN\.?V\.?$",
    r"\bB\.?V\.?$",
    r"\bS\.?A\.?S\.?$",
]

# Compiled regex for all suffixes (anchored to end of string)
_SUFFIX_PATTERN = re.compile(
    r",?\s*(?:" + "|".join(LEGAL_SUFFIXES) + r")\s*$",
    re.IGNORECASE,
)

def preprocess_name(name: str) -> str:
    """Normalize a company name for matching.

    Steps:
        1. Unicode NFKC normalization
        2. Lowercase
        3. Strip legal suffixes
        4. Replace special characters (& ' / , .) with space
        5. Collapse whitespace
        6. Strip leading/trailing whitespace

    Examples:
        "Apex Digital Inc." -> "apex digital"
        "Global Analytics Group" -> "global analytics group"
        "Alpine Systems, Inc." -> "alpine systems"
        "GAG" -> "gag"
    """
    name = unicodedata.normalize("NFKC", name)
    name = name.lower()

    # Strip legal suffixes (iteratively in case of stacked suffixes)
    for _ in range(3):
        cleaned = _SUFFIX_PATTERN.sub("", name).strip()
        if cleaned == name:
            break
        name = cleaned

    # Replace special characters with space
    name = name.replace("&", " ")
    name = name.replace("'", " ")
    name = name.replace("/", " ")
    name = name.replace(",", " ")
    name = name.replace(".", " ")

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return name


def to_customer_safe_name(name: str) -> str:
    """Convert a customer name to the safe filename convention.

    Steps:
        1. Lowercase
        2. Strip legal suffixes
        3. Replace spaces and special chars (& ' / , .) with _
        4. Collapse consecutive underscores
        5. Strip leading/trailing underscores

    Examples:
        "Global Analytics Group" -> "global_analytics_group"
        "Alpine Systems, Inc." -> "alpine_systems"
        "GAG" -> "gag"
        "O'Brien Press" -> "o_brien_press"
        "Morgan & Mills" -> "morgan_mills"
    """
    name = unicodedata.normalize("NFKC", name)
    name = name.lower()

    # Strip legal suffixes
    for _ in range(3):
        cleaned = _SUFFIX_PATTERN.sub("", name).strip()
        if cleaned == name:
            break
        name = cleaned

    # Replace special characters and spaces with underscore
    name = name.replace("&", "_")
    name = name.replace("'", "_")
    name = name.replace("/", "_")
    name = name.replace(",", "_")
    name = name.replace(".", "_")
    name = name.replace(" ", "_")
    name = name.replace("-", "_")

    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name)

    # Strip leading/trailing underscores
    name = name.strip("_")

    return name
```

---

## 3. The 6-Pass Cascading Matcher

For each name requiring resolution, passes are applied in order. Matching stops at the first successful match. If no pass succeeds, the name is logged as unmatched.

### Pass 1: Exact Match After Preprocessing

```python
# src/dd_agents/entity/passes.py

def pass_1_exact_match(
    preprocessed_source: str,
    target_names: dict[str, str],   # preprocessed -> original
) -> str | None:
    """Exact string comparison after normalization.

    Returns the original (un-preprocessed) target name, or None.
    """
    return target_names.get(preprocessed_source)
```

**Example**: "Apex Digital Inc." preprocesses to "apex digital", which exactly matches "apex digital" (from directory name "Apex Digital"). Returns "Apex Digital".

### Pass 2: Alias Lookup

```python
def pass_2_alias_lookup(
    source_name: str,
    preprocessed_source: str,
    canonical_to_variants: dict[str, list[str]],
) -> str | None:
    """Check entity_aliases.canonical_to_variants from deal-config.json.

    Both the raw source name and preprocessed source are checked against
    all variants (also preprocessed). Returns the canonical name.
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
```

**Example**: "GAG" is found in variants for canonical "Global Analytics Group" -> returns "Global Analytics Group" with confidence 1.0.

> **Confidence scoring**: Aliases from deal-config.json always receive confidence 1.0 (user-verified). Fuzzy matches receive confidence proportional to their match score (e.g., 0.92 for a 92% rapidfuzz match).

### Pass 3: Fuzzy Matching (rapidfuzz)

```python
from rapidfuzz import fuzz

# Thresholds vary by name length (after preprocessing)
FUZZY_THRESHOLD_LONG = 88     # Names > 8 chars
FUZZY_THRESHOLD_MEDIUM = 95   # Names 5-8 chars
SHORT_NAME_MAX_LEN = 5        # Names <= 5 chars: NEVER fuzzy match

def pass_3_fuzzy_match(
    preprocessed_source: str,
    target_names: dict[str, str],   # preprocessed -> original
    short_name_guard: list[str],
) -> tuple[str | None, float]:
    """Fuzzy matching with length-based thresholds and short name guard.

    Returns (matched_original_name, score) or (None, best_score).
    """
    source_len = len(preprocessed_source)

    # Short Name Guard: names <= 5 chars after preprocessing are NEVER
    # eligible for fuzzy matching. They must match via exact (Pass 1)
    # or alias (Pass 2) only.
    if source_len <= SHORT_NAME_MAX_LEN:
        return (None, 0.0)

    # Also check the explicit short_name_guard list
    preprocessed_guards = [preprocess_name(n) for n in short_name_guard]
    if preprocessed_source in preprocessed_guards:
        return (None, 0.0)

    # Determine threshold based on length
    threshold = FUZZY_THRESHOLD_LONG if source_len > 8 else FUZZY_THRESHOLD_MEDIUM

    best_match = None
    best_score = 0.0

    for preprocessed_target, original_target in target_names.items():
        # Use token_sort_ratio (handles word reordering)
        score = fuzz.token_sort_ratio(preprocessed_source, preprocessed_target)

        if score > best_score:
            best_score = score
            if score >= threshold:
                best_match = original_target

    return (best_match, best_score)
```

**Threshold rationale**:
- Names >8 chars (e.g., "metro solutions") have enough signal for 88% threshold
- Names 5-8 chars (e.g., "nexon") need 95% to avoid false positives
- Names <=5 chars (e.g., "d b", "hp") are NEVER fuzzy matched -- too ambiguous

### Pass 4: TF-IDF Cosine Similarity

For large name lists (>50 names), TF-IDF on character n-grams catches abbreviations and word reorderings that fuzzy matching misses.

```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

TFIDF_THRESHOLD = 0.80

def pass_4_tfidf_match(
    preprocessed_source: str,
    target_names: dict[str, str],   # preprocessed -> original
    short_name_guard: list[str],
) -> tuple[str | None, float]:
    """TF-IDF cosine similarity on character 3-grams and 4-grams.

    Returns (matched_original_name, score) or (None, best_score).
    """
    source_len = len(preprocessed_source)

    # Same short name guard as fuzzy matching
    if source_len <= SHORT_NAME_MAX_LEN:
        return (None, 0.0)

    preprocessed_guards = [preprocess_name(n) for n in short_name_guard]
    if preprocessed_source in preprocessed_guards:
        return (None, 0.0)

    # Build TF-IDF matrix for all target names
    target_list = list(target_names.keys())
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
```

### Pass 5: Parent-Child Lookup

Checks `entity_aliases.parent_child` for corporate hierarchy relationships. A subsidiary name matches to its parent's canonical entry.

```python
def pass_5_parent_child(
    source_name: str,
    preprocessed_source: str,
    parent_child: dict[str, list[str]],
    target_names: dict[str, str],
) -> str | None:
    """Check parent-child corporate relationships.

    parent_child maps parent_name -> [child_name, ...].
    If source matches a child, return the parent as canonical.
    Also checks transitively: WidgetCo -> DataFlow -> Apex Digital.
    """
    # Build child -> parent lookup
    child_to_parent: dict[str, str] = {}
    for parent, children in parent_child.items():
        for child in children:
            child_to_parent[preprocess_name(child)] = parent

    # Direct child match
    if preprocessed_source in child_to_parent:
        parent = child_to_parent[preprocessed_source]
        # Verify parent is in target names
        preprocessed_parent = preprocess_name(parent)
        if preprocessed_parent in target_names:
            return target_names[preprocessed_parent]
        return parent

    # Transitive check (grandchild -> parent)
    visited = set()
    current = preprocessed_source
    while current in child_to_parent and current not in visited:
        visited.add(current)
        parent = child_to_parent[current]
        preprocessed_parent = preprocess_name(parent)
        if preprocessed_parent in target_names:
            return target_names[preprocessed_parent]
        current = preprocessed_parent

    return None
```

### Pass 6: Manual Review Queue

Names that fail all 5 passes are logged as unmatched for human review. No guessing.

```python
def pass_6_manual_review(
    source_name: str,
    attempts: list[dict],
) -> dict:
    """Log unmatched name for manual review.

    Returns the unmatched entry for entity_matches.json.
    """
    return {
        "source_name": source_name,
        "source": "reference_file",   # or "database", overridden by caller
        "attempts": attempts,
        "resolution": "unmatched_gap_logged",
    }
```

---

## 4. Exclusion List

Names in `entity_aliases.exclusions` from deal-config.json are rejected even if they score above fuzzy/TF-IDF thresholds. This prevents known false positives.

```python
def is_excluded(
    name: str,
    preprocessed_name: str,
    exclusions: list[str],
) -> bool:
    """Check if a name is on the exclusion list."""
    preprocessed_exclusions = [preprocess_name(e) for e in exclusions]
    return (
        name in exclusions
        or preprocessed_name in preprocessed_exclusions
    )
```

**Example**: "MetroSoft" is in the exclusion list. Even if it fuzzy-matches "Metro Solutions" at 62%, the match is rejected. Without the exclusion list, the fuzzy matcher might return this as a low-confidence match.

---

## 5. The Entity Resolver

The resolver coordinates all 6 passes, respects the exclusion list, consults the cache, and produces the match log.

```python
# src/dd_agents/entity/resolver.py

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dd_agents.entity.preprocessing import preprocess_name, to_customer_safe_name
from dd_agents.entity.passes import (
    pass_1_exact_match,
    pass_2_alias_lookup,
    pass_3_fuzzy_match,
    pass_4_tfidf_match,
    pass_5_parent_child,
    pass_6_manual_review,
    is_excluded,
)
from dd_agents.entity.cache import EntityResolutionCache
from dd_agents.models.entity import EntityMatch, EntityMatchLog


class EntityResolver:
    """6-pass cascading entity resolution matcher."""

    def __init__(
        self,
        customers_csv: list[dict],
        entity_aliases: dict,
        cache_path: Path,
        run_id: str,
    ):
        self.customers = customers_csv
        self.run_id = run_id

        # Parse alias config (with safe defaults if absent)
        self.canonical_to_variants = entity_aliases.get("canonical_to_variants", {})
        self.short_name_guard = entity_aliases.get("short_name_guard", [])
        self.exclusions = entity_aliases.get("exclusions", [])
        self.parent_child = entity_aliases.get("parent_child", {})

        # Build target name lookup: preprocessed -> original
        self.target_names: dict[str, str] = {}
        for cust in customers_csv:
            original = cust["customer_name"]
            preprocessed = preprocess_name(original)
            self.target_names[preprocessed] = original

        # Load cache
        self.cache = EntityResolutionCache(cache_path)
        self.config_hash = self._compute_config_hash(entity_aliases)

        # Results
        self.matches: list[dict] = []
        self.unmatched: list[dict] = []
        self.rejected: list[dict] = []

    def _compute_config_hash(self, entity_aliases: dict) -> str:
        """SHA-256 of the entity_aliases section for cache invalidation."""
        content = json.dumps(entity_aliases, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def resolve_name(
        self,
        source_name: str,
        source_type: str = "reference_file",
    ) -> Optional[str]:
        """Resolve a single name through the 6-pass cascade.

        Args:
            source_name: The name to resolve
            source_type: Where the name came from ("reference_file", "database", etc.)

        Returns:
            Canonical customer name from customers.csv, or None if unmatched.
        """
        preprocessed = preprocess_name(source_name)
        attempts = []

        # Check exclusion list first
        if is_excluded(source_name, preprocessed, self.exclusions):
            self.rejected.append({
                "source_name": source_name,
                "source": source_type,
                "reason": "in exclusion list",
            })
            return None

        # Check cache before running passes
        cached_result = self.cache.lookup(
            source_name, self.config_hash, self.target_names
        )
        if cached_result is not None:
            canonical = cached_result["canonical"]
            self.cache.confirm_entry(source_name, self.run_id)
            self.matches.append({
                "source_name": source_name,
                "source": source_type,
                "matched_name": canonical,
                "target": "customers.csv",
                "match_pass": cached_result["match_pass"],
                "match_method": "cache_hit",
                "confidence": cached_result["confidence"],
                "canonical_name": canonical,
            })
            return canonical

        # Pass 1: Exact match after preprocessing
        match = pass_1_exact_match(preprocessed, self.target_names)
        attempts.append({"pass": 1, "method": "exact", "result": "match" if match else "no_match"})
        if match:
            self._record_match(source_name, match, source_type, pass_num=1, method="exact", confidence=1.0)
            return match

        # Pass 2: Alias lookup
        match = pass_2_alias_lookup(source_name, preprocessed, self.canonical_to_variants)
        attempts.append({"pass": 2, "method": "alias_lookup", "result": "match" if match else "no_match"})
        if match:
            self._record_match(source_name, match, source_type, pass_num=2, method="alias_lookup", confidence=1.0)
            return match

        # Pass 3: Fuzzy match (with short name guard)
        fuzzy_match, fuzzy_score = pass_3_fuzzy_match(
            preprocessed, self.target_names, self.short_name_guard
        )
        attempt_info = {"pass": 3, "method": "fuzzy"}
        if fuzzy_match:
            # Check exclusion on the matched name
            if is_excluded(fuzzy_match, preprocess_name(fuzzy_match), self.exclusions):
                attempt_info.update({"best_match": fuzzy_match, "score": fuzzy_score, "result": "excluded"})
                self.rejected.append({
                    "source_name": source_name,
                    "source": source_type,
                    "rejected_match": fuzzy_match,
                    "match_pass": 3,
                    "score": fuzzy_score,
                    "reason": "matched name in exclusion list",
                })
                fuzzy_match = None
            else:
                attempt_info.update({"best_match": fuzzy_match, "score": fuzzy_score, "result": "match"})
        elif fuzzy_score > 0:
            attempt_info.update({"best_match": None, "score": fuzzy_score, "result": "below_threshold"})
        else:
            attempt_info.update({"result": "no_match_short_name_guard" if len(preprocessed) <= 5 else "no_match"})
        attempts.append(attempt_info)

        if fuzzy_match:
            self._record_match(
                source_name, fuzzy_match, source_type,
                pass_num=3, method="fuzzy",
                confidence=round(fuzzy_score / 100.0, 2),
            )
            return fuzzy_match

        # Pass 4: TF-IDF cosine similarity
        tfidf_match, tfidf_score = pass_4_tfidf_match(
            preprocessed, self.target_names, self.short_name_guard
        )
        attempt_info = {"pass": 4, "method": "tfidf"}
        if tfidf_match:
            if is_excluded(tfidf_match, preprocess_name(tfidf_match), self.exclusions):
                attempt_info.update({"best_match": tfidf_match, "score": tfidf_score, "result": "excluded"})
                self.rejected.append({
                    "source_name": source_name,
                    "source": source_type,
                    "rejected_match": tfidf_match,
                    "match_pass": 4,
                    "score": tfidf_score,
                    "reason": "matched name in exclusion list",
                })
                tfidf_match = None
            else:
                attempt_info.update({"best_match": tfidf_match, "score": tfidf_score, "result": "match"})
        elif tfidf_score > 0:
            attempt_info.update({"best_match": None, "score": tfidf_score, "result": "below_threshold"})
        else:
            attempt_info.update({"result": "no_match"})
        attempts.append(attempt_info)

        if tfidf_match:
            self._record_match(
                source_name, tfidf_match, source_type,
                pass_num=4, method="tfidf",
                confidence=round(tfidf_score, 2),
            )
            return tfidf_match

        # Pass 5: Parent-child lookup
        match = pass_5_parent_child(
            source_name, preprocessed, self.parent_child, self.target_names
        )
        attempts.append({"pass": 5, "method": "parent_child", "result": "match" if match else "no_match"})
        if match:
            self._record_match(source_name, match, source_type, pass_num=5, method="parent_child", confidence=0.9)
            return match

        # Pass 6: Manual review (no match found)
        unmatched_entry = pass_6_manual_review(source_name, attempts)
        unmatched_entry["source"] = source_type
        self.unmatched.append(unmatched_entry)
        return None

    def resolve_all(
        self,
        names: list[str],
        source_type: str = "reference_file",
    ) -> dict[str, Optional[str]]:
        """Resolve a list of names. Returns {source_name: canonical_name | None}."""
        results = {}
        for name in names:
            results[name] = self.resolve_name(name, source_type)
        return results

    def get_match_log(self) -> dict:
        """Return the complete match log for entity_matches.json."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "matches": self.matches,
            "unmatched": self.unmatched,
            "rejected": self.rejected,
        }

    def _record_match(
        self,
        source_name: str,
        matched_name: str,
        source_type: str,
        pass_num: int,
        method: str,
        confidence: float,
    ):
        """Record a successful match and update cache."""
        self.matches.append({
            "source_name": source_name,
            "source": source_type,
            "matched_name": matched_name,
            "target": "customers.csv",
            "match_pass": pass_num,
            "match_method": method,
            "confidence": confidence,
            "canonical_name": matched_name,
        })

        # Update cache
        self.cache.add_entry(
            source_name=source_name,
            canonical=matched_name,
            match_pass=pass_num,
            match_type=method,
            confidence=confidence,
            run_id=self.run_id,
        )
```

---

## 6. Match Logging

Every entity resolution attempt is recorded in `_dd/forensic-dd/inventory/entity_matches.json` (FRESH tier, rebuilt every run).

```json
{
  "generated_at": "2025-02-18T14:30:00Z",
  "matches": [
    {
      "source_name": "GAG",
      "source": "reference_file",
      "matched_name": "Global Analytics Group",
      "target": "customers.csv",
      "match_pass": 2,
      "match_method": "alias_lookup",
      "confidence": 1.0,
      "canonical_name": "Global Analytics Group"
    },
    {
      "source_name": "Alpine Systems, Inc.",
      "source": "database",
      "matched_name": "AlpineSys",
      "target": "customers.csv",
      "match_pass": 2,
      "match_method": "alias_lookup",
      "confidence": 1.0,
      "canonical_name": "Alpine Systems"
    },
    {
      "source_name": "Sierra Networks, Inc.",
      "source": "reference_file",
      "matched_name": "Sierra",
      "target": "customers.csv",
      "match_pass": 3,
      "match_method": "fuzzy",
      "confidence": 0.91,
      "canonical_name": "Sierra"
    }
  ],
  "unmatched": [
    {
      "source_name": "GridPoint Systems",
      "source": "database",
      "attempts": [
        {"pass": 1, "method": "exact", "result": "no_match"},
        {"pass": 2, "method": "alias_lookup", "result": "no_match"},
        {"pass": 3, "method": "fuzzy", "best_match": "GridScale", "score": 72, "result": "below_threshold"},
        {"pass": 4, "method": "tfidf", "best_match": "GridScale", "score": 0.65, "result": "below_threshold"},
        {"pass": 5, "method": "parent_child", "result": "no_match"}
      ],
      "resolution": "unmatched_gap_logged"
    }
  ],
  "rejected": [
    {
      "source_name": "MetroSoft",
      "source": "reference_file",
      "reason": "in exclusion list"
    },
    {
      "source_name": "MACo",
      "source": "database",
      "rejected_match": "Metro Solutions",
      "match_pass": 3,
      "score": 62,
      "reason": "matched name in exclusion list"
    }
  ]
}
```

---

## 7. Cache Learning Protocol (PERMANENT Tier)

The entity resolution cache at `_dd/entity_resolution_cache.json` (shared across all DD skills) persists confirmed matches across runs. On subsequent runs, cached entries are consulted before the 6-pass matcher, dramatically reducing resolution time.

### 7.1 Cache Structure

```json
{
  "version": 1,
  "last_updated": "2025-02-18T14:30:00Z",
  "last_updated_by": "forensic-dd",
  "last_updated_run_id": "20250218_143000",
  "config_hash": "a1b2c3d4...",
  "prior_config_snapshot": {
    "canonical_to_variants": {
      "Global Analytics Group": ["GAG", "GAnalytics", "Global Analytics"]
    },
    "short_name_guard": ["GAG", "DHL", "LG"],
    "exclusions": ["MetroSoft"],
    "parent_child": {"Apex Digital": ["DataFlow", "WidgetCo"]}
  },
  "entries": {
    "GAG": {
      "canonical": "Global Analytics Group",
      "match_pass": 2,
      "match_type": "alias_lookup",
      "confidence": 1.0,
      "entity_type": "customer",
      "first_seen_run": "20250218_143000",
      "last_confirmed_run": "20250218_143000",
      "confirmation_count": 1
    },
    "Sierra Networks, Inc.": {
      "canonical": "Sierra",
      "match_pass": 3,
      "match_type": "fuzzy",
      "confidence": 0.91,
      "entity_type": "customer",
      "first_seen_run": "20250218_143000",
      "last_confirmed_run": "20250220_091500",
      "confirmation_count": 3
    }
  },
  "unmatched": [
    {
      "name": "Unknown Entity LLC",
      "context": "Found in reference file Customer Database.xlsx row 45",
      "first_seen_run": "20250218_143000"
    }
  ]
}
```

### 7.2 Cache Lookup Flow

```
For each entity name requiring resolution:

  1. Check _dd/entity_resolution_cache.json for existing entry
  2. IF cache hit AND entry is NOT invalidated:
     -> Use cached match directly (skip 6-pass matcher)
     -> Increment confirmation_count
     -> Update last_confirmed_run
  3. IF cache hit BUT entry was invalidated by config_diff:
     -> Remove entry from cache
     -> Run 6-pass matcher for this name
     -> Add new result to cache
  4. IF cache miss:
     -> Run 6-pass matcher
     -> Add result to cache (match or unmatched)
```

### 7.3 Per-Entry Cache Invalidation

When the `entity_aliases` config hash differs from the cached `config_hash`, the cache is NOT fully invalidated. Instead, a targeted diff determines which entries need re-resolution.

```python
# src/dd_agents/entity/cache.py

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


class EntityResolutionCache:
    """PERMANENT-tier cache for entity resolution matches."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.data = self._load()
        self._invalidated_entries: set[str] = set()

    def _load(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                # Corrupted cache -- start fresh
                return self._empty_cache()
        return self._empty_cache()

    def _empty_cache(self) -> dict:
        return {
            "version": 1,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "last_updated_by": "forensic-dd",
            "last_updated_run_id": "",
            "config_hash": "",
            "prior_config_snapshot": {},
            "entries": {},
            "unmatched": [],
        }

    def compute_invalidation(
        self,
        current_config: dict,
        current_config_hash: str,
    ):
        """Compute which cache entries need re-resolution due to config changes.

        This implements the per-entry invalidation algorithm from the
        entity-resolution-protocol.md. Only entries affected by specific
        config changes are invalidated; unaffected entries are preserved.
        """
        if self.data["config_hash"] == current_config_hash:
            return  # No config change, nothing to invalidate

        prior = self.data.get("prior_config_snapshot", {})
        if not prior:
            # No prior snapshot -- cannot compute diff, full invalidation
            self.data["entries"] = {}
            self.data["config_hash"] = current_config_hash
            self.data["prior_config_snapshot"] = current_config
            return

        # Compute diff
        prior_variants = prior.get("canonical_to_variants", {})
        current_variants = current_config.get("canonical_to_variants", {})
        prior_exclusions = set(prior.get("exclusions", []))
        current_exclusions = set(current_config.get("exclusions", []))
        prior_parent_child = prior.get("parent_child", {})
        current_parent_child = current_config.get("parent_child", {})

        # 1. Changed canonicals: variant lists differ
        changed_canonicals = set()
        all_canonicals = set(prior_variants.keys()) | set(current_variants.keys())
        for canonical in all_canonicals:
            prior_v = set(prior_variants.get(canonical, []))
            current_v = set(current_variants.get(canonical, []))
            if prior_v != current_v:
                changed_canonicals.add(canonical)

        # 2. Added exclusions
        added_exclusions = current_exclusions - prior_exclusions

        # 3. Removed aliases (variants in prior but not in current)
        removed_aliases = set()
        for canonical, variants in prior_variants.items():
            current_v = set(current_variants.get(canonical, []))
            for v in variants:
                if v not in current_v:
                    removed_aliases.add(v)

        # 4. Changed parent-child
        changed_pc_names = set()
        all_parents = set(prior_parent_child.keys()) | set(current_parent_child.keys())
        for parent in all_parents:
            prior_children = set(prior_parent_child.get(parent, []))
            current_children = set(current_parent_child.get(parent, []))
            if prior_children != current_children:
                changed_pc_names.add(parent)
                changed_pc_names.update(prior_children | current_children)

        # Apply invalidation rules to each cache entry
        entries_to_remove = []
        for source_name, entry in self.data["entries"].items():
            canonical = entry.get("canonical", "")
            match_pass = entry.get("match_pass", 0)

            invalidate = False

            # Rule: canonical is in changed_canonicals
            if canonical in changed_canonicals:
                invalidate = True

            # Rule: source_name matches an added exclusion
            if source_name in added_exclusions:
                invalidate = True

            # Rule: source_name matches a removed alias
            if source_name in removed_aliases:
                invalidate = True

            # Rule: alias-matched entry whose alias was removed
            if match_pass == 2:  # alias_lookup
                # Check if the source_name was a variant that's been removed
                for can, variants in prior_variants.items():
                    if source_name in variants and source_name not in current_variants.get(can, []):
                        invalidate = True

            # Rule: parent-child matched entry affected by change
            if match_pass == 5:  # parent_child
                if source_name in changed_pc_names or canonical in changed_pc_names:
                    invalidate = True

            if invalidate:
                entries_to_remove.append(source_name)
                self._invalidated_entries.add(source_name)

        for name in entries_to_remove:
            del self.data["entries"][name]

        # Update config tracking
        self.data["config_hash"] = current_config_hash
        self.data["prior_config_snapshot"] = current_config

    def lookup(
        self,
        source_name: str,
        current_config_hash: str,
        target_names: dict[str, str],
    ) -> Optional[dict]:
        """Look up a name in the cache.

        Returns the cache entry dict if found and valid, None otherwise.
        Validates that the canonical name still exists in target_names.
        """
        if source_name in self._invalidated_entries:
            return None

        entry = self.data.get("entries", {}).get(source_name)
        if entry is None:
            return None

        # Validate: canonical must still exist in customers.csv
        from dd_agents.entity.preprocessing import preprocess_name
        canonical_preprocessed = preprocess_name(entry["canonical"])
        if canonical_preprocessed not in target_names:
            # Canonical no longer in customers.csv -- invalidate
            del self.data["entries"][source_name]
            return None

        return entry

    def add_entry(
        self,
        source_name: str,
        canonical: str,
        match_pass: int,
        match_type: str,
        confidence: float,
        run_id: str,
    ):
        """Add or update a cache entry after successful resolution."""
        existing = self.data["entries"].get(source_name)
        if existing:
            existing["last_confirmed_run"] = run_id
            existing["confirmation_count"] = existing.get("confirmation_count", 0) + 1
        else:
            self.data["entries"][source_name] = {
                "canonical": canonical,
                "match_pass": match_pass,
                "match_type": match_type,
                "confidence": confidence,
                "entity_type": "customer",
                "first_seen_run": run_id,
                "last_confirmed_run": run_id,
                "confirmation_count": 1,
            }

    def confirm_entry(self, source_name: str, run_id: str):
        """Confirm a cache hit (increment count, update run)."""
        entry = self.data["entries"].get(source_name)
        if entry:
            entry["last_confirmed_run"] = run_id
            entry["confirmation_count"] = entry.get("confirmation_count", 0) + 1

    def save(self, run_id: str):
        """Persist cache to disk."""
        self.data["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.data["last_updated_by"] = "forensic-dd"
        self.data["last_updated_run_id"] = run_id

        # Read-then-write with validation (for shared resource safety)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Verify write
        verification = json.loads(self.cache_path.read_text(encoding="utf-8"))
        if verification.get("last_updated_run_id") != run_id:
            raise RuntimeError(
                "Entity resolution cache write verification failed. "
                "Possible concurrent access."
            )
```

### 7.4 Cache Invalidation Rules (Summary)

| Condition | Action |
|-----------|--------|
| `entity_aliases` config hash unchanged | No invalidation |
| Config changed, prior snapshot available | Per-entry diff (see algorithm above) |
| Config changed, no prior snapshot | Full invalidation (delete all entries) |
| Canonical name no longer in customers.csv | Remove that entry on lookup |
| Name added to exclusions | Invalidate entry for that name |
| Alias removed from canonical's variant list | Invalidate entries matched via that alias |
| Parent-child mapping changed | Invalidate entries matched via parent_child |
| Cache file deleted or corrupted | Full rebuild from 6-pass matcher |

**Cache invalidation summary**: Cache entries are invalidated when (1) deal-config aliases change, (2) a canonical name is removed from customers.csv, or (3) a name is added to the exclusions list. All other cache entries persist across runs.

**Expected cache hit rate**: After 2-3 runs on the same data room with stable configuration, cache hit rate exceeds 90%. This reduces entity resolution from the primary bottleneck (many fuzzy comparisons) to near-instant for unchanged customer sets.

---

## 8. customer_safe_name Convention

The `customer_safe_name` is a deterministic, filesystem-safe identifier derived from the canonical customer name. It is used for all per-customer output filenames.

### Transformation Rules

1. Lowercase
2. Strip legal suffixes (Inc., Corp., LLC, Ltd., L.P., GmbH, S.A., Pty, ULC, etc.)
3. Replace spaces and special characters (`&`, `'`, `/`, `,`, `.`, `-`) with `_`
4. Collapse consecutive underscores
5. Strip leading/trailing underscores

### Examples

| Original Name | Safe Name |
|--------------|-----------|
| Global Analytics Group | `global_analytics_group` |
| Alpine Systems, Inc. | `alpine_systems` |
| GAG | `gag` |
| O'Brien Press | `o_brien_press` |
| Morgan & Mills | `morgan_mills` |
| Sierra Networks, Inc. | `sierra_networks` |
| Apex Digital Inc. | `apex_digital` |
| Metro Solutions, Inc. | `metro_solutions` |
| R&D Global | `r_d_global` |

### Usage Across the System

The safe name appears in:
- Agent output files: `{RUN_DIR}/findings/{agent}/{customer_safe_name}.json`
- Gap files: `{RUN_DIR}/findings/{agent}/gaps/{customer_safe_name}.json`
- Merged files: `{RUN_DIR}/findings/merged/{customer_safe_name}.json`
- Agent prompts: `Customer 1: Acme Corp (safe_name: acme_corp)`
- Clean-result IDs: `forensic-dd_legal_clean_{customer_safe_name}_0000`
- Incremental classification entries

The safe name is computed once during inventory building (step 6) and included in agent prompts. Agents MUST use the pre-computed safe names -- they do not derive them independently.

---

## 9. Integration With Pipeline

Entity resolution runs at pipeline step 7 and feeds into multiple downstream steps:

```
Step 6: Build inventory (customers.csv)
    |
Step 7: Entity resolution
    |   - Load cache from _dd/entity_resolution_cache.json
    |   - Compute config invalidation diff
    |   - Resolve all reference file names against customers.csv
    |   - Resolve database names against customers.csv (if source_of_truth exists)
    |   - Write entity_matches.json to FRESH tier
    |
Step 8: Reference registry (uses entity matches for customers_mentioned)
    |
Step 9: Customer-mention index (builds on entity matches)
    |
Steps 14-16: Agent prompts (include entity lookup tool, customer safe names)
    |
Step 34: Save cache (persist confirmed matches to PERMANENT tier)
```

```python
# src/dd_agents/orchestrator/steps/step_07_entity_resolution.py

async def step_07_entity_resolution(state: PipelineState) -> PipelineState:
    """Step 7: Entity resolution with cache-first strategy."""

    skill_dir = state.project_dir / state.skill_dir
    cache_path = state.project_dir / "_dd" / "entity_resolution_cache.json"

    # Load entity aliases from deal-config (with safe defaults)
    entity_aliases = state.deal_config.get("entity_aliases", {})

    resolver = EntityResolver(
        customers_csv=state.customers_csv,
        entity_aliases=entity_aliases,
        cache_path=cache_path,
        run_id=state.run_id,
    )

    # Compute cache invalidation if config changed
    config_hash = resolver.config_hash
    resolver.cache.compute_invalidation(entity_aliases, config_hash)

    # Collect all names requiring resolution
    names_to_resolve = set()

    # From reference files
    reference_files = _load_reference_files(state)
    for ref_file in reference_files:
        for name in ref_file.get("customers_mentioned", []):
            names_to_resolve.add(name)

    # From customer database (if exists)
    if "source_of_truth" in state.deal_config:
        db_names = _load_database_customer_names(state)
        for name in db_names:
            names_to_resolve.add(name)

    # Resolve all names
    results = resolver.resolve_all(list(names_to_resolve))

    # Write entity_matches.json (FRESH tier)
    match_log = resolver.get_match_log()
    matches_path = skill_dir / "inventory" / "entity_matches.json"
    matches_path.write_text(
        json.dumps(match_log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Store for downstream steps
    state.entity_matches = match_log
    state.entity_resolver = resolver  # Keep for cache save at step 34

    # Log summary
    log.info(
        f"Entity resolution complete: "
        f"{len(match_log['matches'])} matched, "
        f"{len(match_log['unmatched'])} unmatched, "
        f"{len(match_log['rejected'])} rejected"
    )

    return state
```

---

## 10. Dependencies

```
# pyproject.toml [project.dependencies]
rapidfuzz>=3.0.0            # Fuzzy string matching (Pass 3)
scikit-learn>=1.3.0         # TF-IDF vectorizer + cosine similarity (Pass 4)
```

---

## 11. File Layout

```
src/dd_agents/
  entity/
    __init__.py
    preprocessing.py         # preprocess_name(), to_customer_safe_name()
    passes.py                # pass_1 through pass_6, is_excluded()
    resolver.py              # EntityResolver class
    cache.py                 # EntityResolutionCache class
  models/
    entity.py                # EntityCacheEntry, EntityMatch, EntityMatchLog (from 04)
```

Entity resolution artifacts:
```
_dd/
  entity_resolution_cache.json                    # PERMANENT (shared across skills)
  forensic-dd/
    inventory/
      entity_matches.json                         # FRESH (rebuilt every run)
      customers.csv                               # FRESH (input to resolver)
    index/
      text/                                       # PERMANENT (extraction cache)
```
