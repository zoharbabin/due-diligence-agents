"""Single source of truth for numeric severity-calibration thresholds.

Every prompt string that states a severity threshold (TfC revenue %, notice
period, ARR-mismatch tiers, change-of-control revenue exposure) MUST be built
from these constants via f-strings — never hardcode the literal number in prose.

Why this module exists (audit §1.2): the same thresholds were previously
restated in fresh prose across ``prompt_constants.py``, ``prompt_builder.py``
(SPECIALIST_FOCUS + ``_build_severity_rubric``), the Executive-Synthesis builder,
and several ``specialists.py`` ``domain_robustness()`` methods. Changing one
risked silent drift. Centralising the numbers makes a threshold change a
one-line edit and is enforced by ``tests/unit/test_severity_thresholds.py``.
"""

from __future__ import annotations

from typing import Final

# --- Termination for Convenience (TfC) ---
#: TfC escalates from P2 to P1 only when revenue at risk exceeds this percentage.
TFC_REVENUE_PCT: Final[int] = 10
#: ...and the contractual notice period is shorter than this many days.
TFC_NOTICE_DAYS: Final[int] = 90

# --- Revenue / ARR reconciliation mismatch tiers ---
#: Contract-vs-reference ARR mismatch at or above this percentage is P1.
ARR_MISMATCH_P1_PCT: Final[int] = 5
#: ...at or above this (but below P1) is P2.
ARR_MISMATCH_P2_PCT: Final[int] = 2

# --- Change of Control (CoC) revenue exposure ---
#: A consent-required / termination-right CoC clause escalates when revenue at
#: risk exceeds this percentage.
COC_REVENUE_PCT: Final[int] = 5
#: An automatic-termination CoC clause is most severe when revenue at risk
#: exceeds this percentage.
COC_AUTOTERM_REVENUE_PCT: Final[int] = 20

# --- Sanctions / watchlist screening (Issue #274) ---
# Severity of a screening hit by match band. These are possible matches that
# need human review, so the numbers stay here and nowhere else. The merge step
# (resolve_severity) still has the final say.
SCREENING_SEVERITY_EXACT: Final[str] = "P0"
SCREENING_SEVERITY_STRONG: Final[str] = "P1"
SCREENING_SEVERITY_POSSIBLE: Final[str] = "P2"

#: Starting severity for a public-source lead found by profile research (Issue #274).
#: The merge step still decides the final severity through ``resolve_severity()``.
PROFILE_LEAD_SEVERITY: Final[dict[str, str]] = {
    "sanctions": "P1",
    "enforcement": "P1",
    "litigation": "P2",
    "regulatory": "P2",
    "adverse_media": "P3",
    "other": "P3",
}
