"""Unit tests for the built-in prompt Markdown loader."""

from __future__ import annotations

import pytest

from dd_agents.agents import severity_thresholds as thr
from dd_agents.agents.prompts import loader


def test_resolve_thresholds_substitutes_known_placeholders() -> None:
    out = loader.resolve_thresholds("TfC over {TFC_REVENUE_PCT}% with {TFC_NOTICE_DAYS}d notice")
    assert out == f"TfC over {thr.TFC_REVENUE_PCT}% with {thr.TFC_NOTICE_DAYS}d notice"


def test_resolve_thresholds_leaves_json_braces_untouched() -> None:
    # The prompts are full of literal JSON braces — these must survive verbatim.
    text = 'Return {"severity": "P1", "nested": {"a": 1}} as JSON'
    assert loader.resolve_thresholds(text) == text


def test_resolve_thresholds_fails_closed_on_typo_placeholder() -> None:
    with pytest.raises(loader.PromptLoadError, match="unresolved severity-threshold placeholder"):
        loader.resolve_thresholds("bad {TFC_REVENU_PCT} typo")


def test_split_sections_parses_headings() -> None:
    body = "## Role\nrole text\n\n## Specialist Focus\nfocus text\n## Domain Guidance\nguide"
    sections = loader._split_sections(body)
    assert sections["Role"] == "role text"
    assert sections["Specialist Focus"] == "focus text"
    assert sections["Domain Guidance"] == "guide"


def test_split_front_matter_optional() -> None:
    meta, body = loader._split_front_matter("## Role\nhi")
    assert meta == {}
    assert "## Role" in body
    meta2, body2 = loader._split_front_matter("---\nid: x\n---\n## Role\nhi")
    assert meta2 == {"id": "x"}
    assert body2.strip().startswith("## Role")


def test_load_missing_specialist_fails_closed() -> None:
    loader.load_builtin_specialist.cache_clear()
    with pytest.raises(loader.PromptLoadError, match="not found"):
        loader.load_builtin_specialist("__no_such_agent__")


def test_unclosed_front_matter_fails_closed() -> None:
    with pytest.raises(loader.PromptLoadError, match="never closed"):
        loader._split_front_matter("---\nagent: legal\nno closing fence\n")


def test_non_mapping_front_matter_fails_closed() -> None:
    with pytest.raises(loader.PromptLoadError, match="must be a mapping"):
        loader._split_front_matter("---\n- a\n- b\n---\n## Role\nx")


def test_specialist_missing_heading_fails_closed(tmp_path, monkeypatch) -> None:
    spec = tmp_path / "specialists"
    spec.mkdir()
    (spec / "demo.md").write_text("---\nagent: demo\n---\n## Role\nr\n## Specialist Focus\nf\n", encoding="utf-8")
    monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
    loader.load_builtin_specialist.cache_clear()
    loader._read.cache_clear()
    with pytest.raises(loader.PromptLoadError, match="missing required heading"):
        loader.load_builtin_specialist("demo")
    loader.load_builtin_specialist.cache_clear()
    loader._read.cache_clear()


def test_specialist_empty_section_fails_closed(tmp_path, monkeypatch) -> None:
    spec = tmp_path / "specialists"
    spec.mkdir()
    # All headings present but Domain Guidance is whitespace-only.
    (spec / "demo.md").write_text(
        "---\nagent: demo\n---\n## Role\nr\n## Specialist Focus\nf\n## Domain Guidance\n   \n", encoding="utf-8"
    )
    monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
    loader.load_builtin_specialist.cache_clear()
    loader._read.cache_clear()
    with pytest.raises(loader.PromptLoadError, match="empty required section"):
        loader.load_builtin_specialist("demo")
    loader.load_builtin_specialist.cache_clear()
    loader._read.cache_clear()


def test_split_on_marker_fails_closed_when_marker_absent(monkeypatch) -> None:
    monkeypatch.setattr(loader, "load_named_prompt", lambda c, n: "head only, no marker")
    with pytest.raises(loader.PromptLoadError, match="exactly once"):
        loader.split_on_marker("synthesis", "red_flag_scanner", "<!-- CATEGORIES -->")


def test_split_on_marker_returns_head_tail() -> None:
    head, tail = loader.split_on_marker("synthesis", "red_flag_scanner", "<!-- CATEGORIES -->")
    assert "Red Flag Scanner" in head
    assert "CALIBRATION" in tail


def test_esg_domain_guidance_includes_regulatory_aliases() -> None:
    loader.load_builtin_specialist.cache_clear()
    dg = loader.load_builtin_specialist("esg").domain_guidance
    for kw in ("EU Taxonomy", "EUDR", "Scope 4", "avoided emissions", "just transition"):
        assert kw in dg
    # Pre-existing aliases must survive the edit.
    assert "double materiality" in dg
    assert "CSRD" in dg
