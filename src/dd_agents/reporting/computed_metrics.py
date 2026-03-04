"""Pre-computed report metrics engine (Issue #101).

Single-pass computation of ALL report metrics from merged customer outputs.
Every renderer consumes ``ReportComputedData`` — no renderer computes its own metrics.

Deterministic — no LLM calls. Pure data aggregation.
"""

from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Severity weights for risk score calculation
_SEVERITY_WEIGHTS: dict[str, float] = {"P0": 10.0, "P1": 5.0, "P2": 2.0, "P3": 1.0}

_DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

# ---------------------------------------------------------------------------
# Canonical category mapping (per domain)
# ---------------------------------------------------------------------------
# Maps freeform agent-produced category strings to ~12 canonical categories
# per domain using keyword matching.  If no keyword matches, falls through
# as-is (no data loss).

CANONICAL_CATEGORIES: dict[str, dict[str, list[str]]] = {
    "legal": {
        "Change of Control": ["change_of_control", "coc", "assignment_restriction"],
        "Termination & Exit": ["terminat", "exit", "expir", "wind_down"],
        "IP & Ownership": ["ip_", "intellectual_property", "ownership", "patent", "copyright", "trade_secret"],
        "Liability & Indemnification": ["liabil", "indemnif", "limitation_of", "cap_on"],
        "Data Privacy & Security": ["data_priv", "gdpr", "ccpa", "security", "breach_notif", "pii"],
        "Regulatory & Compliance": ["regulat", "compliance", "anti_", "sanction", "export_control"],
        "Governance & Structure": ["governance", "corporate_struct", "board", "voting", "shareholder"],
        "Contract Terms": ["payment_term", "pricing", "fee_", "rate_", "billing", "invoice"],
        "Non-Compete & Restrictive": ["non_compete", "non_solicit", "restrictive", "exclusiv"],
        "Warranty & Representation": ["warrant", "representat", "covenant"],
        "Insurance & Risk Transfer": ["insurance", "risk_transfer", "force_majeure"],
        "Employment & Benefits": ["employ", "benefit", "compensation", "equity_", "stock_option"],
    },
    "finance": {
        "Revenue Recognition": ["revenue", "arr_", "mrr_", "booking", "deferred_revenue"],
        "Profitability & Margins": ["profit", "margin", "ebitda", "cost_struct", "gross_margin"],
        "Cash Flow & Liquidity": ["cash_flow", "liquidity", "working_capital", "burn_rate"],
        "Debt & Obligations": ["debt", "loan", "credit_facil", "obligation", "covenant"],
        "Tax": ["tax_", "transfer_pricing", "nexus", "vat_"],
        "Audit & Controls": ["audit", "internal_control", "sox_", "material_weakness"],
        "Financial Reporting": ["financial_report", "restatement", "accounting_polic"],
        "Customer Economics": ["customer_econom", "ltv", "cac", "churn", "retention"],
        "Concentration Risk": ["concentrat", "customer_concentrat", "revenue_concentrat"],
        "Projections & Forecasts": ["project", "forecast", "budget", "plan_"],
    },
    "commercial": {
        "Customer Concentration": ["concentrat", "top_customer", "key_account", "revenue_concentrat"],
        "Market Position": ["market_", "competitive", "positioning", "market_share"],
        "Sales Pipeline": ["pipeline", "sales_", "bookings", "quota"],
        "Pricing & Packaging": ["pricing", "discount", "packaging", "rate_card"],
        "Customer Satisfaction": ["satisfact", "nps", "churn", "retention", "renewal"],
        "Channel & Partnerships": ["channel", "partner", "reseller", "distributor"],
        "Go-to-Market": ["go_to_market", "gtm", "expansion", "upsell", "cross_sell"],
        "Contract Portfolio": ["contract_portf", "backlog", "committed", "renewal_risk"],
    },
    "producttech": {
        "Architecture & Scalability": ["architect", "scal", "infrastructure", "cloud"],
        "Technical Debt": ["technical_debt", "legacy", "deprecat", "end_of_life"],
        "Security": ["security", "vulnerab", "penetrat", "access_control", "encrypt"],
        "Data & Analytics": ["data_", "analytics", "ml_", "ai_", "database"],
        "Development Process": ["dev_process", "ci_cd", "agile", "sprint", "sdlc"],
        "Performance": ["performance", "latency", "uptime", "sla_", "reliability"],
        "IP & Innovation": ["ip_", "patent", "open_source", "licens"],
        "Team & Capabilities": ["team_", "hiring", "talent", "skill_gap", "key_person"],
    },
}


def _normalize_category(category: str, domain: str) -> str:
    """Map a freeform category string to its canonical name for the given domain.

    Uses keyword matching against ``CANONICAL_CATEGORIES``.  When multiple
    keywords match, the **longest** keyword wins (most specific match).
    Falls through unchanged if no keyword matches.
    """
    cat_lower = category.lower().replace(" ", "_")
    domain_map = CANONICAL_CATEGORIES.get(domain, {})
    best_canonical: str | None = None
    best_keyword_len = 0
    for canonical, keywords in domain_map.items():
        for kw in keywords:
            if kw in cat_lower and len(kw) > best_keyword_len:
                best_canonical = canonical
                best_keyword_len = len(kw)
    return best_canonical if best_canonical is not None else category


class ReportComputedData(BaseModel):
    """All pre-computed metrics for the HTML report.

    Computed once by ``ReportDataComputer.compute()``, consumed by every renderer.
    """

    # Deal-level counts
    total_findings: int = 0
    total_gaps: int = 0
    total_customers: int = 0
    customers_analyzed: int = 0

    # Severity breakdown
    findings_by_severity: dict[str, int] = Field(default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0})

    # Domain breakdown
    findings_by_domain: dict[str, int] = Field(default_factory=dict)

    # Category breakdown: category -> list of enriched finding dicts
    findings_by_category: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    # Domain -> category -> list of enriched finding dicts
    category_groups: dict[str, dict[str, list[dict[str, Any]]]] = Field(default_factory=dict)

    # Risk scoring
    deal_risk_score: float = 0.0
    deal_risk_label: str = "Clean"
    domain_risk_scores: dict[str, float] = Field(default_factory=dict)
    domain_risk_labels: dict[str, str] = Field(default_factory=dict)
    customer_risk_scores: dict[str, float] = Field(default_factory=dict)
    top_customers_by_risk: list[str] = Field(default_factory=list)

    # Domain severity matrix: domain -> severity -> count
    domain_severity: dict[str, dict[str, int]] = Field(default_factory=dict)

    # Concentration
    concentration_hhi: float = 0.0

    # Gaps
    gaps_by_priority: dict[str, int] = Field(default_factory=dict)
    gaps_by_type: dict[str, int] = Field(default_factory=dict)

    # Cross-reference
    total_cross_refs: int = 0
    cross_ref_matches: int = 0
    cross_ref_mismatches: int = 0
    match_rate: float = 0.0

    # Governance
    avg_governance_pct: float = 0.0
    governance_scores: dict[str, float] = Field(default_factory=dict)
    unresolved_governance_count: int = 0

    # Wolf pack (P0+P1 findings, sorted)
    wolf_pack: list[dict[str, Any]] = Field(default_factory=list)

    # Wolf pack P0 only (capped at 15, for Deal Breakers section)
    wolf_pack_p0: list[dict[str, Any]] = Field(default_factory=list)

    # All findings enriched with _customer_safe_name and _customer
    all_findings: list[dict[str, Any]] = Field(default_factory=list)

    # Category-domain matrices (for heat map)
    category_domain_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    severity_domain_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)

    # Pre-merge / quality (optional, set externally)
    pre_merge_passed: bool | None = None
    qa_scores: dict[str, float] | None = None
    numerical_audit_passed: bool | None = None

    # Buyer context (optional, set externally)
    buyer_strategy: dict[str, Any] | None = None
    acquirer_intelligence: dict[str, Any] | None = None


class ReportDataComputer:
    """Single-pass computation of all report metrics.

    Usage::

        computer = ReportDataComputer()
        data = computer.compute(merged_data)
        # data is a ReportComputedData instance consumed by all renderers
    """

    @staticmethod
    def _agent_to_domain(agent: str) -> str:
        """Map agent name to one of the 4 domains."""
        agent = agent.lower().strip()
        if agent in _DOMAIN_AGENTS:
            return agent
        if "legal" in agent:
            return "legal"
        if "financ" in agent:
            return "finance"
        if "commerc" in agent:
            return "commercial"
        if "product" in agent or "tech" in agent:
            return "producttech"
        return "legal"

    @staticmethod
    def _compute_risk_label(severity_counts: dict[str, int]) -> str:
        """Compute risk label from severity distribution."""
        if severity_counts.get("P0", 0) > 0:
            return "Critical"
        if severity_counts.get("P1", 0) >= 3:
            return "High"
        if severity_counts.get("P1", 0) > 0 or severity_counts.get("P2", 0) >= 5:
            return "Medium"
        if severity_counts.get("P2", 0) > 0:
            return "Low"
        return "Clean"

    @staticmethod
    def _compute_risk_score(severity_counts: dict[str, int]) -> float:
        """Compute numeric risk score (0-100) from severity counts."""
        total_weight = sum(_SEVERITY_WEIGHTS.get(s, 0) * c for s, c in severity_counts.items())
        # Normalize: P0=10 means 1 P0 finding = score 10
        return min(total_weight, 100.0)

    @staticmethod
    def _compute_hhi(customer_finding_counts: dict[str, int]) -> float:
        """Compute Herfindahl-Hirschman Index from finding distribution.

        HHI = sum((share_i * 100)^2) where share_i = count_i / total.
        Range: 10000/N (equal) to 10000 (single customer).
        """
        total = sum(customer_finding_counts.values())
        if total == 0:
            return 0.0
        return sum(((count / total) * 100) ** 2 for count in customer_finding_counts.values())

    def compute(self, merged_data: dict[str, Any]) -> ReportComputedData:
        """Compute all metrics in one pass from merged customer output dicts."""
        total_findings = 0
        total_gaps = 0
        severity_counts: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        domain_findings_count: dict[str, int] = defaultdict(int)
        domain_severity: dict[str, dict[str, int]] = {d: {"P0": 0, "P1": 0, "P2": 0, "P3": 0} for d in _DOMAIN_AGENTS}
        category_groups: dict[str, dict[str, list[dict[str, Any]]]] = {d: defaultdict(list) for d in _DOMAIN_AGENTS}
        findings_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        wolf_pack: list[dict[str, Any]] = []
        all_findings: list[dict[str, Any]] = []
        gap_priority_counts: dict[str, int] = defaultdict(int)
        gap_type_counts: dict[str, int] = defaultdict(int)
        governance_scores: dict[str, float] = {}
        customer_finding_counts: dict[str, int] = defaultdict(int)
        customer_risk_raw: dict[str, dict[str, int]] = defaultdict(lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0})

        # Cross-reference tracking
        total_xrefs = 0
        xref_matches = 0
        xref_mismatches = 0

        # Category-domain matrices
        category_domain_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        severity_domain_matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for csn, data in merged_data.items():
            if not isinstance(data, dict):
                continue

            findings = data.get("findings", [])
            gaps = data.get("gaps", [])
            if not isinstance(findings, list):
                findings = []
            if not isinstance(gaps, list):
                gaps = []

            total_findings += len(findings)
            total_gaps += len(gaps)
            customer_finding_counts[csn] = len(findings)

            # Governance
            gov = data.get("governance_resolution_pct")
            if gov is not None:
                with contextlib.suppress(ValueError, TypeError):
                    governance_scores[csn] = float(gov)

            # Cross-references
            xrefs = data.get("cross_references", [])
            if isinstance(xrefs, list):
                for xr in xrefs:
                    if not isinstance(xr, dict):
                        continue
                    total_xrefs += 1
                    status = str(xr.get("match_status", xr.get("match", ""))).lower()
                    if status in ("match", "true", "yes"):
                        xref_matches += 1
                    elif status in ("mismatch", "false", "no"):
                        xref_mismatches += 1

            # Findings
            for f in findings:
                if not isinstance(f, dict):
                    continue
                sev = str(f.get("severity", "P3"))
                if sev in severity_counts:
                    severity_counts[sev] += 1
                if sev in customer_risk_raw[csn]:
                    customer_risk_raw[csn][sev] += 1

                agent = str(f.get("agent", "")).lower()
                domain = self._agent_to_domain(agent)
                enriched = {**f, "_customer_safe_name": csn, "_customer": data.get("customer", csn)}
                domain_findings_count[domain] += 1
                if domain in domain_severity and sev in domain_severity[domain]:
                    domain_severity[domain][sev] += 1

                raw_cat = str(f.get("category", "uncategorized")).lower()
                cat = _normalize_category(raw_cat, domain)
                if domain in category_groups:
                    category_groups[domain][cat].append(enriched)
                findings_by_category[cat].append(enriched)

                category_domain_matrix[cat][domain] += 1
                severity_domain_matrix[sev][domain] += 1

                if sev in ("P0", "P1"):
                    wolf_pack.append(enriched)

                all_findings.append(enriched)

            # Gaps
            for g in gaps:
                if not isinstance(g, dict):
                    continue
                gap_priority_counts[str(g.get("priority", "unknown"))] += 1
                gap_type_counts[str(g.get("gap_type", "unknown"))] += 1

        # Sort wolf pack: P0 first, then alphabetical
        wolf_pack.sort(key=lambda f: (0 if f.get("severity") == "P0" else 1, str(f.get("title", ""))))

        # Wolf pack P0 only, capped at 15
        wolf_pack_p0 = [f for f in wolf_pack if f.get("severity") == "P0"][:15]

        # Compute derived metrics
        deal_risk_label = self._compute_risk_label(severity_counts)
        deal_risk_score = self._compute_risk_score(severity_counts)

        domain_risk_scores: dict[str, float] = {}
        domain_risk_labels: dict[str, str] = {}
        for d in _DOMAIN_AGENTS:
            domain_risk_scores[d] = self._compute_risk_score(domain_severity.get(d, {}))
            domain_risk_labels[d] = self._compute_risk_label(domain_severity.get(d, {}))

        customer_risk_scores: dict[str, float] = {}
        for csn, sev_dict in customer_risk_raw.items():
            customer_risk_scores[csn] = self._compute_risk_score(sev_dict)

        top_customers = sorted(customer_risk_scores.keys(), key=lambda c: customer_risk_scores[c], reverse=True)

        avg_gov = sum(governance_scores.values()) / len(governance_scores) if governance_scores else 0.0
        unresolved = sum(1 for v in governance_scores.values() if v < 100.0)

        concentration_hhi = self._compute_hhi(customer_finding_counts)

        match_rate = xref_matches / total_xrefs if total_xrefs > 0 else 0.0

        return ReportComputedData(
            total_findings=total_findings,
            total_gaps=total_gaps,
            total_customers=len(merged_data),
            customers_analyzed=len(merged_data),
            findings_by_severity=severity_counts,
            findings_by_domain=dict(domain_findings_count),
            findings_by_category={k: v for k, v in findings_by_category.items()},
            category_groups={d: dict(cats) for d, cats in category_groups.items()},
            deal_risk_score=deal_risk_score,
            deal_risk_label=deal_risk_label,
            domain_risk_scores=domain_risk_scores,
            domain_risk_labels=domain_risk_labels,
            customer_risk_scores=customer_risk_scores,
            top_customers_by_risk=top_customers,
            domain_severity=domain_severity,
            concentration_hhi=concentration_hhi,
            gaps_by_priority=dict(gap_priority_counts),
            gaps_by_type=dict(gap_type_counts),
            total_cross_refs=total_xrefs,
            cross_ref_matches=xref_matches,
            cross_ref_mismatches=xref_mismatches,
            match_rate=match_rate,
            avg_governance_pct=avg_gov,
            governance_scores=governance_scores,
            unresolved_governance_count=unresolved,
            wolf_pack=wolf_pack,
            wolf_pack_p0=wolf_pack_p0,
            all_findings=all_findings,
            category_domain_matrix={k: dict(v) for k, v in category_domain_matrix.items()},
            severity_domain_matrix={k: dict(v) for k, v in severity_domain_matrix.items()},
        )
