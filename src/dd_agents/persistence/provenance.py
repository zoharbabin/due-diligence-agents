"""Single source of truth for run provenance hashing (audit §8.1).

Why this module exists: the config hash was computed two different ways —
``orchestrator/engine.py`` hashed raw file *bytes*, while
``persistence/run_manager.py`` hashed *sorted-json*. The two never agreed, so
they could not be cross-checked. Worse, neither covered the agent *personas*,
so a checkpoint could be resumed against changed prompts and silently produce
non-reproducible findings.

This module gives ONE canonical hash for config, one normalized hash for
persona text, and one combined provenance hash. All hashing for provenance and
the fail-closed resume gate routes through here, so a fresh run and a resume of
the same inputs always agree.

All functions are pure and deterministic (no I/O, no env, no clock) — safe under
concurrent runs and identical across local/cloud (parity).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def compute_config_hash(deal_config: dict[str, Any] | None) -> str:
    """Canonical SHA-256 of a parsed deal-config dict.

    Uses sorted keys and compact separators so logically-identical configs hash
    identically regardless of key order or incidental whitespace. Returns ``""``
    for ``None`` (no config). This is the SINGLE config-hash function — both the
    fresh-run path and the resume-recompute path must call it on the parsed dict
    (never on raw file bytes), or every resume would spuriously fail.
    """
    if deal_config is None:
        return ""
    canonical = json.dumps(deal_config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_persona_text(text: str) -> str:
    """Normalize persona text so hashes are stable across OS/editor differences.

    Collapses CRLF/CR to LF, right-strips each line, and ensures a single
    trailing newline. This makes the hash depend on meaningful content, not on
    line-ending or trailing-whitespace noise (local/cloud parity).
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    return "\n".join(lines).strip() + "\n"


def compute_persona_hashes(personas: dict[str, str]) -> dict[str, str]:
    """Map each agent name → content-normalized SHA-256 of its persona text."""
    return {
        name: hashlib.sha256(_normalize_persona_text(text).encode("utf-8")).hexdigest()
        for name, text in sorted(personas.items())
    }


def compute_provenance_hash(
    config_hash: str,
    prompt_version: str,
    persona_hashes: dict[str, str],
    routing_fingerprint: str = "",
) -> str:
    """Combine config + prompt-version + persona hashes into one provenance hash.

    This is the value the fail-closed resume gate compares: if the config, the
    prompt builder version, any agent persona, or the LLM routing
    (provider/gateway/clamp — ``routing_fingerprint``) changed since the
    checkpoint, the combined hash changes and the stale checkpoint is rejected.
    So a run cannot silently resume under a different provider/model and stitch
    findings from two backends into one report.

    ``routing_fingerprint`` defaults to ``""`` so the function stays pure (the
    caller derives the secret-free fingerprint from the environment and passes
    it in); an empty value preserves the legacy three-input hash.
    """
    payload = {
        "config_hash": config_hash,
        "prompt_version": prompt_version,
        "persona_hashes": dict(sorted(persona_hashes.items())),
        "routing_fingerprint": routing_fingerprint,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
