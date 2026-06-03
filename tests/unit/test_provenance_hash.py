"""Wave 2 — run provenance hashing (audit §8.1).

Proves the single canonical config hash is deterministic and key-order
independent, persona normalization is OS-agnostic, and any drift in config,
prompt version, or persona text changes the combined provenance hash.
"""

from __future__ import annotations

from dd_agents.persistence.provenance import (
    compute_config_hash,
    compute_persona_hashes,
    compute_provenance_hash,
)


def test_config_hash_deterministic_and_key_order_independent() -> None:
    a = compute_config_hash({"b": 2, "a": 1, "nested": {"y": 1, "x": 2}})
    b = compute_config_hash({"a": 1, "nested": {"x": 2, "y": 1}, "b": 2})
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_config_hash_empty_for_none() -> None:
    assert compute_config_hash(None) == ""


def test_config_hash_changes_on_content_change() -> None:
    base = compute_config_hash({"a": 1})
    changed = compute_config_hash({"a": 2})
    assert base != changed


def test_persona_hash_normalizes_line_endings() -> None:
    crlf = compute_persona_hashes({"legal": "line one\r\nline two\r\n"})
    lf = compute_persona_hashes({"legal": "line one\nline two\n"})
    assert crlf == lf


def test_persona_hash_normalizes_trailing_whitespace() -> None:
    trailing = compute_persona_hashes({"legal": "line one   \nline two\t\n"})
    clean = compute_persona_hashes({"legal": "line one\nline two\n"})
    assert trailing == clean


def test_persona_hash_sensitive_to_real_content() -> None:
    a = compute_persona_hashes({"legal": "You are the legal specialist."})
    b = compute_persona_hashes({"legal": "You are the finance specialist."})
    assert a != b


def test_provenance_hash_changes_when_any_input_changes() -> None:
    cfg = "cfg1"
    personas = {"legal": "abc", "_SAFETY_FLOOR": "floor"}
    base = compute_provenance_hash(cfg, "2.0.0", personas)

    # config change
    assert compute_provenance_hash("cfg2", "2.0.0", personas) != base
    # prompt version change
    assert compute_provenance_hash(cfg, "2.1.0", personas) != base
    # persona change (one agent)
    assert compute_provenance_hash(cfg, "2.0.0", {**personas, "legal": "xyz"}) != base
    # safety-floor change busts the hash
    assert compute_provenance_hash(cfg, "2.0.0", {**personas, "_SAFETY_FLOOR": "weaker"}) != base


def test_provenance_hash_stable_for_identical_inputs() -> None:
    personas = {"legal": "abc", "finance": "def"}
    assert compute_provenance_hash("c", "v", personas) == compute_provenance_hash("c", "v", dict(personas))


def test_collect_persona_texts_includes_per_agent_safety_floor() -> None:
    from dd_agents.agents.registry import AgentRegistry

    texts = AgentRegistry.collect_persona_texts(["legal", "finance"])
    assert "legal" in texts
    # Per-agent safety-floor entries embed each agent's citation mandate, so
    # per-agent citation-example drift busts that agent's provenance hash.
    assert "_SAFETY_FLOOR::legal" in texts
    assert "_SAFETY_FLOOR::finance" in texts
    assert "MANDATORY Citation Requirements" in texts["_SAFETY_FLOOR::legal"]
    # The legal and finance citation examples differ, so the floors differ.
    assert texts["_SAFETY_FLOOR::legal"] != texts["_SAFETY_FLOOR::finance"]


def test_dd_config_override_busts_provenance(tmp_path) -> None:
    """Regression (Copilot #202 C5): editing dd-config/ persona overrides must
    change the provenance hash so a stale checkpoint can't resume against
    drifted prompts."""
    from dd_agents.agents.registry import AgentRegistry

    dd = tmp_path / "dd-config" / "agents"
    dd.mkdir(parents=True)
    legal = dd / "legal.md"

    def prov() -> str:
        texts = AgentRegistry.collect_persona_texts(["legal"], project_dir=tmp_path)
        return compute_provenance_hash("cfg", "2.0.0", compute_persona_hashes(texts))

    base = prov()
    legal.write_text("---\nagent: legal\n---\n## Persona (replaces default)\nFocus A.\n", encoding="utf-8")
    added = prov()
    legal.write_text("---\nagent: legal\n---\n## Persona (replaces default)\nFocus B.\n", encoding="utf-8")
    edited = prov()
    assert base != added, "adding a dd-config override must bust provenance"
    assert added != edited, "editing a dd-config override must bust provenance"
