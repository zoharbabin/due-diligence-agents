"""Wave 2 — provenance fields survive checkpoint round-trip + drift is detectable.

The full fail-closed resume path is exercised by the pipeline integration
suite; these tests pin the state-serialization back-compat and the drift
comparison the gate relies on (audit §8.1), without a full pipeline run.
"""

from __future__ import annotations

from dd_agents.orchestrator.state import PipelineState
from dd_agents.persistence.provenance import (
    compute_persona_hashes,
    compute_provenance_hash,
)


def test_provenance_fields_round_trip_through_checkpoint() -> None:
    state = PipelineState(run_id="r1")
    state.config_hash = "cfg"
    state.prompt_version = "2.0.0"
    state.persona_hashes = {"legal": "abc"}
    state.provenance_hash = compute_provenance_hash("cfg", "2.0.0", {"legal": "abc"})

    restored = PipelineState.from_checkpoint_dict(state.to_checkpoint_dict())
    assert restored.provenance_hash == state.provenance_hash
    assert restored.prompt_version == "2.0.0"
    assert restored.persona_hashes == {"legal": "abc"}


def test_legacy_checkpoint_without_provenance_loads_clean() -> None:
    """Old checkpoints (no provenance keys) deserialize with safe defaults."""
    legacy = PipelineState(run_id="old").to_checkpoint_dict()
    legacy.pop("provenance_hash", None)
    legacy.pop("prompt_version", None)
    legacy.pop("persona_hashes", None)

    restored = PipelineState.from_checkpoint_dict(legacy)
    assert restored.provenance_hash == ""  # → gate treats as legacy, warns, resumes
    assert restored.prompt_version == "unknown"
    assert restored.persona_hashes == {}


def test_drift_is_detectable_via_hash_mismatch() -> None:
    """The gate's core comparison: changed personas → different provenance hash."""
    checkpoint_hash = compute_provenance_hash("cfg", "2.0.0", compute_persona_hashes({"legal": "original persona"}))
    current_hash = compute_provenance_hash("cfg", "2.0.0", compute_persona_hashes({"legal": "EDITED persona"}))
    assert checkpoint_hash != current_hash  # gate would raise BlockingGateError


def test_matching_provenance_passes_gate_comparison() -> None:
    personas = compute_persona_hashes({"legal": "p"})
    a = compute_provenance_hash("cfg", "2.0.0", personas)
    b = compute_provenance_hash("cfg", "2.0.0", personas)
    assert a == b  # control case: identical inputs resume clean
