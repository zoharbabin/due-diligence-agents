"""Pydantic models for agent eval metrics and ground truth definitions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common domain synonym sets for flexible keyword matching
# ---------------------------------------------------------------------------

COMMON_SYNONYMS: dict[str, list[str]] = {
    "terminate": ["cancel", "end", "discontinue", "cease", "rescind", "revoke"],
    "change of control": ["coc", "change in ownership", "acquisition trigger", "ownership change"],
    "assign": ["transfer", "delegate", "convey"],
    "liability": ["damages", "exposure", "loss cap", "liability cap", "limitation of liability"],
    "breach": ["default", "violation", "non-compliance", "failure to perform"],
    "penalty": ["liquidated damages", "service credit", "fee reduction", "credit", "remedies"],
    "encrypt": ["encryption", "encrypted", "cryptographic protection"],
    "MFA": ["multi-factor", "two-factor", "2FA", "multi factor"],
    "revenue": ["income", "earnings", "receipts"],
    "retention": ["storage", "preservation", "archival"],
    "not enforced": ["not required", "not enabled", "not mandatory", "disabled", "optional"],
    "not encrypted": ["unencrypted", "plaintext", "plain text", "not protected"],
    "unpatched": ["unremediated", "not patched", "outstanding", "not remediated", "not addressed"],
    "not updated": ["outdated", "out of date", "stale", "not reviewed", "not revised"],
    "expired": ["lapsed", "no longer valid", "not renewed", "out of date"],
    "delete": ["deletion", "erasure", "removal", "destroy", "purge"],
    "fee": ["charge", "cost", "price", "amount", "payment"],
    "implementation": ["setup", "onboarding", "deployment", "initial"],
    "total": ["aggregate", "sum", "cumulative", "overall", "combined"],
    "late": ["overdue", "past due", "delinquent"],
    "sub-processor": ["sub processor", "subprocessor", "third-party processor", "vendor"],
}

# ---------------------------------------------------------------------------
# Category synonym mapping for flexible category matching
# ---------------------------------------------------------------------------

CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "change_of_control": ["coc", "ownership_change", "acquisition_trigger", "control_change"],
    "termination": ["termination_rights", "contract_termination", "early_termination"],
    "liability": ["liability_cap", "liability_caps", "limitation_of_liability", "liability_limitation", "damages_cap"],
    "ip_ownership": ["intellectual_property", "ip_rights", "ip_assignment", "ip"],
    "data_privacy": ["privacy", "data_protection", "gdpr", "personal_data"],
    "assignment_consent": ["assignment", "assignment_rights", "contract_assignment"],
    "indemnification": ["indemnity", "indemnification_obligations"],
    "confidentiality": ["nda", "non_disclosure", "confidential_information"],
    "compliance_certifications": [
        "compliance_certification",
        "compliance",
        "certification",
        "soc2",
        "soc_2",
        "iso_27001",
        "security_compliance",
    ],
    "access_controls": [
        "access_control",
        "authentication",
        "identity_access",
        "mfa",
        "privileged_access",
        "identity_management",
    ],
    "encryption_standards": [
        "encryption",
        "encryption_standard",
        "data_encryption",
        "cryptography",
        "data_at_rest_encryption",
    ],
    "vulnerability_management": [
        "vulnerability",
        "vulnerabilities",
        "patching",
        "vulnerability_assessment",
        "patch_management",
    ],
    "data_breach_history": [
        "data_breach",
        "breach_history",
        "security_incident",
        "unauthorized_access",
        "breach",
    ],
    "incident_response": [
        "incident_management",
        "incident_response_plan",
        "security_monitoring",
        "irp",
    ],
    "third_party_risk": [
        "vendor_risk",
        "vendor_management",
        "third_party",
        "supply_chain_risk",
        "vendor_security",
    ],
    "network_security": [
        "network_segmentation",
        "firewall",
        "network_access",
        "network_architecture",
        "perimeter_security",
    ],
    "sla_risk": [
        "sla_compliance",
        "service_level",
        "sla",
        "sla_violation",
        "service_level_agreement",
        "uptime",
        "sla_termination_risk",
        "sla_operational_risk",
        "service_credit_exposure",
        "service_credit",
    ],
    "pricing_risk": [
        "pricing",
        "pricing_model",
        "fee_structure",
        "cost_risk",
        "fee_risk",
        "revenue_risk",
        "fee_reduction",
    ],
    "revenue_recognition": [
        "revenue",
        "revenue_analysis",
        "revenue_recognition_risk",
        "asc_606",
        "revenue_treatment",
        "financial_revenue",
        "contract_economics",
        "revenue_schedule",
    ],
    "financial_discrepancy": [
        "fee_discrepancy",
        "financial_inconsistency",
        "calculation_error",
        "financial_analysis",
        "cost_discrepancy",
        "pricing_discrepancy",
        "contract_value",
        "fee_analysis",
        "financial_contract",
        "fee_structure",
        "contract_economics",
        "total_value",
        "revenue_uncertainty",
        "revenue_variance",
        "revenue_exposure",
        "financial_risk",
        "revenue_recognition",
        "revenue_forecasting",
    ],
    "payment_terms": [
        "payment",
        "payment_schedule",
        "payment_conditions",
        "invoicing",
        "billing_terms",
        "late_payment",
    ],
    "data_transfer": [
        "cross_border_transfer",
        "international_transfer",
        "data_flow",
        "cross_border_data",
        "data_export",
        "security_posture",
    ],
    "sub_processor": [
        "sub_processing",
        "subprocessor",
        "sub_processors",
        "third_party_processing",
        "vendor_processing",
    ],
    "data_retention": [
        "data_deletion",
        "retention_policy",
        "data_lifecycle",
        "data_disposal",
        "records_retention",
    ],
    "security_posture": [
        "security_assessment",
        "security_maturity",
        "security_risk",
        "cybersecurity_risk",
        "security_gaps",
    ],
    "renewal_terms": ["renewal", "auto_renewal", "contract_renewal"],
    "non_compete": ["non_competition", "restrictive_covenant", "compete"],
    "warranty": ["warranties", "representation", "representations_warranties"],
    "dispute_resolution": ["arbitration", "dispute", "mediation", "jurisdiction"],
    # HR categories
    "compensation_structure": [
        "compensation",
        "salary",
        "bonus",
        "equity_compensation",
        "stock_options",
        "vesting",
        "pay_structure",
    ],
    "termination_provisions": [
        "termination",
        "severance",
        "notice_period",
        "without_cause",
        "termination_clause",
        "pay_in_lieu",
    ],
    # Tax categories
    "transfer_pricing": [
        "intercompany_pricing",
        "cost_plus",
        "arms_length",
        "royalty_rate",
        "intercompany_transaction",
    ],
    "nol_limitation": [
        "net_operating_loss",
        "section_382",
        "nol",
        "loss_carryforward",
        "tax_loss",
    ],
    "tax_credit_risk": [
        "r_and_d_credit",
        "sred",
        "sr_ed",
        "research_credit",
        "tax_credit",
        "cra_audit",
    ],
    "nexus_exposure": [
        "sales_tax_nexus",
        "wayfair",
        "indirect_tax",
        "state_tax",
        "remote_employee_nexus",
    ],
    "concessionary_rate_risk": [
        "tax_incentive",
        "pioneer_certificate",
        "concessionary_tax",
        "tax_holiday",
        "preferential_rate",
    ],
    # Regulatory categories
    "license_renewal": [
        "license",
        "permit",
        "registration",
        "license_expiry",
        "regulatory_license",
    ],
    "enforcement_action": [
        "consent_order",
        "regulatory_enforcement",
        "fine",
        "penalty",
        "remediation_order",
    ],
    "coc_regulatory_approval": [
        "regulatory_approval",
        "change_of_control_approval",
        "prior_approval",
        "regulatory_consent",
    ],
    "compliance_gap": [
        "regulatory_gap",
        "missing_registration",
        "compliance_deficiency",
        "regulatory_risk",
    ],
    # ESG categories
    "carbon_emissions": [
        "scope_1",
        "scope_2",
        "scope_3",
        "greenhouse_gas",
        "co2",
        "climate_risk",
        "net_zero",
    ],
    "diversity_inclusion": [
        "dei",
        "gender_diversity",
        "board_diversity",
        "inclusion",
        "equity",
        "workforce_diversity",
    ],
    "governance_structure": [
        "board_independence",
        "governance",
        "board_composition",
        "corporate_governance",
        "esg_committee",
    ],
    "esg_reporting": [
        "esg_framework",
        "gri",
        "sasb",
        "tcfd",
        "cdp",
        "sustainability_reporting",
    ],
    "supply_chain_risk": [
        "supplier_risk",
        "supply_chain",
        "supplier_code_of_conduct",
        "labor_standards",
        "vendor_audit",
    ],
    # Cross-domain categories
    "termination_exposure": [
        "termination_risk",
        "tfc_exposure",
        "contract_termination_risk",
        "early_termination_exposure",
        "revenue_at_risk",
    ],
    "contract_enforceability": [
        "enforceability",
        "acceptance_criteria",
        "delivery_acceptance",
        "deemed_accepted",
        "contract_validity",
    ],
    "governing_law": [
        "jurisdiction",
        "choice_of_law",
        "applicable_law",
        "forum_selection",
        "venue",
    ],
    "audit_rights": [
        "audit",
        "audit_clause",
        "usage_audit",
        "compliance_audit",
        "audit_provision",
    ],
    "concentration_risk": [
        "customer_concentration",
        "revenue_concentration",
        "client_concentration",
        "single_customer_risk",
        "dependency_risk",
    ],
    "service_delivery": [
        "service_scope",
        "managed_services",
        "service_description",
        "scope_of_services",
        "deliverables",
    ],
}


# ---------------------------------------------------------------------------
# Three-valued verdict for handling non-determinism
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


# ---------------------------------------------------------------------------
# Ground truth models
# ---------------------------------------------------------------------------


class ExpectedFinding(BaseModel):
    """A single expected finding that the agent should produce."""

    category: str = Field(description="Finding category (e.g. change_of_control, ip_ownership)")
    min_severity: str = Field(default="P3", description="Minimum acceptable severity (inclusive)")
    max_severity: str = Field(default="P0", description="Maximum acceptable severity (inclusive)")
    must_contain_keywords: list[str] = Field(
        default_factory=list, description="Keywords that must appear in title or description"
    )
    keyword_synonyms: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-keyword synonym sets. Key is a keyword from must_contain_keywords, "
        "value is list of acceptable alternatives. Falls back to COMMON_SYNONYMS if empty.",
    )
    citation_must_reference: dict[str, str] = Field(
        default_factory=dict, description="Citation constraints: {'file': '...', 'page_or_section': '...'}"
    )
    required: bool = Field(default=True, description="Whether this finding is required (affects recall)")


class MustNotFind(BaseModel):
    """A finding category that the agent must NOT produce (false positive guard)."""

    category: str = Field(description="Finding category that should not appear")
    reason: str = Field(default="", description="Explanation of why this would be a false positive")


class GroundTruth(BaseModel):
    """Ground truth definition for a single contract-agent pair."""

    contract: str = Field(description="Contract filename (e.g. coc_basic.md)")
    agent: str = Field(description="Agent name (e.g. legal, finance)")
    expected_findings: list[ExpectedFinding] = Field(
        default_factory=list, description="Findings the agent should produce"
    )
    expected_gaps: list[str] = Field(default_factory=list, description="Gap categories the agent should identify")
    must_not_find: list[MustNotFind] = Field(
        default_factory=list, description="Finding categories that must NOT appear"
    )
    tags: list[str] = Field(
        default_factory=lambda: ["golden_path"],
        description="Dataset category tags: golden_path, edge_case, adversarial, regression, cross_domain",
    )
    ambiguity_zone: float = Field(
        default=0.0,
        description="Width of the inconclusive zone around thresholds. "
        "0.0 means strict pass/fail. 0.1 means +/-10% is inconclusive.",
    )
    max_expected_findings: int = Field(
        default=20,
        description="Upper bound on expected finding count. Agent exceeding this is over-producing.",
    )
    min_expected_findings: int = Field(
        default=0,
        description="Lower bound on expected finding count. Agent below this may be under-producing.",
    )


# ---------------------------------------------------------------------------
# Eval metrics
# ---------------------------------------------------------------------------


class AgentEvalMetrics(BaseModel):
    """Computed quality metrics for a single agent eval run."""

    agent_name: str = Field(description="Agent identifier")
    finding_recall: float = Field(default=0.0, description="Fraction of expected findings that were produced")
    finding_precision: float = Field(default=0.0, description="Fraction of produced findings that match expected")
    citation_accuracy: float = Field(
        default=0.0, description="Fraction of matched findings with correct citation references"
    )
    severity_accuracy: float = Field(
        default=0.0, description="Fraction of matched findings with severity in acceptable range"
    )
    false_positive_rate: float = Field(
        default=0.0, description="Fraction of produced findings that are in must_not_find"
    )
    f1_score: float = Field(default=0.0, description="Harmonic mean of precision and recall")
    finding_count: int = Field(default=0, description="Total number of findings produced")


class EvalBaseline(BaseModel):
    """Stored baseline metrics for regression detection."""

    timestamp: str = Field(default="", description="ISO-8601 timestamp when baseline was recorded")
    commit: str = Field(default="", description="Git commit hash when baseline was recorded")
    metrics: dict[str, AgentEvalMetrics] = Field(default_factory=dict, description="Agent name -> metrics mapping")
