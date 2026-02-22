"""PERMANENT-tier cache for entity resolution matches.

Persists confirmed entity matches across pipeline runs so that subsequent
runs skip the 6-pass matcher for already-resolved names.  Implements
per-entry invalidation when ``entity_aliases`` config changes rather than
a full cache wipe.

Cache file: ``_dd/entity_resolution_cache.json``
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dd_agents.utils.naming import preprocess_name

if TYPE_CHECKING:
    from pathlib import Path


class EntityResolutionCache:
    """PERMANENT-tier cache for entity resolution matches.

    Parameters
    ----------
    cache_path:
        Path to ``entity_resolution_cache.json``.
    """

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.data: dict[str, Any] = self._load()
        self._invalidated_entries: set[str] = set()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self.cache_path.exists():
            try:
                result: dict[str, Any] = json.loads(self.cache_path.read_text(encoding="utf-8"))
                return result
            except (json.JSONDecodeError, OSError):
                # Corrupted cache -- start fresh
                return self._empty_cache()
        return self._empty_cache()

    @staticmethod
    def _empty_cache() -> dict[str, Any]:
        return {
            "version": 1,
            "last_updated": datetime.now(UTC).isoformat(),
            "last_updated_by": "forensic-dd",
            "last_updated_run_id": "",
            "config_hash": "",
            "prior_config_snapshot": {},
            "entries": {},
            "unmatched": [],
        }

    # ------------------------------------------------------------------
    # Per-entry invalidation
    # ------------------------------------------------------------------

    def compute_invalidation(
        self,
        current_config: dict[str, Any],
        current_config_hash: str,
    ) -> None:
        """Compute which cache entries need re-resolution due to config changes.

        Implements the per-entry invalidation algorithm from the
        entity-resolution spec (section 7.3).  Only entries affected by
        specific config changes are invalidated; unaffected entries are
        preserved.
        """
        if self.data["config_hash"] == current_config_hash:
            return  # No config change, nothing to invalidate

        prior: dict[str, Any] = self.data.get("prior_config_snapshot", {})
        if not prior:
            # No prior snapshot -- cannot compute diff, full invalidation
            self.data["entries"] = {}
            self.data["config_hash"] = current_config_hash
            self.data["prior_config_snapshot"] = current_config
            return

        # ----- Compute diff -----

        prior_variants: dict[str, list[str]] = prior.get("canonical_to_variants", {})
        current_variants: dict[str, list[str]] = current_config.get("canonical_to_variants", {})
        prior_exclusions = set(prior.get("exclusions", []))
        current_exclusions = set(current_config.get("exclusions", []))
        prior_parent_child: dict[str, list[str]] = prior.get("parent_child", {})
        current_parent_child: dict[str, list[str]] = current_config.get("parent_child", {})

        # 1. Changed canonicals: variant lists differ
        changed_canonicals: set[str] = set()
        all_canonicals = set(prior_variants.keys()) | set(current_variants.keys())
        for canonical in all_canonicals:
            prior_v = set(prior_variants.get(canonical, []))
            current_v = set(current_variants.get(canonical, []))
            if prior_v != current_v:
                changed_canonicals.add(canonical)

        # 2. Added exclusions
        added_exclusions = current_exclusions - prior_exclusions

        # 3. Removed aliases (variants in prior but not in current)
        removed_aliases: set[str] = set()
        for canonical, variants in prior_variants.items():
            current_v = set(current_variants.get(canonical, []))
            for v in variants:
                if v not in current_v:
                    removed_aliases.add(v)

        # 4. Changed parent-child
        changed_pc_names: set[str] = set()
        all_parents = set(prior_parent_child.keys()) | set(current_parent_child.keys())
        for parent in all_parents:
            prior_children = set(prior_parent_child.get(parent, []))
            current_children = set(current_parent_child.get(parent, []))
            if prior_children != current_children:
                changed_pc_names.add(parent)
                changed_pc_names.update(prior_children | current_children)

        # ----- Apply invalidation rules to each cache entry -----

        entries_to_remove: list[str] = []
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
                for can, variants in prior_variants.items():
                    if source_name in variants and source_name not in current_variants.get(can, []):
                        invalidate = True

            # Rule: parent-child matched entry affected by change
            if match_pass == 5 and (source_name in changed_pc_names or canonical in changed_pc_names):
                invalidate = True

            if invalidate:
                entries_to_remove.append(source_name)
                self._invalidated_entries.add(source_name)

        for name in entries_to_remove:
            del self.data["entries"][name]

        # Update config tracking
        self.data["config_hash"] = current_config_hash
        self.data["prior_config_snapshot"] = current_config

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(
        self,
        source_name: str,
        current_config_hash: str,
        target_names: dict[str, str],
    ) -> dict[str, Any] | None:
        """Look up a name in the cache.

        Returns the cache entry dict if found and valid, ``None`` otherwise.
        Validates that the canonical name still exists in *target_names*.
        """
        if source_name in self._invalidated_entries:
            return None

        entry = self.data.get("entries", {}).get(source_name)
        if entry is None:
            return None

        # Validate: canonical must still exist in customers.csv
        canonical_preprocessed = preprocess_name(entry["canonical"])
        if canonical_preprocessed not in target_names:
            # Canonical no longer in customers.csv -- invalidate
            del self.data["entries"][source_name]
            return None

        result: dict[str, Any] = entry
        return result

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_entry(
        self,
        source_name: str,
        canonical: str,
        match_pass: int,
        match_type: str,
        confidence: float,
        run_id: str,
    ) -> None:
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

    def confirm_entry(self, source_name: str, run_id: str) -> None:
        """Confirm a cache hit (increment count, update run)."""
        entry = self.data["entries"].get(source_name)
        if entry:
            entry["last_confirmed_run"] = run_id
            entry["confirmation_count"] = entry.get("confirmation_count", 0) + 1

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, run_id: str) -> None:
        """Persist cache to disk."""
        self.data["last_updated"] = datetime.now(UTC).isoformat()
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
            raise RuntimeError("Entity resolution cache write verification failed. Possible concurrent access.")
