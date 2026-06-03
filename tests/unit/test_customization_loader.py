"""Tests for the customization loader (AD-1/AD-5/§6.2/§6.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dd_agents.customization.loader import (
    CustomizationError,
    PersonaLayer,
    ResolvedCustomization,
    _merge,
    load_dd_config,
    parse_persona_file,
    resolve_chain,
)
from dd_agents.models.config import AgentCustomization

PROFILES_DIR = Path(__file__).resolve().parents[2] / "src" / "dd_agents" / "customization" / "profiles"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


VALID_PERSONA = """---
agent: legal
status: active
model_profile: premium
---

## Persona (replaces default)

You are a forensic M&A lawyer focused on change-of-control risk.

## Additional Focus Areas

- assignment clauses
- anti-assignment provisions

## Additional Instructions

Pay close attention to consent requirements on any transfer.

## Severity Overrides

- change_of_control: P1
- assignment: P2
"""


def test_valid_front_matter_and_all_headings_parse(tmp_path: Path) -> None:
    path = _write(tmp_path / "legal.md", VALID_PERSONA)
    layer = parse_persona_file(path)
    assert isinstance(layer, PersonaLayer)
    assert layer.status == "active"
    assert layer.model_profile == "premium"
    assert layer.extends is None
    cust = layer.customization
    assert cust.persona == "You are a forensic M&A lawyer focused on change-of-control risk."
    assert cust.extra_focus_areas == ["assignment clauses", "anti-assignment provisions"]
    assert cust.extra_instructions == "Pay close attention to consent requirements on any transfer."
    assert cust.severity_overrides == {"change_of_control": "P1", "assignment": "P2"}


def test_unknown_heading_raises(tmp_path: Path) -> None:
    content = "---\nagent: legal\n---\n\n## Bogus Heading\n\nstuff\n"
    path = _write(tmp_path / "legal.md", content)
    with pytest.raises(CustomizationError):
        parse_persona_file(path)


def test_unknown_front_matter_key_raises(tmp_path: Path) -> None:
    content = "---\nagent: legal\nbogus_key: 1\n---\n\n## Additional Focus Areas\n\n- x\n"
    path = _write(tmp_path / "legal.md", content)
    with pytest.raises(CustomizationError):
        parse_persona_file(path)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    content = "---\nagent: [unterminated\n---\n\n## Additional Focus Areas\n\n- x\n"
    path = _write(tmp_path / "legal.md", content)
    with pytest.raises(CustomizationError):
        parse_persona_file(path)


def test_persona_absent_returns_none(tmp_path: Path) -> None:
    content = "---\nagent: legal\n---\n\n## Additional Focus Areas\n\n- x\n"
    path = _write(tmp_path / "legal.md", content)
    layer = parse_persona_file(path)
    assert layer.customization.persona is None


def test_content_hash_stable_and_changes_on_byte_change(tmp_path: Path) -> None:
    path = _write(tmp_path / "legal.md", VALID_PERSONA)
    h1 = parse_persona_file(path).content_hash
    h2 = parse_persona_file(path).content_hash
    assert h1 == h2
    _write(tmp_path / "legal.md", VALID_PERSONA + "\nextra byte\n")
    h3 = parse_persona_file(path).content_hash
    assert h3 != h1


def test_merge_rule_field_by_field() -> None:
    a = AgentCustomization(
        persona="A persona",
        extra_focus_areas=["x", "y"],
        extra_instructions="inst A",
        severity_overrides={"k1": "P0", "k2": "P1"},
    )
    b = AgentCustomization(
        persona="B persona",
        extra_focus_areas=["y", "z"],
        extra_instructions="inst B",
        severity_overrides={"k2": "P2", "k3": "P3"},
    )
    merged = _merge(a, b)
    # scalar: b wins if set
    assert merged.persona == "B persona"
    # list: a+b dedup preserving order
    assert merged.extra_focus_areas == ["x", "y", "z"]
    # map: {**a, **b}
    assert merged.severity_overrides == {"k1": "P0", "k2": "P2", "k3": "P3"}
    # extra_instructions concatenated a + "\n\n" + b
    assert merged.extra_instructions == "inst A\n\ninst B"


def test_merge_scalar_b_unset_keeps_a() -> None:
    a = AgentCustomization(persona="A persona")
    b = AgentCustomization()
    merged = _merge(a, b)
    assert merged.persona == "A persona"


def test_two_layer_extends_merge(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    base = """---
agent: legal
---

## Additional Focus Areas

- base_area

## Severity Overrides

- base_cat: P2
"""
    child = """---
agent: legal
extends: base
---

## Persona (replaces default)

Child persona.

## Additional Focus Areas

- child_area

## Severity Overrides

- base_cat: P1
- child_cat: P3
"""
    _write(profiles / "base.md", base)

    dd_config = tmp_path / "dd-config" / "agents"
    # The dd-config agent file declares `extends: base` and carries the child layer.
    _write(dd_config / "legal.md", child)

    resolved = resolve_chain(
        "legal",
        dd_config_dir=tmp_path / "dd-config",
        deal_cust=None,
        profiles_dir=profiles,
    )
    cust = resolved.customization
    # scalar wins (child sets persona)
    assert cust.persona == "Child persona."
    # list append dedup preserving order
    assert cust.extra_focus_areas == ["base_area", "child_area"]
    # map per-key: child overrides base_cat, adds child_cat
    assert cust.severity_overrides == {"base_cat": "P1", "child_cat": "P3"}
    assert len(resolved.layer_hashes) >= 2


def test_extends_cycle_raises(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    a = "---\nagent: legal\nextends: b\n---\n\n## Additional Focus Areas\n\n- a\n"
    b = "---\nagent: legal\nextends: a\n---\n\n## Additional Focus Areas\n\n- b\n"
    _write(profiles / "a.md", a)
    _write(profiles / "b.md", b)
    dd_config = tmp_path / "dd-config"
    _write(
        dd_config / "agents" / "legal.md",
        "---\nagent: legal\nextends: a\n---\n\n## Additional Focus Areas\n\n- top\n",
    )
    with pytest.raises(CustomizationError):
        resolve_chain("legal", dd_config_dir=dd_config, deal_cust=None, profiles_dir=profiles)


def test_no_dd_config_dir_returns_none(tmp_path: Path) -> None:
    assert load_dd_config(tmp_path) is None


def test_load_dd_config_resolves_all_agents(tmp_path: Path) -> None:
    dd_config = tmp_path / "dd-config"
    _write(
        dd_config / "agents" / "legal.md",
        "---\nagent: legal\n---\n\n## Additional Focus Areas\n\n- custom_legal\n",
    )
    resolved = load_dd_config(tmp_path)
    assert resolved is not None
    assert "legal" in resolved
    assert isinstance(resolved["legal"], ResolvedCustomization)
    assert "custom_legal" in resolved["legal"].customization.extra_focus_areas
    # An agent with no override file still resolves (empty customization).
    assert "finance" in resolved


def test_bundled_profiles_parse() -> None:
    for name in ("saas", "regulated-fintech", "asset-purchase", "carve-out"):
        layer = parse_persona_file(PROFILES_DIR / f"{name}.md")
        assert isinstance(layer, PersonaLayer)


def test_binary_persona_file_raises_clean_error(tmp_path: Path) -> None:
    """Regression: a non-UTF-8 file must fail-closed, not leak UnicodeDecodeError."""
    f = tmp_path / "legal.md"
    f.write_bytes(b"\x80\x81\xffbinary")
    with pytest.raises(CustomizationError):
        parse_persona_file(f)


def test_pathological_yaml_raises_clean_error(tmp_path: Path) -> None:
    """Regression: deeply-nested YAML must fail-closed, not leak RecursionError."""
    f = tmp_path / "legal.md"
    f.write_text("---\na: " + ("[" * 9000) + "\n---\n", encoding="utf-8")
    with pytest.raises(CustomizationError):
        parse_persona_file(f)


def test_resolve_chain_fails_closed_on_agent_filename_mismatch(tmp_path: Path) -> None:
    """Regression (Copilot #202 C4): a file whose front-matter agent: != filename
    must be rejected, matching the validator — never silently applied."""
    agents = tmp_path / "agents"
    agents.mkdir(parents=True)
    (agents / "legal.md").write_text("---\nagent: finance\n---\n## Persona (replaces default)\nx\n", encoding="utf-8")
    with pytest.raises(CustomizationError):
        resolve_chain("legal", tmp_path, None, PROFILES_DIR)


def test_resolve_chain_allows_wildcard_and_matching_agent(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir(parents=True)
    # matching stem is fine
    (agents / "legal.md").write_text(
        "---\nagent: legal\n---\n## Severity Overrides\n- change_of_control: P1\n", encoding="utf-8"
    )
    r = resolve_chain("legal", tmp_path, None, PROFILES_DIR)
    assert r.customization.severity_overrides == {"change_of_control": "P1"}
