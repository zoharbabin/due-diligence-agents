"""Wave 0 — the single deterministic severity authority (audit AD-3 / §1.2b).

Proves the ordered resolution (llm → recalibration → user_override), the AD-3a
safety bound, tamper-immunity, and idempotency.
"""

from __future__ import annotations

from dd_agents.reporting.severity_resolver import (
    SRC_CITATION,
    SRC_LLM,
    SRC_RECALIBRATION,
    SRC_USER_OVERRIDE,
    recalibration_cap,
    resolve_severity,
)


def _resolve(**kw):
    base = dict(
        llm_severity="P1",
        post_citation_severity="P1",
        title="t",
        description="d",
        category="change_of_control",
        metadata={},
        user_overrides={},
        allow_user_downgrade_of_dealbreakers=False,
    )
    base.update(kw)
    return resolve_severity(**base)


def test_passthrough_when_nothing_applies() -> None:
    r = _resolve(category="generic", title="x", description="y")
    assert r.severity == "P1"
    assert r.source == SRC_LLM
    assert len(r.chain) == 1


def test_citation_downgrade_recorded() -> None:
    r = _resolve(llm_severity="P1", post_citation_severity="P2", category="generic")
    assert r.severity == "P2"
    assert r.source == SRC_CITATION


def test_recalibration_is_down_only() -> None:
    # competitor-only CoC caps at P3
    r = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        title="Competitor CoC clause",
        description="change of control restriction applies only to competitors",
        category="change_of_control",
    )
    assert r.severity == "P3"
    assert r.source == SRC_RECALIBRATION
    # chain records both the seed and the recalibration step, in order
    stages = [c["stage"] for c in r.chain]
    assert stages == [SRC_LLM, SRC_RECALIBRATION]


def test_user_override_escalation_always_allowed() -> None:
    r = _resolve(post_citation_severity="P3", llm_severity="P3", user_overrides={"change_of_control": "P1"})
    assert r.severity == "P1"
    assert r.source == SRC_USER_OVERRIDE


def test_user_downgrade_of_dealbreaker_blocked_by_default() -> None:
    r = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        category="generic",
        title="x",
        description="y",
        user_overrides={"generic": "P3"},
    )
    assert r.severity == "P0"  # unchanged
    assert any("blocked" in c["reason"] for c in r.chain)


def test_user_downgrade_of_dealbreaker_clamped_to_p1_when_enabled() -> None:
    r = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        category="generic",
        title="x",
        description="y",
        user_overrides={"generic": "P3"},
        allow_user_downgrade_of_dealbreakers=True,
    )
    assert r.severity == "P1"  # clamped, never below P1
    assert r.source == SRC_USER_OVERRIDE


def test_tamper_finding_is_immune_to_user_downgrade() -> None:
    r = _resolve(
        llm_severity="P1",
        post_citation_severity="P1",
        category="document_integrity",
        title="Injected instructions detected",
        description="document contained 'ignore previous instructions'",
        user_overrides={"document_integrity": "P3"},
        allow_user_downgrade_of_dealbreakers=True,
    )
    assert r.severity == "P1"  # protected — override refused
    assert any("tamper-protected" in c["reason"] for c in r.chain)


def test_idempotent_round_trip() -> None:
    first = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        title="Competitor CoC",
        description="change of control only for competitors",
        category="change_of_control",
    )
    second = resolve_severity(
        llm_severity=first.severity,
        post_citation_severity=first.severity,
        title="Competitor CoC",
        description="change of control only for competitors",
        category="change_of_control",
        metadata={},
        user_overrides={},
    )
    assert first.severity == second.severity == "P3"


def test_recalibration_cap_matches_known_patterns() -> None:
    cap, reason = recalibration_cap("Competitor clause", "change of control for competitors only", "legal")
    assert cap == "P3"
    assert reason
    cap2, _ = recalibration_cap("Generic finding", "nothing special", "legal")
    assert cap2 is None


def test_idempotent_on_dealbreaker_clamp_path() -> None:
    """Regression: clamping a P0 user-downgrade to P1 must be idempotent.

    Previously a re-resolution saw P1 (not P0), so was_dealbreaker went False
    and the same P3 override slipped through to P3 on the 2nd pass.
    """
    first = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        category="generic",
        title="t",
        description="d",
        user_overrides={"generic": "P3"},
        allow_user_downgrade_of_dealbreakers=True,
    )
    assert first.severity == "P1"
    second = _resolve(
        llm_severity=first.severity,
        post_citation_severity=first.severity,
        category="generic",
        title="t",
        description="d",
        user_overrides={"generic": "P3"},
        allow_user_downgrade_of_dealbreakers=True,
    )
    assert second.severity == "P1"  # stable, not P3


def test_dealbreaker_block_is_idempotent() -> None:
    first = _resolve(
        llm_severity="P0",
        post_citation_severity="P0",
        category="generic",
        title="t",
        description="d",
        user_overrides={"generic": "P3"},
        allow_user_downgrade_of_dealbreakers=False,
    )
    assert first.severity == "P0"
    second = _resolve(
        llm_severity=first.severity,
        post_citation_severity=first.severity,
        category="generic",
        title="t",
        description="d",
        user_overrides={"generic": "P3"},
        allow_user_downgrade_of_dealbreakers=False,
    )
    assert second.severity == "P0"
