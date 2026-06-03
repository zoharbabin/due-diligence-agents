"""Single deterministic authority for a finding's final severity (audit AD-3).

Before this module, severity was decided in up to four uncoordinated places
(LLM assignment, prompt-time override hints, post-merge recalibration, and a
recorded-but-never-applied executive-synthesis override). The result was
unpredictable: a user who set ``change_of_control: P1`` got only a prompt hint
the model might ignore, which a downgrade rule could then override anyway.

``resolve_severity`` collapses that into ONE ordered, pure, deterministic pass
run once in the merge write path (``reporting/merge.py``):

    llm  →  recalibration (down-only)  →  user_override (bounded, AD-3a)

Each stage that changes severity records a ``severity_source`` and appends a
``severity_chain`` entry, so every final value is auditable. The module is pure
(no I/O, no LLM) and therefore safe under concurrent agent merges.

The deterministic recalibration *rules* live here (relocated from
``computed_metrics``) so there is exactly one home; ``computed_metrics`` imports
them back for its read-path guard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dd_agents.utils.constants import (
    SEVERITY_ORDER,
    SEVERITY_P1,
    SEVERITY_P3,
)

# --- severity_source provenance tags ---
SRC_LLM = "llm"
SRC_CITATION = "citation_downgrade"
SRC_RECALIBRATION = "recalibration"
SRC_USER_OVERRIDE = "user_override"

#: Categories/markers that a user override may NEVER suppress (AD-3a). Tamper
#: and injection findings are surfaced regardless of any downgrade request.
_PROTECTED_PATTERNS: tuple[str, ...] = (
    "tamper",
    "injection",
    "prompt_injection",
    "doc_tamper",
    "document_integrity",
)

# ---------------------------------------------------------------------------
# Deterministic recalibration rules (single home; relocated from computed_metrics)
# ---------------------------------------------------------------------------

_RECALIBRATION_RULES: list[dict[str, object]] = [
    {
        "name": "competitor_only_coc",
        "max_severity": "P3",
        "title_patterns": ["competitor"],
        "text_patterns": ["change of control", "change-of-control", " coc ", "coc ", "coc_"],
        "require_all": True,
        "reason": "Competitor-only CoC: buyer rarely competes with target's customers",
    },
    {
        "name": "auditor_independence",
        "max_severity": "P2",
        "text_patterns": ["auditor independence", "professional independence", "independence requirements"],
        "require_all": False,
        "reason": "Standard auditor/professional independence clause",
    },
    {
        "name": "transaction_fee",
        "max_severity": "P1",
        "text_patterns": ["transaction fee", "management fee", "advisory fee"],
        "require_all": False,
        "reason": "Transaction/advisory fee: known cost, not structural deal-blocker",
    },
    {
        "name": "tfc_cap",
        "max_severity": "P2",
        "text_patterns": ["termination for convenience", "terminate without cause"],
        "category_patterns": ["tfc", "convenience_termination"],
        "require_all": False,
        "reason": "TfC: valuation concern, not deal-blocking",
    },
    {
        "name": "speculative_language",
        "max_severity": "P2",
        "text_patterns": ["may contain", "must be verified", "appears to", "potentially", "cannot confirm"],
        "require_all": False,
        "reason": "Speculative/unconfirmed: cap severity until verified",
    },
]


def recalibration_cap(title: str, description: str, category: str) -> tuple[str | None, str]:
    """Return ``(max_severity_cap, reason)`` for known false-positive patterns.

    Pure matcher over title/description/category. When several rules match, the
    mildest cap (highest P-number) wins. Returns ``(None, "")`` if nothing
    matches. This is the single shared core used by both the merge-time resolver
    and the ``computed_metrics`` read-path guard.
    """
    title_lower = title.lower()
    text_combined = f"{title_lower} {description.lower()}"
    cat_lower = category.lower()

    best_cap: str | None = None
    best_reason = ""

    for rule in _RECALIBRATION_RULES:
        max_sev = str(rule.get("max_severity", SEVERITY_P3))
        require_all = bool(rule.get("require_all", False))
        group_results: list[bool] = []

        title_pats = rule.get("title_patterns")
        if isinstance(title_pats, list) and title_pats:
            group_results.append(any(str(p).lower() in title_lower for p in title_pats))

        text_pats = rule.get("text_patterns")
        if isinstance(text_pats, list) and text_pats:
            group_results.append(any(str(p).lower() in text_combined for p in text_pats))

        cat_pats = rule.get("category_patterns")
        if isinstance(cat_pats, list) and cat_pats:
            group_results.append(any(str(p).lower() in cat_lower for p in cat_pats))

        if not group_results:
            continue
        matched = all(group_results) if require_all else any(group_results)
        if not matched:
            continue

        if best_cap is None or SEVERITY_ORDER.get(max_sev, 3) > SEVERITY_ORDER.get(best_cap, 3):
            best_cap = max_sev
            best_reason = str(rule.get("reason", ""))

    return best_cap, best_reason


def _rank(sev: str) -> int:
    """Severity rank (0 = most severe). Unknown values sort as least severe."""
    return SEVERITY_ORDER.get(sev, 3)


def _is_protected(category: str, metadata: dict[str, object] | None) -> bool:
    """True if this finding is tamper/injection and immune to user downgrade."""
    cat = category.lower()
    if any(p in cat for p in _PROTECTED_PATTERNS):
        return True
    if metadata:
        marker = f"{metadata.get('severity_source', '')} {metadata.get('integrity_flag', '')}".lower()
        if any(p in marker for p in _PROTECTED_PATTERNS):
            return True
    return False


@dataclass(frozen=True)
class SeverityResolution:
    """Outcome of :func:`resolve_severity` — final severity plus audit trail."""

    severity: str
    source: str
    reason: str
    chain: list[dict[str, str]] = field(default_factory=list)


def resolve_severity(
    *,
    llm_severity: str,
    post_citation_severity: str,
    title: str,
    description: str,
    category: str,
    metadata: dict[str, object] | None = None,
    user_overrides: dict[str, str] | None = None,
    allow_user_downgrade_of_dealbreakers: bool = False,
) -> SeverityResolution:
    """Resolve a finding's final severity deterministically (AD-3).

    Order (later stages have higher authority): seed from the post-citation
    severity → deterministic recalibration (down-only) → user override
    (escalation always allowed; downgrade of a P0 only when explicitly enabled,
    and never below P1; never applied to protected tamper findings, AD-3a).

    Idempotent: re-running on an already-resolved finding yields the same value.
    """
    chain: list[dict[str, str]] = []
    severity = post_citation_severity
    source = SRC_CITATION if post_citation_severity != llm_severity else SRC_LLM
    reason = "citation downgrade" if source == SRC_CITATION else ""
    chain.append({"stage": source, "severity": severity, "reason": reason})

    # Stage: deterministic recalibration (down-only).
    cap, cap_reason = recalibration_cap(title, description, category)
    if cap is not None and _rank(cap) > _rank(severity):
        severity = cap
        source = SRC_RECALIBRATION
        reason = cap_reason
        chain.append({"stage": SRC_RECALIBRATION, "severity": severity, "reason": cap_reason})

    # Stage: user override (bounded).
    override = (user_overrides or {}).get(category)
    if override and override in SEVERITY_ORDER and override != severity:
        protected = _is_protected(category, metadata)
        is_downgrade = _rank(override) > _rank(severity)
        # "Dealbreaker" for downgrade-protection means the finding is at or above
        # the P1 floor (P0 or P1). Keying on the P1 floor — rather than only P0 —
        # makes resolution IDEMPOTENT: once a P0 override is clamped to P1, a
        # re-resolution sees P1 and still refuses to drop it below the floor,
        # instead of letting the same override slip through to P3 on the 2nd pass.
        is_dealbreaker = _rank(severity) <= _rank(SEVERITY_P1)
        below_floor = _rank(override) > _rank(SEVERITY_P1)

        if protected and is_downgrade:
            chain.append(
                {"stage": SRC_USER_OVERRIDE, "severity": severity, "reason": f"blocked: {category} is tamper-protected"}
            )
        elif is_downgrade and is_dealbreaker and below_floor and not allow_user_downgrade_of_dealbreakers:
            chain.append(
                {"stage": SRC_USER_OVERRIDE, "severity": severity, "reason": "blocked: dealbreaker downgrade disabled"}
            )
        else:
            target = override
            # Even when downgrade is allowed, never drop a dealbreaker below P1.
            if is_downgrade and is_dealbreaker and below_floor:
                target = SEVERITY_P1
                reason = f"user override (clamped to {SEVERITY_P1}: dealbreaker floor)"
            else:
                reason = "user override"
            # No-op if the bound left severity unchanged (idempotent: a re-resolve
            # of an already-clamped finding records nothing and changes nothing).
            if target != severity:
                severity = target
                source = SRC_USER_OVERRIDE
                chain.append({"stage": SRC_USER_OVERRIDE, "severity": severity, "reason": reason})

    return SeverityResolution(severity=severity, source=source, reason=reason, chain=chain)
