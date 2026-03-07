"""Pre-computed report metrics engine (Issue #101, #113).

Single-pass computation of ALL report metrics from merged customer outputs.
Every renderer consumes ``ReportComputedData`` — no renderer computes its own metrics.

Deterministic — no LLM calls. Pure data aggregation.
"""

from __future__ import annotations

import contextlib
import logging
import math
import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Severity weights used for sorting findings (wolf pack, domain lists).
# Risk score uses a separate logarithmic formula in _compute_risk_score().
_SEVERITY_WEIGHTS: dict[str, float] = {"P0": 10.0, "P1": 5.0, "P2": 2.0, "P3": 1.0}

_DOMAIN_AGENTS: list[str] = ["legal", "finance", "commercial", "producttech"]

# Regex for extracting dollar amounts from finding text (D3)
_DOLLAR_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([KMBkmb])?")

# Pattern for detecting data-room folder names used as categories
_DATAROOM_FOLDER_RE = re.compile(r"^\d+[\._]\d*[\._]?\s*")

# ---------------------------------------------------------------------------
# Noise detection — extraction failure vs material DD findings
# ---------------------------------------------------------------------------

_NOISE_PATTERNS: list[str] = [
    "cannot assess",
    "not available",
    "inaccessible",
    "binary",
    "no extractable",
    "unable to extract",
    "no data available",
    "could not extract",
    "extraction fail",
    "unreadable",
    "no documents",
    "file format not supported",
]

# ---------------------------------------------------------------------------
# Post-hoc severity recalibration — deterministic rules for known false-positive patterns
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

_RECALIBRATION_RULES: list[dict[str, object]] = [
    {
        "name": "competitor_only_coc",
        "max_severity": "P3",
        "title_patterns": ["competitor"],
        "text_patterns": ["change of control", "change-of-control", " coc ", "coc "],
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

# Pattern for stripping leading data-room folder numeric prefixes from safe names
_DISPLAY_NAME_PREFIX_RE = re.compile(r"^\d+_\d+_")


def _is_noise_finding(finding: dict[str, Any]) -> bool:
    """Return True if the finding is extraction/pipeline noise, not material DD content."""
    title = str(finding.get("title", ""))
    desc = str(finding.get("description", ""))
    combined = f"{title} {desc}".lower()
    return any(pattern in combined for pattern in _NOISE_PATTERNS)


# ---------------------------------------------------------------------------
# Data quality detection — findings about missing/unavailable data (not noise)
# ---------------------------------------------------------------------------

_DATA_QUALITY_PATTERNS: list[str] = [
    "data unavailable",
    "data unreadable",
    "data not provided",
    "data gap",
    "analysis limitation",
    "insufficient data",
    "records unavailable",
    "waterfall unavailable",
    "documentation insufficient",
    "files unreadable",
    "file unreadable",
    "document unreadable",
    "cannot verify ar",
    "cannot verify revenue",
    "cannot validate revenue",
    "cannot validate financial",
    "cannot assess financial",
]

_DATA_QUALITY_CATEGORIES: set[str] = {
    "missing_document",
    "data_gap",
    "documentation_gap",
}


def _is_data_quality_finding(finding: dict[str, Any]) -> bool:
    """Return True if finding is about data availability, not an actual DD issue."""
    if _is_noise_finding(finding):
        return False  # Noise is separate
    cat = str(finding.get("category", "")).lower().replace(" ", "_")
    if any(dqc in cat for dqc in _DATA_QUALITY_CATEGORIES):
        return True
    combined = f"{finding.get('title', '')} {finding.get('description', '')}".lower()
    return any(p in combined for p in _DATA_QUALITY_PATTERNS)


def _is_noise_gap(gap: dict[str, Any]) -> bool:
    """Return True if the gap is extraction noise rather than a material documentation gap."""
    item = str(gap.get("missing_item", ""))
    risk = str(gap.get("risk_if_missing", ""))
    combined = f"{item} {risk}".lower()
    return any(pattern in combined for pattern in _NOISE_PATTERNS)


def _clean_display_name(safe_name: str) -> str:
    """Convert a customer safe_name to a human-readable display name.

    Examples:
        "1_5_customer_contracts" → "Customer Contracts"
        "snapapp" → "Snapapp"
        "3_9_mapping" → "Mapping"
    """
    name = _DISPLAY_NAME_PREFIX_RE.sub("", safe_name)
    name = name.replace("_", " ").strip()
    return name.title() if name else safe_name.title()


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
            "transfer_of_control",
            "acquisition_trigger",
        ],
        "Assignment & Consent": [
            "assignment_restriction",
            "assignment_clause",
            "consent_to_assign",
            "consent_required",
            "novation",
            "successor",
            "anti_assignment",
        ],
        "Termination & Exit": [
            "terminat",
            "exit_",
            "expir",
            "wind_down",
            "cancellat",
            "cure_period",
            "early_termination",
            "termination_for_cause",
            "termination_cause",
        ],
        "Contract Portfolio": [
            "notice_period",
            "auto_renew",
            "renewal",
            "convenience_termination",
            "termination_for_convenience",
            "termination_convenience",
            "tfc",
            "revenue_quality",
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
        "Revenue Composition": [
            "revenue_composition",
            "revenue_mix",
            "subscription_vs_services",
            "product_revenue",
            "services_revenue",
        ],
        "Cost Structure": [
            "cost_struct",
            "cost_of_revenue",
            "operating_expens",
            "headcount_cost",
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
            "pricing_model",
            "per_user",
            "per_seat",
            "consumption_based",
            "tiered_pricing",
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
        "Customer Segmentation": [
            "customer_segment",
            "cohort",
            "size_tier",
            "geographic_distribut",
            "industry_mix",
        ],
        "Expansion & Contraction": [
            "expansion_",
            "contraction_",
            "nrr_decompos",
            "downsell",
            "downgrade",
        ],
        "Competitive Position": [
            "competitive_position",
            "preferred_vendor",
            "switching_cost",
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

    # Executive synthesis (optional, set externally or via compute())
    executive_synthesis: dict[str, Any] | None = None

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

    # TfC analysis (valuation concern, separate from termination)
    tfc_findings: list[dict[str, Any]] = Field(default_factory=list)
    tfc_customers_affected: int = 0

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

    # --- Rendering overhaul: material vs noise separation ---

    # Material findings (noise filtered out)
    material_findings: list[dict[str, Any]] = Field(default_factory=list)
    noise_findings: list[dict[str, Any]] = Field(default_factory=list)
    material_count: int = 0
    noise_count: int = 0
    data_quality_findings: list[dict[str, Any]] = Field(default_factory=list)
    data_quality_count: int = 0
    material_by_severity: dict[str, int] = Field(default_factory=lambda: {"P0": 0, "P1": 0, "P2": 0, "P3": 0})

    # Material wolf pack (noise filtered)
    material_wolf_pack: list[dict[str, Any]] = Field(default_factory=list)
    material_wolf_pack_p0: list[dict[str, Any]] = Field(default_factory=list)

    # Display names: safe_name → cleaned human-readable name
    display_names: dict[str, str] = Field(default_factory=dict)

    # Top 10 material findings per domain (sorted by severity weight)
    top_findings_by_domain: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    # Material vs noise gaps
    material_gaps: list[dict[str, Any]] = Field(default_factory=list)
    noise_gaps: list[dict[str, Any]] = Field(default_factory=list)

    # --- Issue #143: Confidence Calibration ---
    confidence_distribution: dict[str, int] = Field(
        default_factory=lambda: {"high": 0, "medium": 0, "low": 0},
        description="Count of findings by confidence level",
    )
    low_confidence_count: int = Field(default=0, description="Number of low-confidence findings requiring review")

    # --- Issue #115: SaaS Health Metrics ---
    saas_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="SaaS health metrics: total_customers, avg_contract_value, tier_distribution, etc.",
    )

    # --- Issue #125: Red Flag Scan (quick-scan mode) ---
    red_flag_scan: dict[str, Any] | None = None

    # --- Issue #102: Revenue-at-Risk & Financial Impact ---
    revenue_by_customer: dict[str, float] = Field(default_factory=dict)
    total_contracted_arr: float = 0.0
    risk_adjusted_arr: float = 0.0
    revenue_data_coverage: float = 0.0
    risk_waterfall: dict[str, dict[str, Any]] = Field(default_factory=dict)
    concentration_treemap: list[dict[str, Any]] = Field(default_factory=list)

    # --- Issue #145: Audit Trail & Finding Provenance ---
    provenance_stats: dict[str, Any] = Field(
        default_factory=lambda: {
            "total_findings": 0,
            "high_confidence_pct": 0.0,
            "agent_contribution": {},
            "recalibrated_count": 0,
            "domains_covered": [],
        },
        description="Provenance statistics: agent contribution, confidence, recalibration audit trail",
    )

    # --- Issue #135: Discount & Pricing Analysis ---
    discount_analysis: dict[str, Any] = Field(
        default_factory=lambda: {
            "customers_with_discounts": 0,
            "total_pricing_findings": 0,
            "distribution": {},
            "findings": [],
        },
        description="Discount and pricing analysis: distribution, top discounted customers",
    )

    # --- Issue #136: Renewal & Contract Expiry Analysis ---
    renewal_analysis: dict[str, Any] = Field(
        default_factory=lambda: {
            "total_renewal_findings": 0,
            "auto_renew_count": 0,
            "manual_renew_count": 0,
            "escalation_cap_count": 0,
            "findings": [],
        },
        description="Renewal analysis: type distribution, escalation caps, expiry timeline",
    )

    # --- Issue #121: Regulatory & Compliance Risk ---
    compliance_analysis: dict[str, Any] = Field(
        default_factory=lambda: {
            "dpa_findings_count": 0,
            "jurisdiction_findings_count": 0,
            "regulatory_findings_count": 0,
            "total_compliance_findings": 0,
            "findings": [],
        },
        description="Compliance analysis: DPA coverage, jurisdiction distribution, regulatory risk",
    )

    # --- Issue #137: Legal Entity Distribution ---
    entity_distribution: dict[str, Any] = Field(
        default_factory=lambda: {
            "total_entities_mentioned": 0,
            "entity_findings_count": 0,
            "findings": [],
        },
        description="Legal entity distribution and migration risk analysis",
    )

    # --- Issue #147: Contract Date Timeline ---
    contract_timeline: dict[str, Any] = Field(
        default_factory=lambda: {
            "date_mentions_count": 0,
            "expiry_findings_count": 0,
            "findings": [],
        },
        description="Contract date timeline: expiry calendar, renewal waterfall",
    )


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
    def _recalibrate_severity(finding: dict[str, Any]) -> dict[str, Any]:
        """Apply deterministic severity recalibration rules to a finding.

        Pattern-matches title, description, and category against known
        false-positive patterns.  If current severity is more severe than the
        rule's cap, the finding is downgraded and annotated with an audit trail.
        When multiple rules match, the mildest cap (highest P-number) wins.
        """
        current_sev = str(finding.get("severity", "P3"))
        if current_sev not in _SEVERITY_ORDER:
            return finding

        title_lower = str(finding.get("title", "")).lower()
        desc_lower = str(finding.get("description", "")).lower()
        text_combined = f"{title_lower} {desc_lower}"
        cat_lower = str(finding.get("category", "")).lower()

        best_cap: str | None = None
        best_reason: str = ""

        for rule in _RECALIBRATION_RULES:
            max_sev = str(rule.get("max_severity", "P3"))
            require_all = bool(rule.get("require_all", False))

            # Collect which pattern groups are specified and whether they match
            group_results: list[bool] = []

            title_pats = rule.get("title_patterns")
            if isinstance(title_pats, list) and title_pats:
                group_results.append(any(p.lower() in title_lower for p in title_pats))

            text_pats = rule.get("text_patterns")
            if isinstance(text_pats, list) and text_pats:
                group_results.append(any(p.lower() in text_combined for p in text_pats))

            cat_pats = rule.get("category_patterns")
            if isinstance(cat_pats, list) and cat_pats:
                group_results.append(any(p.lower() in cat_lower for p in cat_pats))

            if not group_results:
                continue

            matched = all(group_results) if require_all else any(group_results)
            if not matched:
                continue

            # This rule matches — check if its cap is milder than current best
            if best_cap is None or _SEVERITY_ORDER.get(max_sev, 3) > _SEVERITY_ORDER.get(best_cap, 3):
                best_cap = max_sev
                best_reason = str(rule.get("reason", ""))

        if best_cap is None:
            return finding

        # Only downgrade (higher P-number = less severe)
        if _SEVERITY_ORDER.get(current_sev, 3) < _SEVERITY_ORDER.get(best_cap, 3):
            recalibrated = {**finding, "severity": best_cap}
            recalibrated["_recalibrated_from"] = current_sev
            recalibrated["_recalibration_reason"] = best_reason
            return recalibrated

        return finding

    @staticmethod
    def _compute_risk_label(severity_counts: dict[str, int]) -> str:
        """Compute risk label from severity distribution.

        Softened mechanical scoring (Issue #113):
        - P0 >= 3 → Critical
        - P0 1-2 → High (previously Critical for any P0)
        - P1 >= 3 → High
        - P1 > 0 or P2 >= 5 → Medium
        - P2 > 0 or P3 > 0 → Low
        - Otherwise → Clean
        """
        p0_count = severity_counts.get("P0", 0)
        if p0_count >= 3:
            return "Critical"
        if p0_count > 0:
            return "High"
        if severity_counts.get("P1", 0) >= 3:
            return "High"
        if severity_counts.get("P1", 0) > 0 or severity_counts.get("P2", 0) >= 5:
            return "Medium"
        if severity_counts.get("P2", 0) > 0 or severity_counts.get("P3", 0) > 0:
            return "Low"
        return "Clean"

    @staticmethod
    def _compute_risk_score(severity_counts: dict[str, int]) -> float:
        """Compute numeric risk score (0-100) from severity counts.

        Uses logarithmic scaling to prevent saturation: even a large deal
        with hundreds of P2/P3 findings will not hit 100 unless there are
        genuine P0 deal-breakers.
        """
        raw = (
            25 * math.log1p(severity_counts.get("P0", 0))
            + 8 * math.log1p(severity_counts.get("P1", 0))
            + 3 * math.log1p(severity_counts.get("P2", 0))
            + 1 * math.log1p(severity_counts.get("P3", 0))
        )
        return min(round(raw, 1), 100.0)

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

    def compute(
        self,
        merged_data: dict[str, Any],
        executive_synthesis: dict[str, Any] | None = None,
    ) -> ReportComputedData:
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
                # Skip placeholder "no issues" findings (consistent with excel.py)
                if str(f.get("category", "")).lower() == "domain_reviewed_no_issues":
                    continue
                f = self._recalibrate_severity(f)
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

        # --- Rendering overhaul: material/noise/data-quality three-way split ---
        material_findings: list[dict[str, Any]] = []
        noise_findings_list: list[dict[str, Any]] = []
        data_quality_findings_list: list[dict[str, Any]] = []
        material_by_severity: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for f in all_findings:
            if _is_noise_finding(f):
                noise_findings_list.append(f)
            elif _is_data_quality_finding(f):
                data_quality_findings_list.append(f)
            else:
                material_findings.append(f)
                sev = str(f.get("severity", "P3"))
                if sev in material_by_severity:
                    material_by_severity[sev] += 1

        material_wolf = [f for f in wolf_pack if not _is_noise_finding(f) and not _is_data_quality_finding(f)]
        material_wolf_p0 = [f for f in material_wolf if f.get("severity") == "P0"][:15]

        # Display names
        display_names: dict[str, str] = {}
        for csn in merged_data:
            display_names[csn] = _clean_display_name(csn)

        # Top 10 material findings per domain (sorted by severity weight desc)
        top_by_domain: dict[str, list[dict[str, Any]]] = {}
        for d in _DOMAIN_AGENTS:
            domain_material = [f for f in material_findings if self._agent_to_domain(str(f.get("agent", ""))) == d]
            domain_material.sort(key=lambda f: -_SEVERITY_WEIGHTS.get(str(f.get("severity", "P3")), 0))
            top_by_domain[d] = domain_material[:10]

        # Material vs noise gaps
        all_gaps_flat: list[dict[str, Any]] = []
        for csn, data in merged_data.items():
            if not isinstance(data, dict):
                continue
            for g in data.get("gaps", []):
                if isinstance(g, dict):
                    all_gaps_flat.append({**g, "_customer": data.get("customer", csn), "_customer_safe_name": csn})
        material_gaps_list = [g for g in all_gaps_flat if not _is_noise_gap(g)]
        noise_gaps_list = [g for g in all_gaps_flat if _is_noise_gap(g)]

        # --- Issue #102: Revenue-at-Risk ---
        revenue_by_customer = self._extract_revenue_from_cross_refs(merged_data)
        total_contracted_arr = sum(revenue_by_customer.values())

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

        # --- Issue #102: Waterfall and treemap ---
        risk_waterfall = self._compute_risk_waterfall(revenue_by_customer, topic_findings)
        # Total exposure = union of unique customers across ALL categories to avoid
        # double-counting when one customer has findings in multiple categories.
        all_at_risk_csns: set[str] = set()
        for cat_data in risk_waterfall.values():
            all_at_risk_csns.update(cat_data.get("customers", []))
        total_risk_exposure = sum(revenue_by_customer.get(csn, 0.0) for csn in all_at_risk_csns)
        risk_adjusted_arr = max(0.0, total_contracted_arr - total_risk_exposure)
        customers_with_revenue = len(revenue_by_customer)
        revenue_data_coverage = customers_with_revenue / len(merged_data) if merged_data else 0.0
        concentration_treemap = self._build_concentration_treemap(
            revenue_by_customer,
            customer_risk_raw,
            display_names,
        )

        # --- Issue #143: Confidence distribution ---
        conf_dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        low_conf_count = 0
        for f in all_findings:
            conf = str(f.get("confidence", "medium")).lower()
            if conf not in conf_dist:
                conf = "medium"
            conf_dist[conf] += 1
            if conf == "low":
                low_conf_count += 1

        # --- Issue #115: SaaS health metrics ---
        saas_metrics = self._compute_saas_metrics(revenue_by_customer, merged_data)

        # --- Wave 1 analyses ---
        # Count recalibrated findings for provenance audit trail
        recalibrated_count = sum(1 for f in all_findings if f.get("_recalibrated_from"))
        provenance_stats = self._compute_provenance_stats(all_findings, recalibrated_count)
        discount_analysis = self._compute_discount_analysis(all_findings)
        renewal_analysis = self._compute_renewal_analysis(all_findings)
        compliance_analysis = self._compute_compliance_analysis(all_findings)
        entity_distribution = self._compute_entity_distribution(all_findings)
        contract_timeline = self._compute_contract_timeline(all_findings)

        # RAG indicators for new analysis sections
        _discount_count = discount_analysis.get("total_pricing_findings", 0)
        section_rag["discount"] = "red" if _discount_count > 10 else ("amber" if _discount_count > 0 else "green")
        _renewal_count = renewal_analysis.get("total_renewal_findings", 0)
        section_rag["renewal"] = "red" if _renewal_count > 10 else ("amber" if _renewal_count > 0 else "green")
        _compliance_count = compliance_analysis.get("total_compliance_findings", 0)
        section_rag["compliance"] = "red" if _compliance_count > 5 else ("amber" if _compliance_count > 0 else "green")
        _entity_count = entity_distribution.get("total_entities_mentioned", 0)
        section_rag["entity"] = "red" if _entity_count > 5 else ("amber" if _entity_count > 0 else "green")
        _timeline_count = contract_timeline.get("expiry_findings_count", 0)
        section_rag["timeline"] = "red" if _timeline_count > 10 else ("amber" if _timeline_count > 0 else "green")

        return ReportComputedData(
            total_findings=total_findings,
            total_gaps=total_gaps,
            total_customers=len(merged_data),
            customers_analyzed=len(merged_data),
            findings_by_severity=severity_counts,
            findings_by_domain=dict(domain_findings_count),
            findings_by_category={k: v for k, v in findings_by_category.items()},
            category_groups={
                d: {
                    cat: [f for f in findings if not _is_data_quality_finding(f)]
                    for cat, findings in cats.items()
                    if any(not _is_data_quality_finding(f) for f in findings)
                }
                for d, cats in category_groups.items()
            },
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
            tfc_findings=topic_findings.get("tfc", []),
            tfc_customers_affected=len({f.get("_customer_safe_name") for f in topic_findings.get("tfc", [])}),
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
            # Rendering overhaul fields
            material_findings=material_findings,
            noise_findings=noise_findings_list,
            material_count=len(material_findings),
            noise_count=len(noise_findings_list),
            data_quality_findings=data_quality_findings_list,
            data_quality_count=len(data_quality_findings_list),
            material_by_severity=material_by_severity,
            material_wolf_pack=material_wolf,
            material_wolf_pack_p0=material_wolf_p0,
            display_names=display_names,
            top_findings_by_domain=top_by_domain,
            material_gaps=material_gaps_list,
            noise_gaps=noise_gaps_list,
            executive_synthesis=executive_synthesis,
            # Issue #102: Revenue-at-Risk
            revenue_by_customer=revenue_by_customer,
            total_contracted_arr=total_contracted_arr,
            risk_adjusted_arr=risk_adjusted_arr,
            revenue_data_coverage=revenue_data_coverage,
            risk_waterfall=risk_waterfall,
            concentration_treemap=concentration_treemap,
            # Issue #143: Confidence Calibration
            confidence_distribution=conf_dist,
            low_confidence_count=low_conf_count,
            # Issue #115: SaaS Health Metrics
            saas_metrics=saas_metrics,
            # Wave 1 analyses
            provenance_stats=provenance_stats,
            discount_analysis=discount_analysis,
            renewal_analysis=renewal_analysis,
            compliance_analysis=compliance_analysis,
            entity_distribution=entity_distribution,
            contract_timeline=contract_timeline,
        )

    # --- Issue #113: Helper methods for business-oriented analysis ---

    @staticmethod
    def _classify_by_topic(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Classify findings into business topic buckets using title/description keywords."""
        topics: dict[str, list[str]] = {
            "coc": [
                "change of control",
                "assignment consent",
                "consent required",
                "consent to assign",
                "assignment restrict",
                "novation",
                "successor",
                "transfer of control",
                "coc ",
            ],
            "tfc": [
                "termination for convenience",
                "terminate without cause",
                "terminate at will",
                "tfc ",
                "convenience termination",
                "non-committed",
                "at-risk arr",
            ],
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

    # --- Issue #102: Revenue-at-Risk helpers ---

    _REVENUE_KEYWORDS: frozenset[str] = frozenset(
        {
            "arr",
            "acv",
            "contract_value",
            "annual_value",
            "revenue",
            "mrr",
            "annual_recurring",
            "total_contract",
            "committed_value",
        }
    )

    @staticmethod
    def _extract_revenue_from_cross_refs(
        merged_data: dict[str, Any],
    ) -> dict[str, float]:
        """Extract per-customer revenue from cross-reference data points.

        Looks for data_point fields containing revenue keywords.
        Prefers reference_value (authoritative) over contract_value.
        Returns ``{customer_safe_name: best_revenue_estimate}``.
        """
        revenue: dict[str, float] = {}
        for csn, data in merged_data.items():
            if not isinstance(data, dict):
                continue
            best = 0.0
            for xr in data.get("cross_references", []):
                if not isinstance(xr, dict):
                    continue
                dp = str(xr.get("data_point", "")).lower().replace(" ", "_")
                if not any(kw in dp for kw in ReportDataComputer._REVENUE_KEYWORDS):
                    continue
                # Prefer reference_value (source of truth) then contract_value
                for field in ("reference_value", "contract_value"):
                    raw = str(xr.get(field, ""))
                    amounts = _extract_dollar_amounts(raw)
                    if amounts:
                        candidate = max(amounts)
                        if candidate > best:
                            best = candidate
                        break  # found a value from this field, stop
            if best > 0:
                revenue[csn] = best
        return revenue

    @staticmethod
    def _compute_risk_waterfall(
        revenue_by_customer: dict[str, float],
        topic_findings: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        """Compute revenue-at-risk waterfall by risk category.

        Each category maps affected customers (via findings) to their revenue.
        Returns ``{category: {"amount": float, "contracts": int, "customers": [str]}}``.
        """
        waterfall: dict[str, dict[str, Any]] = {}

        category_map: dict[str, str] = {
            "coc": "change_of_control",
            "tfc": "termination_for_convenience",
            "concentration": "customer_concentration",
            "pricing": "pricing_risk",
        }

        for topic_key, waterfall_key in category_map.items():
            findings = topic_findings.get(topic_key, [])
            affected_csns: set[str] = set()
            for f in findings:
                csn = f.get("_customer_safe_name", "")
                if csn:
                    affected_csns.add(csn)

            amount = sum(revenue_by_customer.get(csn, 0.0) for csn in affected_csns)
            if amount > 0 or affected_csns:
                waterfall[waterfall_key] = {
                    "amount": amount,
                    "contracts": len(affected_csns),
                    "customers": sorted(affected_csns),
                }

        return waterfall

    @staticmethod
    def _build_concentration_treemap(
        revenue_by_customer: dict[str, float],
        customer_risk_raw: dict[str, dict[str, int]],
        display_names: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Build treemap data sorted by revenue descending.

        Each entry: ``{customer_safe_name, display_name, revenue, pct, risk_level}``.
        """
        total = sum(revenue_by_customer.values())
        if total <= 0:
            return []

        treemap: list[dict[str, Any]] = []
        for csn, rev in revenue_by_customer.items():
            sev = customer_risk_raw.get(csn, {})
            if sev.get("P0", 0) > 0:
                risk = "critical"
            elif sev.get("P1", 0) > 0:
                risk = "high"
            elif sev.get("P2", 0) > 0:
                risk = "medium"
            else:
                risk = "low"
            treemap.append(
                {
                    "customer_safe_name": csn,
                    "display_name": display_names.get(csn, csn),
                    "revenue": rev,
                    "pct": round(rev / total * 100, 1),
                    "risk_level": risk,
                }
            )

        treemap.sort(key=lambda x: -x["revenue"])
        return treemap

    @staticmethod
    def _compute_saas_metrics(
        revenue_by_customer: dict[str, float],
        merged_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute SaaS health metrics from revenue and customer data.

        Returns a dict with: total_customers, customers_with_revenue,
        avg_contract_value, top_customer_pct, tier_distribution.
        """
        total_customers = len(merged_data)
        customers_with_revenue = len(revenue_by_customer)
        total_arr = sum(revenue_by_customer.values())

        avg_cv = total_arr / customers_with_revenue if customers_with_revenue > 0 else 0.0

        # Top customer concentration
        sorted_rev = sorted(revenue_by_customer.values(), reverse=True)
        top_pct = (sorted_rev[0] / total_arr * 100) if sorted_rev and total_arr > 0 else 0.0

        # Tier distribution: Enterprise (>$100K), Mid-Market ($25K-$100K), SMB (<$25K)
        tiers: dict[str, int] = {"Enterprise": 0, "Mid-Market": 0, "SMB": 0}
        for rev in revenue_by_customer.values():
            if rev >= 100_000:
                tiers["Enterprise"] += 1
            elif rev >= 25_000:
                tiers["Mid-Market"] += 1
            else:
                tiers["SMB"] += 1

        return {
            "total_customers": total_customers,
            "customers_with_revenue": customers_with_revenue,
            "avg_contract_value": avg_cv,
            "top_customer_pct": round(top_pct, 1),
            "tier_distribution": tiers,
        }

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
            display = _clean_display_name(csn)
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
            # Collect first P0/P1 finding title as representative issue.
            # Apply recalibration so titles match the recalibrated counts in
            # customer_risk_raw (which was built from recalibrated findings).
            first_p0 = ""
            first_p1 = ""
            for f in findings:
                if not isinstance(f, dict):
                    continue
                rf = ReportDataComputer._recalibrate_severity(f)
                if rf.get("severity") == "P0" and not first_p0:
                    first_p0 = str(rf.get("title", ""))
                if rf.get("severity") == "P1" and not first_p1:
                    first_p1 = str(rf.get("title", ""))
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
            coc_findings_list = topic_findings.get("coc", [])
            coc_customers = len({f.get("_customer_safe_name") for f in coc_findings_list})
            consent_count = sum(
                1
                for f in coc_findings_list
                if "consent" in str(f.get("title", "")).lower() or "consent" in str(f.get("description", "")).lower()
            )
            notification_count = sum(
                1
                for f in coc_findings_list
                if "notification" in str(f.get("title", "")).lower()
                or "notify" in str(f.get("description", "")).lower()
            )
            desc_parts = [f"{coc_count} change-of-control findings across {coc_customers} entities."]
            if consent_count > 0:
                desc_parts.append(
                    f"{consent_count} require consent — initiate outreach to key customers. "
                    "Consider escrow holdback for consent-dependent revenue."
                )
            if notification_count > 0:
                desc_parts.append(f"{notification_count} are notification-only (routine administrative step).")
            if consent_count == 0 and notification_count == 0:
                desc_parts.append("Assess consent requirements and initiate outreach to key customers.")
            recs.append(
                {
                    "timeline": "Pre-Close",
                    "priority": "High",
                    "title": f"Obtain Assignment Consent from {coc_customers} Entities",
                    "description": " ".join(desc_parts),
                }
            )

        # TfC recommendation — valuation concern, not deal-blocker
        tfc_count = len(topic_findings.get("tfc", []))
        if tfc_count > 0:
            tfc_customers = len({f.get("_customer_safe_name") for f in topic_findings.get("tfc", [])})
            recs.append(
                {
                    "timeline": "Valuation",
                    "priority": "Medium",
                    "title": f"Model TfC Revenue Exposure for {tfc_customers} Entities",
                    "description": (
                        "Revenue from TfC contracts is non-committed. Model as at-risk ARR in valuation analysis."
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

        # Executive summary — softened thresholds (Issue #113)
        p0_count = severity_counts.get("P0", 0)
        if p0_count >= 3:
            rag["executive"] = "red"
        elif p0_count > 0 or severity_counts.get("P1", 0) >= 3:
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

        # TfC — valuation concern: amber if present, never red
        tfc = topic_findings.get("tfc", [])
        rag["tfc"] = "amber" if tfc else "green"

        return rag

    # --- Issue #145: Provenance statistics ---

    @staticmethod
    def _compute_provenance_stats(
        all_findings: list[dict[str, Any]],
        recalibrated_count: int,
    ) -> dict[str, Any]:
        """Compute finding provenance statistics for audit trail."""
        total = len(all_findings)
        if total == 0:
            return {
                "total_findings": 0,
                "high_confidence_pct": 0.0,
                "agent_contribution": {},
                "recalibrated_count": 0,
                "domains_covered": [],
            }
        agent_counts: dict[str, int] = defaultdict(int)
        high_conf = 0
        domains: set[str] = set()
        for f in all_findings:
            agent = str(f.get("agent", "unknown")).lower()
            agent_counts[agent] += 1
            domain = ReportDataComputer._agent_to_domain(agent)
            domains.add(domain)
            if str(f.get("confidence", "medium")).lower() == "high":
                high_conf += 1
        return {
            "total_findings": total,
            "high_confidence_pct": round(high_conf / total * 100, 1) if total else 0.0,
            "agent_contribution": dict(agent_counts),
            "recalibrated_count": recalibrated_count,
            "domains_covered": sorted(domains),
        }

    # --- Issue #135: Discount & Pricing Analysis ---

    _DISCOUNT_RE = re.compile(r"(\d{1,3})(?:\.\d+)?%\s*(?:discount|off|reduction|below)", re.IGNORECASE)

    @staticmethod
    def _compute_discount_analysis(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract discount and pricing analysis from findings."""
        pricing_findings: list[dict[str, Any]] = []
        customers_with_discounts: set[str] = set()
        distribution: dict[str, int] = {"0-10%": 0, "10-25%": 0, "25-50%": 0, ">50%": 0}

        pricing_keywords = ["discount", "pricing", "rate card", "price", "below market", "list price"]
        for f in all_findings:
            combined = f"{f.get('title', '')} {f.get('description', '')}".lower()
            if any(kw in combined for kw in pricing_keywords):
                pricing_findings.append(f)
                # Try to extract discount percentage
                matches = ReportDataComputer._DISCOUNT_RE.findall(combined)
                for m in matches:
                    try:
                        pct = int(m)
                    except (ValueError, TypeError):
                        continue
                    csn = f.get("_customer_safe_name", "")
                    if csn:
                        customers_with_discounts.add(csn)
                    if pct <= 10:
                        distribution["0-10%"] += 1
                    elif pct <= 25:
                        distribution["10-25%"] += 1
                    elif pct <= 50:
                        distribution["25-50%"] += 1
                    else:
                        distribution[">50%"] += 1

        return {
            "customers_with_discounts": len(customers_with_discounts),
            "total_pricing_findings": len(pricing_findings),
            "distribution": distribution,
            "findings": pricing_findings[:20],
        }

    # --- Issue #136: Renewal & Contract Expiry Analysis ---

    @staticmethod
    def _compute_renewal_analysis(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze renewal patterns and contract expiry timing."""
        renewal_findings: list[dict[str, Any]] = []
        auto_count = 0
        manual_count = 0
        escalation_count = 0

        renewal_keywords = [
            "renewal",
            "renew",
            "auto-renew",
            "auto_renew",
            "evergreen",
            "expir",
            "term end",
            "contract end",
            "notice period",
        ]
        for f in all_findings:
            combined = f"{f.get('title', '')} {f.get('description', '')}".lower()
            if any(kw in combined for kw in renewal_keywords):
                renewal_findings.append(f)
                if "auto" in combined and "renew" in combined:
                    auto_count += 1
                elif "manual" in combined and "renew" in combined:
                    manual_count += 1
                if "escalat" in combined or "price increase" in combined or "cap" in combined:
                    escalation_count += 1

        return {
            "total_renewal_findings": len(renewal_findings),
            "auto_renew_count": auto_count,
            "manual_renew_count": manual_count,
            "escalation_cap_count": escalation_count,
            "findings": renewal_findings[:20],
        }

    # --- Issue #121: Regulatory & Compliance Risk Assessment ---

    @staticmethod
    def _compute_compliance_analysis(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute regulatory and compliance risk metrics."""
        dpa_keywords = ["dpa", "data processing", "data protection agreement"]
        jurisdiction_keywords = [
            "governing law",
            "jurisdiction",
            "governed by",
            "choice of law",
            "applicable law",
        ]
        regulatory_keywords = [
            "regulatory",
            "compliance",
            "gdpr",
            "ccpa",
            "hipaa",
            "sox",
            "pci",
            "fedramp",
            "sanctions",
            "export control",
            "antitrust",
        ]

        dpa_findings: list[dict[str, Any]] = []
        jurisdiction_findings: list[dict[str, Any]] = []
        regulatory_findings: list[dict[str, Any]] = []
        all_compliance: list[dict[str, Any]] = []

        for f in all_findings:
            combined = f"{f.get('title', '')} {f.get('description', '')}".lower()
            cat = str(f.get("category", "")).lower()
            matched = False
            if any(kw in combined for kw in dpa_keywords) or cat in ("dpa",):
                dpa_findings.append(f)
                matched = True
            if any(kw in combined for kw in jurisdiction_keywords) or cat in ("governing_law",):
                jurisdiction_findings.append(f)
                matched = True
            if any(kw in combined for kw in regulatory_keywords) or cat in ("regulatory",):
                regulatory_findings.append(f)
                matched = True
            if matched:
                all_compliance.append(f)

        return {
            "dpa_findings_count": len(dpa_findings),
            "jurisdiction_findings_count": len(jurisdiction_findings),
            "regulatory_findings_count": len(regulatory_findings),
            "total_compliance_findings": len(all_compliance),
            "findings": all_compliance[:20],
        }

    # --- Issue #137: Legal Entity Distribution ---

    @staticmethod
    def _compute_entity_distribution(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze legal entity distribution from findings."""
        entity_keywords = [
            "legal entity",
            "signing entity",
            "contracting entity",
            "subsidiary",
            "affiliate",
            "parent company",
            "holding company",
            "legacy entity",
            "entity migration",
            "entity consolidation",
            "corporate structure",
            "legal name",
        ]
        entity_findings: list[dict[str, Any]] = []
        entities_mentioned: set[str] = set()

        for f in all_findings:
            combined = f"{f.get('title', '')} {f.get('description', '')}".lower()
            cat = str(f.get("category", "")).lower()
            if (
                any(kw in combined for kw in entity_keywords)
                or "governance" in cat
                or "entity" in cat
                or "corporate_struct" in cat
            ):
                entity_findings.append(f)
                csn = f.get("_customer_safe_name", "")
                if csn:
                    entities_mentioned.add(csn)

        return {
            "total_entities_mentioned": len(entities_mentioned),
            "entity_findings_count": len(entity_findings),
            "findings": entity_findings[:20],
        }

    # --- Issue #147: Contract Date Timeline ---

    _DATE_RE = re.compile(
        r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"
        r"|\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b"
        r"|\b(?:january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s+\d{4}\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _compute_contract_timeline(
        all_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract contract date mentions for timeline visualization."""
        timeline_keywords = [
            "expir",
            "expire",
            "renewal",
            "term end",
            "contract end",
            "effective date",
            "start date",
            "end date",
            "notice period",
            "termination date",
        ]
        timeline_findings: list[dict[str, Any]] = []
        date_count = 0

        for f in all_findings:
            combined = f"{f.get('title', '')} {f.get('description', '')}".lower()
            if any(kw in combined for kw in timeline_keywords):
                timeline_findings.append(f)
                # Count date mentions
                full_text = f"{f.get('title', '')} {f.get('description', '')}"
                matches = ReportDataComputer._DATE_RE.findall(full_text)
                date_count += len(matches)

        return {
            "date_mentions_count": date_count,
            "expiry_findings_count": len(timeline_findings),
            "findings": timeline_findings[:20],
        }
