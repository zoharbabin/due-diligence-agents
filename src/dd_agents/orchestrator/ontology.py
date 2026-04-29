"""Cross-domain dependency ontology for M&A due diligence.

A lightweight dependency graph encoding which finding categories in one
specialist domain have implications for other domains.  Used by trigger
rules to fire cross-domain analysis and by the chat system to guide
multi-domain synthesis.

This is a practical dependency graph, not a formal OWL ontology.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainDependency:
    """A directed edge in the cross-domain dependency graph.

    Expresses: when *source_domain* produces findings in *source_categories*,
    *target_domain* should verify/quantify using *target_categories*.
    """

    source_domain: str
    source_categories: tuple[str, ...]
    target_domain: str
    target_categories: tuple[str, ...]
    relationship: str
    bidirectional: bool = False


DOMAIN_DEPENDENCIES: tuple[DomainDependency, ...] = (
    DomainDependency(
        source_domain="finance",
        source_categories=("revenue_recognition",),
        target_domain="legal",
        target_categories=("contract_enforceability", "clawback"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="legal",
        source_categories=("change_of_control",),
        target_domain="finance",
        target_categories=("revenue_exposure", "financial_impact"),
        relationship="quantifies",
    ),
    DomainDependency(
        source_domain="legal",
        source_categories=("termination",),
        target_domain="finance",
        target_categories=("revenue_exposure", "committed_revenue"),
        relationship="quantifies",
    ),
    DomainDependency(
        source_domain="legal",
        source_categories=("ip_ownership",),
        target_domain="producttech",
        target_categories=("technical_dependency", "migration_risk"),
        relationship="technical_impact",
    ),
    DomainDependency(
        source_domain="producttech",
        source_categories=("data_privacy", "security_posture"),
        target_domain="legal",
        target_categories=("dpa_compliance", "regulatory"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="commercial",
        source_categories=("sla_risk",),
        target_domain="finance",
        target_categories=("service_credit_liability", "revenue_recognition"),
        relationship="quantifies",
    ),
    DomainDependency(
        source_domain="finance",
        source_categories=("pricing_risk", "financial_discrepancy"),
        target_domain="commercial",
        target_categories=("rate_card", "volume_commitment"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="cybersecurity",
        source_categories=("data_breach_history", "incident_response"),
        target_domain="legal",
        target_categories=("regulatory_compliance", "liability"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="hr",
        source_categories=("compensation_structure", "benefits_liabilities"),
        target_domain="finance",
        target_categories=("financial_impact", "liability"),
        relationship="quantifies",
    ),
    DomainDependency(
        source_domain="tax",
        source_categories=("transfer_pricing", "nol_limitation"),
        target_domain="finance",
        target_categories=("financial_impact", "valuation_risk"),
        relationship="quantifies",
    ),
    DomainDependency(
        source_domain="regulatory",
        source_categories=("license_renewal", "enforcement_action"),
        target_domain="legal",
        target_categories=("regulatory_compliance", "liability"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="esg",
        source_categories=("environmental_contamination",),
        target_domain="legal",
        target_categories=("liability", "regulatory_compliance"),
        relationship="requires_verification",
    ),
    DomainDependency(
        source_domain="esg",
        source_categories=("environmental_contamination",),
        target_domain="finance",
        target_categories=("financial_impact", "remediation_cost"),
        relationship="quantifies",
    ),
)


def get_dependencies_for_domain(domain: str) -> list[DomainDependency]:
    """Return all dependencies where *domain* is the source."""
    return [d for d in DOMAIN_DEPENDENCIES if d.source_domain == domain]


def get_dependents_of_domain(domain: str) -> list[DomainDependency]:
    """Return all dependencies where *domain* is the target."""
    return [d for d in DOMAIN_DEPENDENCIES if d.target_domain == domain]


def describe_dependencies_for_chat(active_agents: list[str] | None = None) -> str:
    """Build a human-readable summary for the chat system prompt.

    When *active_agents* is provided, only dependencies where both source
    and target are active agents are included.
    """
    agent_set = set(active_agents) if active_agents is not None else None
    lines: list[str] = ["## Cross-Domain Dependencies"]
    lines.append("When answering questions that span multiple domains, these relationships apply:")
    seen: set[tuple[str, str]] = set()
    for dep in DOMAIN_DEPENDENCIES:
        if agent_set is not None and (dep.source_domain not in agent_set or dep.target_domain not in agent_set):
            continue
        key = (dep.source_domain, dep.target_domain)
        if key in seen:
            continue
        seen.add(key)
        src_cats = ", ".join(dep.source_categories)
        lines.append(
            f"- {dep.source_domain.capitalize()} ({src_cats}) → {dep.target_domain.capitalize()} ({dep.relationship})"
        )
    return "\n".join(lines) if len(lines) > 2 else ""
