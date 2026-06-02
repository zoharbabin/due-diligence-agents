"""Cross-domain trigger engine for the neurosymbolic orchestrator.

Scans pass-1 specialist findings and emits :class:`CrossDomainTrigger`
objects when patterns indicate that another domain should verify or
quantify the finding.  The trigger engine is purely symbolic — no LLM
calls, fully deterministic and auditable.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
MAX_TRIGGERS_PER_SUBJECT = 20
DEFAULT_ESTIMATED_COST = 0.50


def _severity_rank(sev: str) -> int:
    return _SEVERITY_ORDER.get(sev.upper(), 99)


def _severity_at_most(sev: str, threshold: str) -> bool:
    """True if *sev* is equal to or more severe than *threshold* (P0 < P1 < P2)."""
    return _severity_rank(sev) <= _severity_rank(threshold)


# ---------------------------------------------------------------------------
# Prompt sanitisation (defence against prompt injection)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(?:system|user|assistant)\s*>", re.IGNORECASE),
)


def sanitize_for_prompt(text: str) -> str:
    """Strip instruction-like patterns from finding text before prompt injection."""
    result = text
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result[:2000]


# ---------------------------------------------------------------------------
# Trigger instruction template (audit §3.3)
#
# All 7 built-in rules render their pass-2 instruction through this single
# helper so every cross-domain trigger has a uniform shape: an action verb
# line, numbered steps (findings -> metrics -> cross-ref), a severity-
# escalation hint, and a citation mandate. KISS: pure string assembly, no LLM.
# ---------------------------------------------------------------------------


def _trigger_instruction(*, action: str, steps: list[str], severity_hint: str) -> str:
    """Render a uniform cross-domain trigger instruction.

    Shape (stable across all rules):
        <action>
        1. <step>
        2. <step>
        ...
        SEVERITY: <severity_hint>
        Cite all thresholds/findings with source file paths.
    """
    numbered = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    return f"{action}\n{numbered}\nSEVERITY: {severity_hint}\nCite all thresholds/findings with source file paths."


# ---------------------------------------------------------------------------
# CrossDomainTrigger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossDomainTrigger:
    """An instruction for a pass-2 specialist to verify a cross-domain finding."""

    trigger_id: str
    source_agent: str
    target_agent: str
    trigger_type: str
    source_finding_ids: tuple[str, ...]
    subject: str
    contracts: tuple[str, ...]
    instructions: str
    priority: str
    estimated_cost: float
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "trigger_type": self.trigger_type,
            "source_finding_ids": list(self.source_finding_ids),
            "subject": self.subject,
            "contracts": list(self.contracts),
            "instructions": self.instructions,
            "priority": self.priority,
            "estimated_cost": self.estimated_cost,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# TriggerRule protocol
# ---------------------------------------------------------------------------


class TriggerRule(Protocol):
    """A callable that evaluates findings for one subject and returns triggers."""

    @property
    def name(self) -> str: ...

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]: ...


# ---------------------------------------------------------------------------
# Finding helpers
# ---------------------------------------------------------------------------


def _get_category(f: dict[str, Any]) -> str:
    return str(f.get("category", "")).lower().strip()


def _get_severity(f: dict[str, Any]) -> str:
    return str(f.get("severity", "P3")).upper().strip()


def _get_agent(f: dict[str, Any]) -> str:
    return str(f.get("agent", f.get("_agent", ""))).lower().strip()


def _get_id(f: dict[str, Any]) -> str:
    return str(f.get("finding_id", f.get("id", "")))


def _get_contracts(f: dict[str, Any]) -> list[str]:
    """Extract contract file paths from a finding's citations."""
    contracts: list[str] = []
    for cite in f.get("citations", []):
        path = cite.get("source_path", "")
        if path and not path.startswith("[synthetic"):
            contracts.append(path)
    return contracts


def _category_matches(category: str, targets: tuple[str, ...]) -> bool:
    """Check if *category* matches any of the *targets* via substring."""
    cat = category.lower()
    return any(t in cat for t in targets)


def _make_trigger(
    source_agent: str,
    target_agent: str,
    trigger_type: str,
    source_findings: list[dict[str, Any]],
    subject: str,
    instructions: str,
    priority: str | None = None,
) -> CrossDomainTrigger:
    best_sev = min((_get_severity(f) for f in source_findings), key=_severity_rank, default="P2")
    contracts: list[str] = []
    for f in source_findings:
        contracts.extend(_get_contracts(f))
    return CrossDomainTrigger(
        trigger_id=str(uuid.uuid4()),
        source_agent=source_agent,
        target_agent=target_agent,
        trigger_type=trigger_type,
        source_finding_ids=tuple(_get_id(f) for f in source_findings),
        subject=subject,
        contracts=tuple(dict.fromkeys(contracts)),
        instructions=instructions,
        priority=priority or best_sev,
        estimated_cost=DEFAULT_ESTIMATED_COST,
    )


# ---------------------------------------------------------------------------
# Built-in trigger rules (7)
# ---------------------------------------------------------------------------


class _RuleBase:
    """Mixin providing ``name`` from class attribute."""

    _name: str = ""

    @property
    def name(self) -> str:
        return self._name


class RevenueRecognitionEnforceability(_RuleBase):
    """Finance revenue_recognition → Legal enforceability verification."""

    _name = "revenue_recognition_enforceability"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "finance"
            and _category_matches(_get_category(f), ("revenue_recognition", "revenue_reclass", "deferred_revenue"))
            and _severity_at_most(_get_severity(f), "P2")
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="finance",
                target_agent="legal",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Review the cited contracts for revenue-recognition enforceability:",
                    steps=[
                        "enforceable rights under ASC 606",
                        "delivery/acceptance criteria",
                        "clawback or refund clauses",
                        "time-based vs delivery-based recognition language",
                    ],
                    severity_hint=(
                        "escalate to P1 if recognized revenue depends on unenforceable "
                        "or contested rights; otherwise treat as a P2 valuation concern"
                    ),
                ),
            )
        ]


class CoCFinancialImpact(_RuleBase):
    """Legal change_of_control → Finance impact quantification."""

    _name = "coc_financial_impact"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "legal"
            and _category_matches(_get_category(f), ("change_of_control", "coc"))
            and _severity_at_most(_get_severity(f), "P1")
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="legal",
                target_agent="finance",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Quantify the financial exposure of the change-of-control trigger:",
                    steps=[
                        "revenue at risk if CoC terminates contracts",
                        "prepaid fee refund obligations",
                        "acceleration clauses",
                        "impact on ARR/TCV projections",
                    ],
                    severity_hint=(
                        "P0 if CoC auto-terminates contracts representing material revenue; "
                        "P1 if consent/renegotiation is required on material revenue"
                    ),
                ),
            )
        ]


class TerminationRevenueExposure(_RuleBase):
    """Legal termination (TfC) → Finance revenue exposure."""

    _name = "termination_revenue_exposure"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "legal"
            and _category_matches(_get_category(f), ("termination",))
            and any(
                kw in str(f.get("description", "")).lower() + str(f.get("title", "")).lower()
                for kw in ("convenience", "tfc", "without cause", "for convenience")
            )
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="legal",
                target_agent="finance",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Calculate revenue exposure from termination-for-convenience clauses:",
                    steps=[
                        "remaining contract value at risk",
                        "termination penalty amounts",
                        "impact on committed vs uncommitted revenue",
                    ],
                    severity_hint=(
                        "escalate to P1 if TfC-exposed revenue exceeds the configured ARR "
                        "threshold with short notice periods; otherwise P2 (at-risk ARR signal). "
                        "Never flag TfC as P0"
                    ),
                ),
            )
        ]


class IPOwnershipTechRisk(_RuleBase):
    """Legal IP ownership → ProductTech technical impact."""

    _name = "ip_ownership_tech_risk"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "legal"
            and _category_matches(_get_category(f), ("ip_ownership", "intellectual_property", "ip_assign"))
            and _severity_at_most(_get_severity(f), "P1")
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="legal",
                target_agent="producttech",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Assess the technical impact of the disputed IP ownership:",
                    steps=[
                        "which systems/codebases use the disputed IP",
                        "dependency depth",
                        "availability of alternatives",
                        "migration cost estimate",
                    ],
                    severity_hint=(
                        "P1 if the disputed IP is embedded in core product systems with no "
                        "viable alternative; P2 if isolated or readily replaceable"
                    ),
                ),
            )
        ]


_CROSS_BORDER_KEYWORDS = ("cross_border", "cross-border", "international", "transborder", "sccs", "adequacy")
_SERVICE_CREDIT_KEYWORDS = ("service_credit", "service credit", "credit", "penalty", "rebate", "10%", "15%", "20%")


class DataPrivacyCompliance(_RuleBase):
    """ProductTech data_privacy → Legal DPA compliance verification."""

    _name = "data_privacy_compliance"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "producttech"
            and _category_matches(_get_category(f), ("data_privacy", "security_posture", "gdpr", "cross_border"))
            and (
                _category_matches(_get_category(f), ("cross_border", "gdpr"))
                or any(
                    kw in (str(f.get("title", "")) + str(f.get("description", ""))).lower()
                    for kw in _CROSS_BORDER_KEYWORDS
                )
            )
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="producttech",
                target_agent="legal",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Review DPA/data-processing provisions for cross-border compliance:",
                    steps=[
                        "SCCs or adequacy decisions",
                        "sub-processor obligations",
                        "data breach notification requirements",
                        "GDPR Article 28 compliance",
                    ],
                    severity_hint=(
                        "P1 if cross-border transfers lack a valid mechanism (no SCCs/adequacy) "
                        "or GDPR Article 28 obligations are missing; otherwise P2"
                    ),
                ),
            )
        ]


class SLAFinancialImpact(_RuleBase):
    """Commercial SLA risk → Finance service credit quantification."""

    _name = "sla_financial_impact"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "commercial"
            and _category_matches(_get_category(f), ("sla_risk", "sla_breach", "service_level", "service_credit"))
            and (
                _category_matches(_get_category(f), ("service_credit",))
                or any(
                    kw in (str(f.get("title", "")) + str(f.get("description", ""))).lower()
                    for kw in _SERVICE_CREDIT_KEYWORDS
                )
            )
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="commercial",
                target_agent="finance",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Quantify SLA financial exposure from service-credit obligations:",
                    steps=[
                        "maximum annual service credit liability",
                        "fee reduction triggers and amounts",
                        "impact on recurring revenue recognition",
                    ],
                    severity_hint=(
                        "escalate to P1 if maximum service-credit liability exceeds the "
                        "configured ARR threshold; otherwise P2"
                    ),
                ),
            )
        ]


class PricingCommercialValidation(_RuleBase):
    """Finance pricing risk → Commercial pricing structure validation."""

    _name = "pricing_commercial_validation"

    def __call__(self, subject: str, findings: list[dict[str, Any]]) -> list[CrossDomainTrigger]:
        hits = [
            f
            for f in findings
            if _get_agent(f) == "finance"
            and _category_matches(_get_category(f), ("pricing_risk", "financial_discrepancy", "pricing_anomal"))
        ]
        if not hits:
            return []
        return [
            _make_trigger(
                source_agent="finance",
                target_agent="commercial",
                trigger_type=self._name,
                source_findings=hits,
                subject=subject,
                instructions=_trigger_instruction(
                    action="Validate the pricing structure behind the flagged discrepancy:",
                    steps=[
                        "are discounts reflected in rate cards",
                        "volume commitment vs actual usage",
                        "renewal pricing mechanisms",
                        "competitive benchmarking",
                    ],
                    severity_hint=(
                        "P1 if the pricing discrepancy materially overstates revenue or "
                        "ARR; otherwise P2 (pricing-quality concern)"
                    ),
                ),
            )
        ]


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------

BUILTIN_RULES: tuple[TriggerRule, ...] = (  # type: ignore[assignment]
    RevenueRecognitionEnforceability(),
    CoCFinancialImpact(),
    TerminationRevenueExposure(),
    IPOwnershipTechRisk(),
    DataPrivacyCompliance(),
    SLAFinancialImpact(),
    PricingCommercialValidation(),
)


def get_builtin_rules() -> tuple[TriggerRule, ...]:
    return BUILTIN_RULES


# ---------------------------------------------------------------------------
# TriggerEngine
# ---------------------------------------------------------------------------


class TriggerEngine:
    """Deterministic rule engine for cross-domain trigger evaluation.

    Evaluates all rules against all subjects, filters by config, and
    applies budget bounding.  No LLM calls — purely symbolic.
    """

    def __init__(
        self,
        rules: list[TriggerRule] | None = None,
        *,
        enabled: bool = True,
        max_budget_usd: float = 5.0,
        min_trigger_severity: str = "P2",
        disabled_rules: list[str] | None = None,
    ) -> None:
        self._rules = list(rules) if rules is not None else list(BUILTIN_RULES)
        self._enabled = enabled
        self._max_budget = max_budget_usd
        self._min_severity = min_trigger_severity
        self._disabled_rules = set(disabled_rules or [])

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> TriggerEngine:
        """Create a TriggerEngine from the ``cross_domain`` config section."""
        if config is None:
            return cls()
        cd = config.get("forensic_dd", config) if isinstance(config, dict) else config
        cross = cd.get("cross_domain", {}) if isinstance(cd, dict) else {}
        if not isinstance(cross, dict):
            return cls()
        return cls(
            enabled=cross.get("enabled", True),
            max_budget_usd=cross.get("max_pass2_budget_usd", 5.0),
            min_trigger_severity=cross.get("min_trigger_severity", "P2"),
            disabled_rules=cross.get("disabled_rules", []),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def evaluate(
        self,
        findings_by_subject: dict[str, list[dict[str, Any]]],
        active_agents: list[str] | None = None,
    ) -> list[CrossDomainTrigger]:
        """Run all rules against all subjects.  Return budget-bounded triggers."""
        if not self._enabled:
            return []

        active = set(active_agents) if active_agents else None
        effective_rules = [r for r in self._rules if r.name not in self._disabled_rules]

        all_triggers: list[CrossDomainTrigger] = []
        skipped_severity = 0
        skipped_agent = 0

        for subject, findings in sorted(findings_by_subject.items()):
            subject_triggers: list[CrossDomainTrigger] = []
            for rule in effective_rules:
                try:
                    triggers = rule(subject, findings)
                except Exception:
                    logger.exception("Trigger rule %s failed for subject %s", rule.name, subject)
                    continue
                for t in triggers:
                    if active and t.target_agent not in active:
                        skipped_agent += 1
                        continue
                    if not _severity_at_most(t.priority, self._min_severity):
                        skipped_severity += 1
                        continue
                    subject_triggers.append(t)
            all_triggers.extend(subject_triggers[:MAX_TRIGGERS_PER_SUBJECT])

        all_triggers.sort(key=lambda t: (_severity_rank(t.priority), t.trigger_type, t.subject))

        bounded: list[CrossDomainTrigger] = []
        budget_remaining = self._max_budget
        skipped_budget = 0
        for t in all_triggers:
            if t.estimated_cost <= budget_remaining:
                bounded.append(t)
                budget_remaining -= t.estimated_cost
            else:
                skipped_budget += 1

        if skipped_severity:
            logger.info("Cross-domain: %d triggers skipped (severity filter)", skipped_severity)
        if skipped_agent:
            logger.info("Cross-domain: %d triggers skipped (target agent not active)", skipped_agent)
        if skipped_budget:
            logger.info(
                "Cross-domain: %d triggers skipped (budget exhausted, limit=$%.2f)",
                skipped_budget,
                self._max_budget,
            )
        if bounded:
            logger.info(
                "Cross-domain: %d triggers selected ($%.2f estimated)",
                len(bounded),
                sum(t.estimated_cost for t in bounded),
            )

        return bounded
