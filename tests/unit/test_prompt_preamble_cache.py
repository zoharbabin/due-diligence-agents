"""Tests for the build-time preamble cache (audit §4.1a).

Two calls with the same agent/config but different subject lists must produce
prompts that differ only in the subject-list section — i.e. the cached static
preamble (role + deal context) is byte-identical, and the cache is a pure
optimization that never alters output.
"""

from __future__ import annotations

from pathlib import Path

from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.models.config import BuyerInfo, DealConfig, DealInfo, TargetInfo
from dd_agents.models.enums import DealType


def _deal_config(buyer: str = "Buyer Co", target: str = "Target Co") -> DealConfig:
    return DealConfig(
        config_version="1.0.0",
        buyer=BuyerInfo(name=buyer),
        target=TargetInfo(name=target),
        deal=DealInfo(type=DealType.ACQUISITION, focus_areas=["legal", "finance"]),
    )


def _builder() -> PromptBuilder:
    return PromptBuilder(
        project_dir=Path("/tmp/project"),
        run_dir=Path("/tmp/run"),
        run_id="run_xyz",
    )


def test_role_section_cached_byte_identical() -> None:
    b = _builder()
    cfg = _deal_config()
    p1 = b.build_specialist_prompt("legal", ["subject_a"], deal_config=cfg)
    p2 = b.build_specialist_prompt("legal", ["subject_b", "subject_c"], deal_config=cfg)

    role_header = "# LEGAL SPECIALIST AGENT"
    assert role_header in p1
    assert role_header in p2

    # The deal-context block (static preamble) is byte-identical across calls.
    role1 = p1[p1.index(role_header) : p1.index("\n\n---\n\n", p1.index(role_header))]
    role2 = p2[p2.index(role_header) : p2.index("\n\n---\n\n", p2.index(role_header))]
    assert role1 == role2
    assert "Buyer: Buyer Co" in role1

    # Cache populated with exactly one entry for this agent+config.
    assert len(b._role_section_cache) == 1


def test_cache_byte_identical_to_uncached() -> None:
    cold = _builder()
    warm = _builder()
    cfg = _deal_config()
    _ = warm.build_specialist_prompt("legal", ["x"], deal_config=cfg)

    cold_role = cold._build_role_section("legal", cold._coerce_deal_config(cfg))
    warm_role = warm._cached_role_section("legal", warm._coerce_deal_config(cfg))
    assert cold_role == warm_role


def test_distinct_configs_do_not_collide() -> None:
    b = _builder()
    p1 = b.build_specialist_prompt("legal", ["s"], deal_config=_deal_config())
    p2 = b.build_specialist_prompt("legal", ["s"], deal_config=_deal_config(buyer="Other Buyer", target="Other Target"))
    assert "Buyer: Buyer Co" in p1
    assert "Buyer: Other Buyer" in p2
    assert len(b._role_section_cache) == 2
