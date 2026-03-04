"""Pre-computed report metrics engine (Issue #101, #113).

Single-pass computation of ALL report metrics from merged customer outputs.
Every renderer consumes ``ReportComputedData`` — no renderer computes its own metrics.

Deterministic — no LLM calls. Pure data aggregation.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Severity weights for risk score calculation
_SEVERITY_WEIGHTS: dict[str, float] = {"P0": 10.0, "P1": 5.0, "P2": 2.0, "P3": 1.0}

_DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

# Regex for extracting dollar amounts from finding text (D3)
_DOLLAR_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KMBkmb])?")

# Pattern for detecting data-room folder names used as categories
_DATAROOM_FOLDER_RE = re.compile(r"^\d+[\._]\d*[\._]?\s*")

# ---------------------------------------------------------------------------
# Canonical category mapping (per domain)
# ---------------------------------------------------------------------------
# Maps freeform agent-produced category strings to ~12 canonical categories
# per domain using keyword matching.  If no keyword matches, falls through
# as-is (no data loss).

CANONICAL_CATEGORIES: dict[str, dict[str, list[str]]] = {
    "legal": {
        "Change of Control": [
            "change_of_control",
            "change_in_control",
            "coc_",
            "assignment_restriction",
            "assignment_clause",
            "consent_to_assign",
            "novation",
            "successor",
            "transfer_of_control",
            "acquisition_trigger",
            "consent_required",
        ],
        "Termination & Exit": [
            "terminat",
            "exit_",
            "expir",
            "wind_down",
            "cancellat",
            "notice_period",
            "auto_renew",
            "renewal",
            "early_termination",
            "convenience_termination",
            "cure_period",
        ],
        "IP & Ownership": [
            "intellectual_property",
            "ip_ownership",
            "ip_rights",
            "ip_assign",
            "patent",
            "copyright",
            "trade_secret",
            "trademark",
            "work_for_hire",
            "license_grant",
            "invention_assign",
            "open_source_licens",
        ],
        "Liability & Indemnification": [
            "liabil",
            "indemnif",
            "limitation_of",
            "cap_on",
            "consequential_damage",
            "limitation_of_liability",
            "damages_cap",
            "mutual_indemnif",
            "hold_harmless",
        ],
        "Data Privacy & Security": [
            "data_priv",
            "gdpr",
            "ccpa",
            "data_protection",
            "dpa_",
            "breach_notif",
            "pii",
            "personal_data",
            "confidential",
            "nda_",
            "non_disclosure",
            "data_processing",
        ],
        "Regulatory & Compliance": [
            "regulat",
            "compliance",
            "anti_",
            "sanction",
            "export_control",
            "governing_law",
            "jurisdict",
            "arbitrat",
            "dispute_resolution",
            "applicable_law",
            "choice_of_law",
        ],
        "Governance & Structure": [
            "governance",
            "corporate_struct",
            "board_",
            "voting",
            "shareholder",
            "entity_structure",
            "subsidiary",
            "legal_entity",
        ],
        "Contract Terms": [
            "payment_term",
            "pricing_term",
            "fee_schedule",
            "rate_",
            "billing",
            "invoice",
            "sla_term",
            "service_level",
            "scope_of_service",
            "contract_value",
        ],
        "Non-Compete & Restrictive": [
            "non_compete",
            "non_solicit",
            "restrictive_covenant",
            "exclusiv",
            "non_circumvent",
            "geographic_restrict",
            "competitor_restrict",
        ],
        "Warranty & Representation": [
            "warrant",
            "representat",
            "covenant",
            "guarantee",
            "rep_and_warrant",
            "material_misrepresent",
        ],
        "Insurance & Risk Transfer": [
            "insurance",
            "risk_transfer",
            "force_majeure",
            "business_continuity",
            "disaster_recovery",
            "unforeseeable",
        ],
        "Employment & Benefits": [
            "employ",
            "benefit",
            "compensation",
            "equity_plan",
            "stock_option",
            "key_person",
            "key_employee",
            "retention_bonus",
            "non_compete_employ",
            "severance",
        ],
    },
    "finance": {
        "Revenue Recognition": [
            "revenue",
            "arr_",
            "mrr_",
            "booking",
            "deferred_revenue",
            "recurring_revenue",
            "subscription_revenue",
            "annual_recurring",
            "contract_value",
            "total_contract",
        ],
        "Profitability & Margins": [
            "profit",
            "margin",
            "ebitda",
            "cost_struct",
            "gross_margin",
            "operating_margin",
            "unit_econom",
            "cost_of_good",
        ],
        "Cash Flow & Liquidity": [
            "cash_flow",
            "liquidity",
            "working_capital",
            "burn_rate",
            "free_cash_flow",
            "operating_cash",
        ],
        "Debt & Obligations": [
            "debt_",
            "loan_",
            "credit_facil",
            "obligation",
            "covenant",
            "promissory",
            "credit_line",
            "outstanding_balance",
        ],
        "Tax": [
            "tax_",
            "transfer_pricing",
            "nexus",
            "vat_",
            "sales_tax",
            "tax_liability",
            "tax_risk",
            "withholding",
        ],
        "Audit & Controls": [
            "audit",
            "internal_control",
            "sox_",
            "material_weakness",
            "financial_control",
            "accounting_control",
        ],
        "Financial Reporting": [
            "financial_report",
            "restatement",
            "accounting_polic",
            "gaap",
            "ifrs",
            "financial_statement",
        ],
        "Customer Economics": [
            "customer_econom",
            "ltv",
            "cac_",
            "churn_rate",
            "retention_rate",
            "customer_acquisition",
            "lifetime_value",
            "payback_period",
            "net_revenue_retention",
            "gross_retention",
            "nrr_",
            "grr_",
        ],
        "Concentration Risk": [
            "concentrat",
            "customer_concentrat",
            "revenue_concentrat",
            "single_customer",
            "top_customer_risk",
            "dependency_risk",
        ],
        "Pricing & Discounts": [
            "discount",
            "pricing_risk",
            "rate_card",
            "pricing_variance",
            "price_escalat",
            "below_market",
            "price_compression",
        ],
        "Projections & Forecasts": [
            "project",
            "forecast",
            "budget",
            "plan_",
            "pipeline_",
            "growth_rate",
            "forward_looking",
        ],
    },
    "commercial": {
        "Customer Concentration": [
            "concentrat",
            "top_customer",
            "key_account",
            "revenue_concentrat",
            "single_customer",
            "customer_depend",
            "whale_customer",
        ],
        "Market Position": [
            "market_",
            "competitive",
            "positioning",
            "market_share",
            "total_addressable",
            "competitive_landscape",
            "moat_",
        ],
        "Sales Pipeline": [
            "pipeline",
            "sales_",
            "bookings",
            "quota",
            "win_rate",
            "sales_cycle",
            "conversion",
        ],
        "Pricing & Packaging": [
            "pricing",
            "discount",
            "packaging",
            "rate_card",
            "price_point",
            "monetiz",
            "tier_",
            "upsell",
        ],
        "Customer Satisfaction": [
            "satisfact",
            "nps_",
            "churn",
            "retention",
            "renewal",
            "customer_health",
            "net_promoter",
            "customer_success",
        ],
        "Channel & Partnerships": [
            "channel",
            "partner",
            "reseller",
            "distributor",
            "alliance",
            "integration_partner",
            "referral",
        ],
        "Go-to-Market": [
            "go_to_market",
            "gtm",
            "expansion",
            "upsell",
            "cross_sell",
            "land_and_expand",
            "market_entry",
        ],
        "Contract Portfolio": [
            "contract_portf",
            "backlog",
            "committed",
            "renewal_risk",
            "contract_mix",
            "multi_year",
            "evergreen",
        ],
    },
    "producttech": {
        "Architecture & Scalability": [
            "architect",
            "scal",
            "infrastructure",
            "cloud",
            "microservice",
            "monolith",
            "platform_",
        ],
        "Technical Debt": [
            "technical_debt",
            "legacy",
            "deprecat",
            "end_of_life",
            "tech_debt",
            "migration_risk",
            "upgrade_",
        ],
        "Security": [
            "security",
            "vulnerab",
            "penetrat",
            "access_control",
            "encrypt",
            "authentication",
            "authorization",
            "soc2",
            "iso_27001",
            "zero_trust",
        ],
        "Data & Analytics": [
            "data_platform",
            "analytics",
            "ml_",
            "ai_",
            "database",
            "data_warehouse",
            "data_pipeline",
        ],
        "Development Process": [
            "dev_process",
            "ci_cd",
            "agile",
            "sprint",
            "sdlc",
            "devops",
            "deployment",
            "release_",
        ],
        "Performance": [
            "performance",
            "latency",
            "uptime",
            "sla_",
            "reliability",
            "availability",
            "response_time",
            "throughput",
        ],
        "IP & Innovation": [
            "ip_portfolio",
            "patent_",
            "open_source",
            "licens",
            "proprietary",
            "trade_secret",
            "invention",
        ],
        "Product Adoption": [
            "adoption",
            "usage",
            "activation",
            "engagement",
            "product_usage",
            "feature_adoption",
            "dau_",
            "mau_",
        ],
        "Team & Capabilities": [
            "team_",
            "hiring",
            "talent",
            "skill_gap",
            "key_person",
            "engineering_team",
            "headcount",
            "attrition",
        ],
        "Integration & APIs": [
            "integrat",
            "api_",
            "webhook",
            "connector",
            "third_party",
            "ecosystem",
            "interoperab",
        ],
    },
}


def _normalize_category(category: str, domain: str) -> str:
    """Map a freeform category string to its canonical name for the given domain.

    Uses keyword matching against ``CANONICAL_CATEGORIES``.  When multiple
    keywords match, the **longest** keyword wins (most specific match).

    Data-room folder names (e.g. "1.1. Engineering", "2_3_insurance") are
    detected via a leading digit pattern and mapped to "Other" if no
    keyword match is found.

    Falls through unchanged if no keyword matches and the category does
    not look like a data-room folder.
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
    if best_canonical is not None:
        return best_canonical
    # Detect data-room folder names and map to "Other"
    if _DATAROOM_FOLDER_RE.match(cat_lower):
        return "Other"
    return category


def _extract_dollar_amounts(text: str) -> list[float]:
    """Extract dollar amounts from text. Returns list of amounts in dollars."""
    amounts: list[float] = []
    for match in _DOLLAR_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        suffix = match.group(2)
        if suffix:
            suffix = suffix.upper()
            if suffix == "K":
                value *= 1_000
            elif suffix == "M":
                value *= 1_000_000
            elif suffix == "B":
                value *= 1_000_000_000
        amounts.append(value)
    return amounts


def _topic_matches(text: str, keywords: list[str]) -> bool:
    """Check if any keyword appears in text."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


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

    # --- Issue #113: Business-oriented analysis ---

    # Topic-specific finding groups (derived from canonical categories)
    coc_findings: list[dict[str, Any]] = Field(default_factory=list)
    ip_findings: list[dict[str, Any]] = Field(default_factory=list)
    termination_findings: list[dict[str, Any]] = Field(default_factory=list)
    privacy_findings: list[dict[str, Any]] = Field(default_factory=list)
    employment_findings: list[dict[str, Any]] = Field(default_factory=list)
    concentration_findings: list[dict[str, Any]] = Field(default_factory=list)
    pricing_findings: list[dict[str, Any]] = Field(default_factory=list)
    tech_debt_findings: list[dict[str, Any]] = Field(default_factory=list)
    security_findings: list[dict[str, Any]] = Field(default_factory=list)

    # CoC analysis
    coc_customers_affected: int = 0
    consent_required_customers: int = 0

    # Customer health tiers
    tier1_customers: list[str] = Field(default_factory=list, description="P0 findings — immediate attention")
    tier2_customers: list[str] = Field(default_factory=list, description="P1 findings — medium risk")
    tier3_customers: list[str] = Field(default_factory=list, description="P2/P3 only — lower risk")

    # Financial extraction (best-effort regex from finding text)
    extracted_amounts: list[dict[str, Any]] = Field(default_factory=list)
    total_arr_mentioned: float = 0.0

    # Generated recommendations (deterministic from data patterns)
    recommendations: list[dict[str, str]] = Field(default_factory=list)

    # Section RAG status (red/amber/green per section)
    section_rag: dict[str, str] = Field(default_factory=dict)

    # Per-customer P0/P1 summary for customer-level tables
    customer_p0_summary: list[dict[str, Any]] = Field(default_factory=list)
    customer_p1_summary: list[dict[str, Any]] = Field(default_factory=list)


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

        # Sort wolf pack: P0 first, then by severity weight (highest impact first)
        wolf_pack.sort(
            key=lambda f: (
                0 if f.get("severity") == "P0" else 1,
                -_SEVERITY_WEIGHTS.get(str(f.get("severity", "P3")), 0),
                str(f.get("title", "")),
            )
        )

        # Wolf pack P0 only, capped at 15
        all_p0 = [f for f in wolf_pack if f.get("severity") == "P0"]
        wolf_pack_p0 = all_p0[:15]
        if len(all_p0) > 15:
            logger.warning(
                "P0 deal breakers capped at 15 (total: %d). Review the full findings list for complete P0 coverage.",
                len(all_p0),
            )

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

        # --- Issue #113: Topic classification, health tiers, recommendations ---
        topic_findings = self._classify_by_topic(all_findings)
        extracted_amounts, total_arr = self._extract_financials(all_findings)
        tier1, tier2, tier3 = self._compute_health_tiers(customer_risk_raw, merged_data)
        customer_p0_summary, customer_p1_summary = self._build_customer_severity_tables(merged_data, customer_risk_raw)
        recommendations = self._generate_recommendations(
            severity_counts,
            topic_findings,
            total_gaps,
            total_findings,
            governance_scores,
            concentration_hhi,
            len(merged_data),
        )
        section_rag = self._compute_section_rag(
            severity_counts,
            domain_risk_labels,
            match_rate,
            avg_gov,
            total_gaps,
            topic_findings,
        )

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
            # Issue #113 fields
            coc_findings=topic_findings.get("coc", []),
            ip_findings=topic_findings.get("ip", []),
            termination_findings=topic_findings.get("termination", []),
            privacy_findings=topic_findings.get("privacy", []),
            employment_findings=topic_findings.get("employment", []),
            concentration_findings=topic_findings.get("concentration", []),
            pricing_findings=topic_findings.get("pricing", []),
            tech_debt_findings=topic_findings.get("tech_debt", []),
            security_findings=topic_findings.get("security", []),
            coc_customers_affected=len({f.get("_customer_safe_name") for f in topic_findings.get("coc", [])}),
            consent_required_customers=len(
                {
                    f.get("_customer_safe_name")
                    for f in topic_findings.get("coc", [])
                    if "consent" in str(f.get("title", "")).lower()
                    or "consent" in str(f.get("description", "")).lower()
                }
            ),
            tier1_customers=tier1,
            tier2_customers=tier2,
            tier3_customers=tier3,
            extracted_amounts=extracted_amounts,
            total_arr_mentioned=total_arr,
            recommendations=recommendations,
            section_rag=section_rag,
            customer_p0_summary=customer_p0_summary,
            customer_p1_summary=customer_p1_summary,
        )

    # --- Issue #113: Helper methods for business-oriented analysis ---

    @staticmethod
    def _classify_by_topic(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Classify findings into business topic buckets using title/description keywords."""
        topics: dict[str, list[str]] = {
            "coc": ["change of control", "assignment", "consent", "novation", "successor", "transfer of control"],
            "ip": ["intellectual property", "ip ", "patent", "copyright", "trade secret", "trademark", "open source"],
            "termination": ["terminat", "expir", "renewal", "auto-renew", "notice period", "cancellat"],
            "privacy": ["privacy", "gdpr", "ccpa", "dpa", "data protection", "personal data", "breach"],
            "employment": ["employ", "key person", "key employee", "retention", "severance", "compensation"],
            "concentration": ["concentrat", "single customer", "top customer", "dependency", "whale"],
            "pricing": ["discount", "pricing", "rate card", "price", "below market"],
            "tech_debt": ["technical debt", "legacy", "deprecated", "end of life", "migration"],
            "security": ["security", "vulnerab", "penetrat", "access control", "encrypt", "soc2", "iso 27001"],
        }
        result: dict[str, list[dict[str, Any]]] = {k: [] for k in topics}
        for f in all_findings:
            title = str(f.get("title", "")).lower()
            desc = str(f.get("description", "")).lower()
            combined = f"{title} {desc}"
            for topic, keywords in topics.items():
                if _topic_matches(combined, keywords):
                    result[topic].append(f)
                    break  # Each finding classified to first matching topic
        return result

    @staticmethod
    def _extract_financials(
        all_findings: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], float]:
        """Extract dollar amounts from finding descriptions (best-effort D3)."""
        extracted: list[dict[str, Any]] = []
        total = 0.0
        for f in all_findings:
            text = f"{f.get('title', '')} {f.get('description', '')}"
            amounts = _extract_dollar_amounts(text)
            for amt in amounts:
                extracted.append(
                    {
                        "customer": f.get("_customer", ""),
                        "customer_safe_name": f.get("_customer_safe_name", ""),
                        "amount": amt,
                        "source_finding": f.get("title", ""),
                        "severity": f.get("severity", "P3"),
                    }
                )
                total += amt
        return extracted, total

    @staticmethod
    def _compute_health_tiers(
        customer_risk_raw: dict[str, dict[str, int]],
        merged_data: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        """Classify customers into Tier 1/2/3 health tiers."""
        tier1: list[str] = []
        tier2: list[str] = []
        tier3: list[str] = []
        for csn, sev_dict in customer_risk_raw.items():
            data = merged_data.get(csn, {})
            display = data.get("customer", csn) if isinstance(data, dict) else csn
            if sev_dict.get("P0", 0) > 0:
                tier1.append(display)
            elif sev_dict.get("P1", 0) > 0:
                tier2.append(display)
            else:
                tier3.append(display)
        return sorted(tier1), sorted(tier2), sorted(tier3)

    @staticmethod
    def _build_customer_severity_tables(
        merged_data: dict[str, Any],
        customer_risk_raw: dict[str, dict[str, int]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Build customer-level P0/P1 summary tables for executive view."""
        p0_rows: list[dict[str, Any]] = []
        p1_rows: list[dict[str, Any]] = []
        for csn, sev_dict in customer_risk_raw.items():
            data = merged_data.get(csn, {})
            if not isinstance(data, dict):
                continue
            display = data.get("customer", csn)
            findings = data.get("findings", [])
            if not isinstance(findings, list):
                findings = []
            p0_count = sev_dict.get("P0", 0)
            p1_count = sev_dict.get("P1", 0)
            total = sum(sev_dict.values())
            # Collect first P0/P1 finding title as representative issue
            first_p0 = ""
            first_p1 = ""
            for f in findings:
                if not isinstance(f, dict):
                    continue
                if f.get("severity") == "P0" and not first_p0:
                    first_p0 = str(f.get("title", ""))
                if f.get("severity") == "P1" and not first_p1:
                    first_p1 = str(f.get("title", ""))
            if p0_count > 0:
                p0_rows.append(
                    {
                        "customer": display,
                        "customer_safe_name": csn,
                        "p0_count": p0_count,
                        "total_findings": total,
                        "primary_issue": first_p0,
                    }
                )
            if p1_count > 0:
                p1_rows.append(
                    {
                        "customer": display,
                        "customer_safe_name": csn,
                        "p1_count": p1_count,
                        "total_findings": total,
                        "primary_issue": first_p1,
                    }
                )
        p0_rows.sort(key=lambda r: r["p0_count"], reverse=True)
        p1_rows.sort(key=lambda r: r["p1_count"], reverse=True)
        return p0_rows, p1_rows

    @staticmethod
    def _generate_recommendations(
        severity_counts: dict[str, int],
        topic_findings: dict[str, list[dict[str, Any]]],
        total_gaps: int,
        total_findings: int,
        governance_scores: dict[str, float],
        concentration_hhi: float,
        total_customers: int,
    ) -> list[dict[str, str]]:
        """Generate prioritized recommendations from data patterns."""
        recs: list[dict[str, str]] = []

        p0_count = severity_counts.get("P0", 0)
        coc_count = len(topic_findings.get("coc", []))
        privacy_count = len(topic_findings.get("privacy", []))
        security_count = len(topic_findings.get("security", []))
        low_gov = [c for c, v in governance_scores.items() if v < 70]

        if p0_count > 0:
            recs.append(
                {
                    "timeline": "Immediate",
                    "priority": "Critical",
                    "title": f"Resolve {p0_count} P0 Critical Findings Before Closing",
                    "description": (
                        f"{p0_count} critical findings require immediate resolution. "
                        "These represent potential deal-breakers that must be addressed "
                        "or mitigated with appropriate deal structure protections."
                    ),
                }
            )

        if coc_count > 0:
            coc_customers = len({f.get("_customer_safe_name") for f in topic_findings.get("coc", [])})
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "High",
                    "title": f"Obtain Assignment Consent from {coc_customers} Entities",
                    "description": (
                        f"{coc_count} change-of-control findings across {coc_customers} entities. "
                        "Assess consent requirements and initiate outreach to key customers. "
                        "Consider escrow holdback for consent-dependent revenue."
                    ),
                }
            )

        if concentration_hhi > 2500:
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "High",
                    "title": "Negotiate Customer Concentration Protection",
                    "description": (
                        f"HHI concentration index of {concentration_hhi:.0f} indicates high customer concentration. "
                        "Consider earn-out tied to customer retention (10-30% of consideration) "
                        "or escrow holdback for 12-24 months."
                    ),
                }
            )

        if privacy_count > 0:
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "Medium",
                    "title": f"Remediate {privacy_count} Data Privacy & Security Gaps",
                    "description": (
                        f"{privacy_count} data privacy findings identified. "
                        "Assess GDPR/CCPA compliance status and DPA coverage. "
                        "Typical remediation cost: $200K-$2M depending on gap severity."
                    ),
                }
            )

        if security_count > 0:
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "Medium",
                    "title": f"Address {security_count} Security Findings",
                    "description": (
                        f"{security_count} security-related findings. "
                        "Evaluate penetration test results, SOC2 compliance status, "
                        "and encryption standards. Include remediation timeline in closing conditions."
                    ),
                }
            )

        if low_gov:
            recs.append(
                {
                    "timeline": "Post-Close",
                    "priority": "Medium",
                    "title": f"Improve Governance for {len(low_gov)} Low-Resolution Entities",
                    "description": (
                        f"{len(low_gov)} entities have governance resolution below 70%. "
                        "Post-close priority: complete governance resolution and "
                        "standardize contract terms across the portfolio."
                    ),
                }
            )

        if total_gaps > 0:
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "Medium",
                    "title": f"Close {total_gaps} Documentation Gaps",
                    "description": (
                        f"{total_gaps} documentation gaps identified. "
                        "Request missing documents from the target company. "
                        "Prioritize gaps affecting P0/P1 findings."
                    ),
                }
            )

        # Positive finding
        clean_customers = total_customers - len(
            {
                f.get("_customer_safe_name")
                for findings in topic_findings.values()
                for f in findings
                if f.get("severity") in ("P0", "P1")
            }
        )
        if clean_customers > 0:
            recs.append(
                {
                    "timeline": "Positive",
                    "priority": "Good",
                    "title": f"{clean_customers} Entities Have No Critical/High Findings",
                    "description": (
                        f"{clean_customers} of {total_customers} entities analyzed "
                        "have no P0 or P1 findings, indicating a healthy base "
                        "of low-risk contracts."
                    ),
                }
            )

        return recs

    @staticmethod
    def _compute_section_rag(
        severity_counts: dict[str, int],
        domain_risk_labels: dict[str, str],
        match_rate: float,
        avg_gov: float,
        total_gaps: int,
        topic_findings: dict[str, list[dict[str, Any]]],
    ) -> dict[str, str]:
        """Compute Red/Amber/Green status for each report section."""
        rag: dict[str, str] = {}

        # Executive summary
        if severity_counts.get("P0", 0) > 0:
            rag["executive"] = "red"
        elif severity_counts.get("P1", 0) >= 3:
            rag["executive"] = "amber"
        else:
            rag["executive"] = "green"

        # Domain sections
        for domain, label in domain_risk_labels.items():
            if label in ("Critical",):
                rag[f"domain-{domain}"] = "red"
            elif label in ("High", "Medium"):
                rag[f"domain-{domain}"] = "amber"
            else:
                rag[f"domain-{domain}"] = "green"

        # Cross-reference
        if match_rate < 0.7:
            rag["xref"] = "red"
        elif match_rate < 0.9:
            rag["xref"] = "amber"
        else:
            rag["xref"] = "green"

        # Governance
        if avg_gov < 70:
            rag["governance"] = "red"
        elif avg_gov < 90:
            rag["governance"] = "amber"
        else:
            rag["governance"] = "green"

        # Gaps
        if total_gaps > 20:
            rag["gaps"] = "red"
        elif total_gaps > 5:
            rag["gaps"] = "amber"
        else:
            rag["gaps"] = "green"

        # CoC — severity-aware: any P0 CoC finding is red
        coc = topic_findings.get("coc", [])
        coc_has_p0 = any(f.get("severity") == "P0" for f in coc)
        if coc_has_p0 or len(coc) > 10:
            rag["coc"] = "red"
        elif len(coc) > 0:
            rag["coc"] = "amber"
        else:
            rag["coc"] = "green"

        # Privacy — severity-aware: any P0 privacy finding is red
        privacy = topic_findings.get("privacy", [])
        privacy_has_p0 = any(f.get("severity") == "P0" for f in privacy)
        if privacy_has_p0 or len(privacy) > 5:
            rag["privacy"] = "red"
        elif len(privacy) > 0:
            rag["privacy"] = "amber"
        else:
            rag["privacy"] = "green"

        return rag
