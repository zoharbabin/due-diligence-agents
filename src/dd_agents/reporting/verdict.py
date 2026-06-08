"""Deterministic Go/No-Go verdict computation (Issue #195).

Pure functions — no I/O, no shared state, no LLM calls.
Given the same severity counts and risk data, always produces
the same verdict. Fully auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerdictRubric:
    """Configurable thresholds for the deterministic verdict rubric.

    Defaults are conservative. Override any of the four fields via the
    deal-config ``reporting.verdict`` section (see ``VerdictRubricConfig``):
    ``no_go_p0_min``, ``conditional_p1_min``, ``proceed_with_conditions_p1_min``,
    ``high_exposure_pct``.
    """

    no_go_p0_min: int = 1
    conditional_p1_min: int = 3
    proceed_with_conditions_p1_min: int = 1
    high_exposure_pct: float = 20.0


@dataclass(frozen=True)
class VerdictResult:
    """Output of deterministic verdict computation."""

    signal: str
    rationale: str
    risk_score: float
    contributing_factors: list[str] = field(default_factory=list)


# Verdict signal constants
SIGNAL_NO_GO = "NO-GO"
SIGNAL_CONDITIONAL = "CONDITIONAL"
SIGNAL_PROCEED_CONDITIONS = "PROCEED WITH CONDITIONS"
SIGNAL_PROCEED = "PROCEED"


def compute_verdict(
    p0_count: int,
    p1_count: int,
    exposure_pct: float,
    cross_domain_critical_count: int = 0,
    rubric: VerdictRubric | None = None,
    risk_score: float = 0.0,
) -> VerdictResult:
    """Compute a deterministic Go/No-Go verdict from quantitative inputs.

    Parameters
    ----------
    p0_count:
        Number of P0 (critical/deal-breaker) findings.
    p1_count:
        Number of P1 (high severity) findings.
    exposure_pct:
        Financial exposure as percentage of total ARR (0-100).
    cross_domain_critical_count:
        Number of compound P0 cross-domain risks.
    rubric:
        Override thresholds (optional, defaults are conservative).
    risk_score:
        Pre-computed deal risk score (0-100).

    Returns
    -------
    VerdictResult with signal, rationale, and contributing factors.
    """
    if rubric is None:
        rubric = VerdictRubric()

    factors: list[str] = []

    # Rule 1: Any P0 finding = NO-GO
    if p0_count >= rubric.no_go_p0_min:
        factors.append(f"{p0_count} critical deal-breaker(s) identified")
        if cross_domain_critical_count > 0:
            factors.append(f"{cross_domain_critical_count} compound cross-domain critical risk(s)")
        if exposure_pct > rubric.high_exposure_pct:
            factors.append(f"{exposure_pct:.0f}% revenue at risk")
        return VerdictResult(
            signal=SIGNAL_NO_GO,
            rationale=f"{p0_count} critical deal-breaker(s) identified requiring resolution before proceeding",
            risk_score=risk_score,
            contributing_factors=factors,
        )

    # Rule 2: High P1 count = CONDITIONAL
    if p1_count >= rubric.conditional_p1_min:
        factors.append(f"{p1_count} high-severity findings require resolution pre-close")
        if exposure_pct > rubric.high_exposure_pct:
            factors.append(f"{exposure_pct:.0f}% revenue at risk exceeds threshold")
        return VerdictResult(
            signal=SIGNAL_CONDITIONAL,
            rationale=f"{p1_count} high-severity findings require resolution pre-close",
            risk_score=risk_score,
            contributing_factors=factors,
        )

    # Rule 3: Some P1 findings = PROCEED WITH CONDITIONS
    if p1_count >= rubric.proceed_with_conditions_p1_min:
        factors.append(f"{p1_count} high-severity finding(s) — addressable but require attention")
        if exposure_pct > rubric.high_exposure_pct:
            factors.append(f"{exposure_pct:.0f}% revenue at risk")
        return VerdictResult(
            signal=SIGNAL_PROCEED_CONDITIONS,
            rationale=f"{p1_count} high-severity finding(s) — addressable but require attention",
            risk_score=risk_score,
            contributing_factors=factors,
        )

    # Rule 4: High exposure alone = PROCEED WITH CONDITIONS
    if exposure_pct > rubric.high_exposure_pct:
        factors.append(f"{exposure_pct:.0f}% revenue at risk exceeds threshold")
        return VerdictResult(
            signal=SIGNAL_PROCEED_CONDITIONS,
            rationale=f"Revenue exposure ({exposure_pct:.0f}%) exceeds {rubric.high_exposure_pct:.0f}% threshold",
            risk_score=risk_score,
            contributing_factors=factors,
        )

    # Rule 5: No material blockers
    factors.append("No material blockers identified")
    return VerdictResult(
        signal=SIGNAL_PROCEED,
        rationale="No material blockers identified",
        risk_score=risk_score,
        contributing_factors=factors,
    )


def generate_executive_takeaways(
    cross_domain_risks: list[dict[str, Any]],
    material_findings: list[dict[str, Any]],
    display_names: dict[str, str],
    total_contracted_arr: float,
    revenue_by_subject: dict[str, float],
) -> list[dict[str, str]]:
    """Generate 3-5 executive takeaways connecting insights across domains.

    Each takeaway cites source domains and explains WHY the connection matters.
    Deterministic — same inputs always produce same output.
    """
    takeaways: list[dict[str, str]] = []

    # Takeaway 1: Top compound cross-domain risk
    for risk in cross_domain_risks[:2]:
        entity = risk.get("entity", "")
        domains = risk.get("domains", [])
        if len(domains) < 2:
            continue
        display = display_names.get(entity, entity)
        domain_str = " + ".join(d.capitalize() for d in domains[:3])
        finding_count = risk.get("finding_count", 0)
        has_p0 = risk.get("has_p0", False)

        revenue = revenue_by_subject.get(entity, 0.0)
        revenue_note = ""
        if revenue > 0 and total_contracted_arr > 0:
            pct = revenue / total_contracted_arr * 100
            revenue_note = f" representing {pct:.0f}% of contracted revenue"

        severity_text = "critical compound risk" if has_p0 else "elevated cross-domain concern"
        takeaways.append(
            {
                "text": (
                    f"{display} flagged across {len(domains)} domains ({domain_str}) "
                    f"with {finding_count} correlated findings{revenue_note} — "
                    f"{severity_text} requiring coordinated review"
                ),
                "domains": domain_str,
                "severity": "critical" if has_p0 else "high",
            }
        )

    # Takeaway 2: Revenue concentration risk (if applicable)
    if total_contracted_arr > 0 and revenue_by_subject:
        sorted_rev = sorted(revenue_by_subject.items(), key=lambda x: -x[1])
        if sorted_rev:
            top_entity, top_rev = sorted_rev[0]
            top_pct = top_rev / total_contracted_arr * 100
            if top_pct > 30:
                display = display_names.get(top_entity, top_entity)
                takeaways.append(
                    {
                        "text": (
                            f"{top_pct:.0f}% of revenue concentrated in {display} — "
                            f"customer retention strategy critical for value preservation"
                        ),
                        "domains": "Commercial + Finance",
                        "severity": "high" if top_pct > 50 else "medium",
                    }
                )

    # Takeaway 3: Domain with no material findings (positive signal)
    domains_with_findings: set[str] = set()
    for f in material_findings:
        agent = str(f.get("agent", "")).lower()
        if agent:
            domains_with_findings.add(agent)

    all_domains = {"legal", "finance", "commercial", "producttech", "cybersecurity", "hr", "tax", "regulatory", "esg"}
    clean_domains = all_domains - domains_with_findings
    if clean_domains and len(takeaways) < 5:
        clean_list = ", ".join(d.capitalize() for d in sorted(clean_domains)[:3])
        takeaways.append(
            {
                "text": f"No material blockers identified in {clean_list}",
                "domains": clean_list,
                "severity": "good",
            }
        )

    return takeaways[:5]
