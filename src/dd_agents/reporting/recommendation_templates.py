"""Actionable recommendation templates — 99 domain-specific patterns (Issue #200).

Version-controlled, deterministic, auditable. No LLM calls.
Each template: pattern_key, action, owner, timeline, effort, escalation.
Match function: finding title/description keywords → structured recommendation.

Templates organized by domain (9 domains × ~11 patterns each = 99 templates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecommendationTemplate:
    """A single actionable recommendation template."""

    pattern_key: str
    domain: str
    keywords: tuple[str, ...]
    action: str
    owner: str
    timeline: str
    effort: str
    escalation: str


@dataclass(frozen=True)
class MatchedRecommendation:
    """A recommendation matched to a specific finding."""

    finding_title: str
    finding_severity: str
    entity: str
    action: str
    owner: str
    timeline: str
    effort: str
    escalation: str
    domain: str
    pattern_key: str


# ---------------------------------------------------------------------------
# Template library (99 templates, 9 domains × 11 each)
# ---------------------------------------------------------------------------

TEMPLATES: list[RecommendationTemplate] = [
    # === LEGAL (11 templates) ===
    RecommendationTemplate(
        "legal_coc",
        "legal",
        ("change of control", "coc", "assignment consent"),
        "Negotiate assignment consent or waiver from counterparty pre-close",
        "Legal Counsel",
        "Pre-close",
        "Medium",
        "Escrow holdback if unresolved",
    ),
    RecommendationTemplate(
        "legal_ip_assignment",
        "legal",
        ("ip assignment", "invention assignment", "work for hire"),
        "Confirm IP assignment chain; obtain missing assignments from contractors",
        "IP Counsel",
        "Pre-close",
        "High",
        "Price adjustment or indemnity",
    ),
    RecommendationTemplate(
        "legal_termination",
        "legal",
        ("termination for convenience", "tfc", "at-will termination"),
        "Map TfC exposure by revenue impact; negotiate removal or lengthened notice",
        "Commercial Lead",
        "Pre-close",
        "Medium",
        "Revenue holdback",
    ),
    RecommendationTemplate(
        "legal_non_compete",
        "legal",
        ("non-compete", "restrictive covenant", "non-solicitation"),
        "Assess enforceability in applicable jurisdictions; negotiate carve-outs",
        "Legal Counsel",
        "Pre-close",
        "Low",
        "Seller indemnity",
    ),
    RecommendationTemplate(
        "legal_indemnity",
        "legal",
        ("indemnity", "indemnification", "hold harmless"),
        "Verify indemnity caps cover identified exposure; negotiate basket adjustments",
        "M&A Counsel",
        "Pre-close",
        "Medium",
        "Purchase price adjustment",
    ),
    RecommendationTemplate(
        "legal_warranty",
        "legal",
        ("warranty", "representation", "rep and warranty"),
        "Ensure specific rep covers identified risk; add bring-down condition",
        "M&A Counsel",
        "Pre-close",
        "Low",
        "R&W insurance coverage",
    ),
    RecommendationTemplate(
        "legal_litigation",
        "legal",
        ("litigation", "lawsuit", "pending claim", "legal proceeding"),
        "Obtain litigation status update; assess probable outcome and reserve needs",
        "Litigation Counsel",
        "Pre-close",
        "High",
        "Escrow for contingent liability",
    ),
    RecommendationTemplate(
        "legal_regulatory_approval",
        "legal",
        ("regulatory approval", "antitrust", "hsr filing"),
        "File required regulatory notifications; assess timeline risk to close",
        "Regulatory Counsel",
        "Pre-close",
        "High",
        "Walk-away if not clearable",
    ),
    RecommendationTemplate(
        "legal_data_privacy",
        "legal",
        ("gdpr", "privacy", "data protection", "ccpa", "dpa"),
        "Audit data processing agreements; confirm lawful basis for transfers post-close",
        "Privacy Counsel",
        "Post-close 30d",
        "Medium",
        "Remediation plan + budget",
    ),
    RecommendationTemplate(
        "legal_contract_gap",
        "legal",
        ("missing contract", "unsigned", "expired agreement"),
        "Obtain executed copies or confirm renewal; close gap before signing",
        "Legal Operations",
        "Pre-close",
        "Low",
        "Closing condition",
    ),
    RecommendationTemplate(
        "legal_jurisdiction",
        "legal",
        ("governing law", "jurisdiction", "forum selection"),
        "Assess unfavorable jurisdiction risk; negotiate forum selection amendment",
        "Legal Counsel",
        "Post-close 30d",
        "Low",
        "Accept with monitoring",
    ),
    # === FINANCE (11 templates) ===
    RecommendationTemplate(
        "finance_revenue_quality",
        "finance",
        ("revenue recognition", "deferred revenue", "rev rec"),
        "Engage auditors to validate revenue recognition policies; quantify restatement risk",
        "CFO / Audit Partner",
        "Pre-close",
        "High",
        "Purchase price adjustment",
    ),
    RecommendationTemplate(
        "finance_intercompany",
        "finance",
        ("intercompany", "related party", "transfer pricing"),
        "Unwind or eliminate intercompany balances at close; confirm arm's-length pricing",
        "Finance Lead",
        "Pre-close",
        "Medium",
        "Closing adjustment",
    ),
    RecommendationTemplate(
        "finance_working_capital",
        "finance",
        ("working capital", "net working capital", "nwc"),
        "Lock working capital peg with collar; define measurement methodology",
        "CFO",
        "Pre-close",
        "Medium",
        "True-up mechanism",
    ),
    RecommendationTemplate(
        "finance_debt",
        "finance",
        ("debt", "loan", "credit facility", "leverage"),
        "Obtain payoff letters; confirm change-of-control provisions in credit agreements",
        "Treasury",
        "Pre-close",
        "High",
        "Refinancing plan",
    ),
    RecommendationTemplate(
        "finance_accounts_receivable",
        "finance",
        ("accounts receivable", "ar aging", "bad debt"),
        "Validate AR aging; establish reserve for doubtful accounts over 90 days",
        "Controller",
        "Pre-close",
        "Medium",
        "AR warranty/holdback",
    ),
    RecommendationTemplate(
        "finance_tax_liability",
        "finance",
        ("tax liability", "tax exposure", "unpaid tax"),
        "Quantify unrecorded tax liabilities; negotiate seller indemnity for pre-close periods",
        "Tax Advisor",
        "Pre-close",
        "High",
        "Tax indemnity + escrow",
    ),
    RecommendationTemplate(
        "finance_audit_qualification",
        "finance",
        ("audit qualification", "going concern", "material weakness"),
        "Assess root cause of qualification; develop remediation timeline",
        "Audit Committee",
        "Post-close 30d",
        "High",
        "Integration priority",
    ),
    RecommendationTemplate(
        "finance_cash_flow",
        "finance",
        ("cash flow", "burn rate", "runway", "liquidity"),
        "Model cash needs through integration; secure bridge financing if needed",
        "CFO",
        "Pre-close",
        "Medium",
        "Closing condition on minimum cash",
    ),
    RecommendationTemplate(
        "finance_earn_out",
        "finance",
        ("earn-out", "contingent consideration", "milestone payment"),
        "Define earn-out metrics precisely; establish dispute resolution mechanism",
        "M&A Lead",
        "Pre-close",
        "Low",
        "Simplify to fixed payment",
    ),
    RecommendationTemplate(
        "finance_insurance",
        "finance",
        ("insurance", "coverage gap", "underinsured"),
        "Obtain insurance adequacy opinion; bind additional coverage pre-close",
        "Risk Manager",
        "Pre-close",
        "Medium",
        "Buyer arranges coverage",
    ),
    RecommendationTemplate(
        "finance_concentration",
        "finance",
        ("customer concentration", "revenue concentration", "single customer"),
        "Negotiate key customer retention agreements; structure holdback tied to retention",
        "Commercial Lead",
        "Pre-close",
        "High",
        "Revenue holdback",
    ),
    # === COMMERCIAL (11 templates) ===
    RecommendationTemplate(
        "commercial_churn",
        "commercial",
        ("churn", "attrition", "customer loss", "cancellation"),
        "Develop retention plan for at-risk accounts; budget for transition incentives",
        "Customer Success",
        "Post-close 30d",
        "Medium",
        "Revenue guarantee",
    ),
    RecommendationTemplate(
        "commercial_pricing",
        "commercial",
        ("pricing pressure", "margin erosion", "discount"),
        "Audit pricing discipline; implement approval gates for deep discounts",
        "Revenue Operations",
        "Post-close 90d",
        "Low",
        "Pricing policy rollout",
    ),
    RecommendationTemplate(
        "commercial_pipeline",
        "commercial",
        ("pipeline", "funnel", "bookings forecast"),
        "Validate pipeline quality with win-rate analysis; stress-test forecast assumptions",
        "CRO",
        "Pre-close",
        "Medium",
        "Weighted pipeline adjustment",
    ),
    RecommendationTemplate(
        "commercial_competition",
        "commercial",
        ("competitive", "market share", "competitor"),
        "Commission competitive positioning assessment; identify differentiation gaps",
        "Strategy Lead",
        "Post-close 90d",
        "Low",
        "Strategic investment budget",
    ),
    RecommendationTemplate(
        "commercial_contract_value",
        "commercial",
        ("contract value", "tcv", "acv"),
        "Reconcile reported TCV/ACV against signed contracts; resolve discrepancies",
        "Finance",
        "Pre-close",
        "Medium",
        "Purchase price adjustment",
    ),
    RecommendationTemplate(
        "commercial_expansion",
        "commercial",
        ("expansion revenue", "upsell", "cross-sell"),
        "Validate expansion assumptions; confirm product roadmap supports growth thesis",
        "Product/Sales",
        "Post-close 30d",
        "Low",
        "Growth plan documentation",
    ),
    RecommendationTemplate(
        "commercial_partner",
        "commercial",
        ("partner", "channel", "reseller", "distributor"),
        "Review partner agreements for CoC provisions; secure partner transition commitments",
        "Partnerships Lead",
        "Pre-close",
        "Medium",
        "Partner retention incentives",
    ),
    RecommendationTemplate(
        "commercial_market_fit",
        "commercial",
        ("product-market fit", "nps", "satisfaction"),
        "Survey key accounts on satisfaction and future intent; address detractors",
        "Product Marketing",
        "Post-close 30d",
        "Low",
        "Customer advisory board",
    ),
    RecommendationTemplate(
        "commercial_renewal",
        "commercial",
        ("renewal", "renewal rate", "contract expiry"),
        "Map near-term renewals; develop retention playbook for first 90 days",
        "Customer Success",
        "Post-close 30d",
        "Medium",
        "Renewal guarantee holdback",
    ),
    RecommendationTemplate(
        "commercial_dependency",
        "commercial",
        ("vendor dependency", "supplier risk", "sole source"),
        "Identify alternative suppliers; negotiate extended terms with critical vendors",
        "Procurement",
        "Post-close 90d",
        "Medium",
        "Supply continuity clause",
    ),
    RecommendationTemplate(
        "commercial_go_to_market",
        "commercial",
        ("go-to-market", "gtm", "sales model"),
        "Align GTM strategy with buyer's distribution model; plan sales integration",
        "CRO",
        "Post-close 90d",
        "Low",
        "Integration milestone",
    ),
    # === PRODUCTTECH (11 templates) ===
    RecommendationTemplate(
        "tech_debt",
        "producttech",
        ("technical debt", "tech debt", "legacy code"),
        "Quantify remediation cost; budget engineering sprints for critical debt reduction",
        "CTO",
        "Post-close 90d",
        "Medium",
        "Engineering budget allocation",
    ),
    RecommendationTemplate(
        "tech_scalability",
        "producttech",
        ("scalability", "system performance", "capacity", "load performance"),
        "Load-test at 3x current traffic; document scaling bottlenecks and costs",
        "Engineering Lead",
        "Post-close 30d",
        "High",
        "Infrastructure investment",
    ),
    RecommendationTemplate(
        "tech_architecture",
        "producttech",
        ("architecture", "monolith", "microservice"),
        "Assess architecture alignment with buyer's stack; plan migration path",
        "Architecture Lead",
        "Post-close 90d",
        "High",
        "Integration roadmap",
    ),
    RecommendationTemplate(
        "tech_security_vuln",
        "producttech",
        ("vulnerability", "cve", "security flaw", "pen test"),
        "Remediate critical/high CVEs pre-close; establish ongoing patching cadence",
        "Security Team",
        "Pre-close",
        "High",
        "Cybersecurity warranty",
    ),
    RecommendationTemplate(
        "tech_documentation",
        "producttech",
        ("documentation", "undocumented", "tribal knowledge"),
        "Conduct knowledge transfer sessions; document critical systems within 30 days",
        "Engineering Lead",
        "Post-close 30d",
        "Low",
        "Retention of key engineers",
    ),
    RecommendationTemplate(
        "tech_license_compliance",
        "producttech",
        ("license", "open source", "gpl", "oss compliance"),
        "Run license audit; remediate GPL contamination in proprietary modules",
        "Legal + Engineering",
        "Pre-close",
        "High",
        "IP indemnity",
    ),
    RecommendationTemplate(
        "tech_data_migration",
        "producttech",
        ("data migration", "data portability", "data export"),
        "Validate data export capabilities; plan integration data mapping",
        "Data Engineering",
        "Post-close 30d",
        "Medium",
        "Migration budget",
    ),
    RecommendationTemplate(
        "tech_uptime",
        "producttech",
        ("uptime", "sla", "availability", "downtime"),
        "Review SLA commitments against actual performance; plan reliability investments",
        "SRE/DevOps",
        "Post-close 30d",
        "Medium",
        "SLA penalty reserve",
    ),
    RecommendationTemplate(
        "tech_key_person",
        "producttech",
        ("key person", "bus factor", "single point of failure"),
        "Identify single-threaded systems; cross-train or hire backup before key-person risk",
        "Engineering Manager",
        "Post-close 30d",
        "High",
        "Retention packages",
    ),
    RecommendationTemplate(
        "tech_api",
        "producttech",
        ("api", "integration", "compatibility", "breaking change"),
        "Audit public API stability; develop deprecation and versioning strategy",
        "Platform Team",
        "Post-close 90d",
        "Low",
        "API stability commitment",
    ),
    RecommendationTemplate(
        "tech_ci_cd",
        "producttech",
        ("ci/cd", "deployment", "release process", "devops"),
        "Assess deployment maturity; align with buyer's DevOps standards",
        "DevOps Lead",
        "Post-close 90d",
        "Low",
        "Tooling standardization budget",
    ),
    # === CYBERSECURITY (11 templates) ===
    RecommendationTemplate(
        "cyber_breach",
        "cybersecurity",
        ("breach", "incident", "data leak", "unauthorized access"),
        "Conduct forensic investigation; assess notification obligations and exposure",
        "CISO",
        "Pre-close",
        "High",
        "Material adverse effect clause",
    ),
    RecommendationTemplate(
        "cyber_encryption",
        "cybersecurity",
        ("encryption", "unencrypted", "plaintext", "at-rest"),
        "Implement encryption for data at rest and in transit; timeline 30-day remediation",
        "Security Engineering",
        "Post-close 30d",
        "Medium",
        "Cybersecurity budget",
    ),
    RecommendationTemplate(
        "cyber_access_control",
        "cybersecurity",
        ("access control", "mfa", "privileged access", "admin account", "admin privileges"),
        "Enforce MFA for all privileged accounts; implement least-privilege model",
        "Security Operations",
        "Post-close 30d",
        "Medium",
        "Compliance requirement",
    ),
    RecommendationTemplate(
        "cyber_compliance_gap",
        "cybersecurity",
        ("soc 2", "iso 27001", "compliance gap", "audit finding"),
        "Develop compliance roadmap; engage auditor for gap remediation timeline",
        "Compliance Lead",
        "Post-close 90d",
        "Medium",
        "Compliance investment",
    ),
    RecommendationTemplate(
        "cyber_endpoint",
        "cybersecurity",
        ("endpoint", "edr", "antivirus", "malware"),
        "Deploy EDR across all endpoints; establish 24/7 monitoring capability",
        "Security Operations",
        "Post-close 30d",
        "Medium",
        "Security budget",
    ),
    RecommendationTemplate(
        "cyber_patch_mgmt",
        "cybersecurity",
        ("patch", "unpatched", "outdated", "end of life"),
        "Remediate critical patches within 14 days; establish patch SLA policy",
        "IT Operations",
        "Post-close 30d",
        "High",
        "Vulnerability SLA",
    ),
    RecommendationTemplate(
        "cyber_backup",
        "cybersecurity",
        ("backup", "disaster recovery", "business continuity"),
        "Validate backup integrity and recovery time; conduct DR test",
        "IT Operations",
        "Post-close 30d",
        "Medium",
        "BCP investment",
    ),
    RecommendationTemplate(
        "cyber_third_party",
        "cybersecurity",
        ("third-party risk", "vendor security", "supply chain"),
        "Assess critical vendor security posture; implement vendor risk management program",
        "Security GRC",
        "Post-close 90d",
        "Low",
        "Vendor audit program",
    ),
    RecommendationTemplate(
        "cyber_logging",
        "cybersecurity",
        ("logging", "monitoring", "siem", "audit trail"),
        "Implement centralized logging; ensure 12-month retention for compliance",
        "Security Engineering",
        "Post-close 30d",
        "Medium",
        "SIEM investment",
    ),
    RecommendationTemplate(
        "cyber_network",
        "cybersecurity",
        ("network segmentation", "firewall", "lateral movement"),
        "Implement network segmentation for critical systems; restrict lateral movement",
        "Network Security",
        "Post-close 90d",
        "Medium",
        "Network investment",
    ),
    RecommendationTemplate(
        "cyber_awareness",
        "cybersecurity",
        ("phishing", "social engineering", "security training"),
        "Deploy security awareness training; establish phishing simulation program",
        "Security Operations",
        "Post-close 90d",
        "Low",
        "Training budget",
    ),
    # === HR (11 templates) ===
    RecommendationTemplate(
        "hr_key_retention",
        "hr",
        ("key employee", "retention", "flight risk"),
        "Offer retention packages to identified key personnel; vest over 24 months",
        "CHRO",
        "Pre-close",
        "High",
        "Retention escrow",
    ),
    RecommendationTemplate(
        "hr_compensation",
        "hr",
        ("compensation", "pay equity", "salary", "benefits"),
        "Conduct compensation benchmarking; develop harmonization plan",
        "Total Rewards",
        "Post-close 90d",
        "Medium",
        "Compensation budget",
    ),
    RecommendationTemplate(
        "hr_employment_compliance",
        "hr",
        ("employment law", "labor compliance", "misclassification"),
        "Audit worker classification; remediate any independent contractor misclassification",
        "Employment Counsel",
        "Pre-close",
        "High",
        "Seller indemnity",
    ),
    RecommendationTemplate(
        "hr_severance",
        "hr",
        ("severance", "redundancy", "restructuring"),
        "Model severance costs for planned restructuring; budget integration synergies",
        "HR Operations",
        "Pre-close",
        "Medium",
        "Restructuring reserve",
    ),
    RecommendationTemplate(
        "hr_culture",
        "hr",
        ("culture", "integration", "morale", "engagement"),
        "Plan cultural integration program; appoint integration champion",
        "CHRO",
        "Post-close 30d",
        "Low",
        "Integration budget",
    ),
    RecommendationTemplate(
        "hr_union",
        "hr",
        ("union", "collective bargaining", "works council"),
        "Consult with employee representatives per legal requirements; plan communication",
        "Employee Relations",
        "Pre-close",
        "Medium",
        "Legal obligation",
    ),
    RecommendationTemplate(
        "hr_org_structure",
        "hr",
        ("organization structure", "reporting", "headcount"),
        "Define Day 1 reporting structure; communicate to both organizations pre-close",
        "Integration PMO",
        "Pre-close",
        "Medium",
        "Day 1 readiness",
    ),
    RecommendationTemplate(
        "hr_training",
        "hr",
        ("training", "onboarding", "skill gap"),
        "Assess skill gaps for combined entity; budget for upskilling programs",
        "L&D Lead",
        "Post-close 90d",
        "Low",
        "Training investment",
    ),
    RecommendationTemplate(
        "hr_benefits",
        "hr",
        ("benefits", "pension", "health insurance", "401k"),
        "Compare benefit programs; develop harmonization plan with transition period",
        "Total Rewards",
        "Post-close 90d",
        "Medium",
        "Benefits equalization budget",
    ),
    RecommendationTemplate(
        "hr_non_compete_employee",
        "hr",
        ("non-compete", "garden leave", "restrictive"),
        "Inventory employee restrictive covenants; assess enforceability post-close",
        "Employment Counsel",
        "Pre-close",
        "Low",
        "Accept with monitoring",
    ),
    RecommendationTemplate(
        "hr_visa",
        "hr",
        ("visa", "work permit", "immigration", "h1b"),
        "Audit immigration status of key personnel; plan transfer petitions",
        "Immigration Counsel",
        "Pre-close",
        "Medium",
        "Immigration counsel budget",
    ),
    # === TAX (11 templates) ===
    RecommendationTemplate(
        "tax_structure",
        "tax",
        ("tax structure", "entity structure", "holding"),
        "Optimize post-close entity structure; assess step-up opportunities",
        "Tax Advisor",
        "Pre-close",
        "Medium",
        "Structure advisory fee",
    ),
    RecommendationTemplate(
        "tax_transfer_pricing",
        "tax",
        ("transfer pricing", "arm's length", "intercompany pricing"),
        "Validate transfer pricing documentation; prepare contemporaneous documentation",
        "Transfer Pricing Advisor",
        "Pre-close",
        "High",
        "TP adjustment risk",
    ),
    RecommendationTemplate(
        "tax_nol",
        "tax",
        ("net operating loss", "nol", "tax attribute", "carryforward"),
        "Model Section 382 limitation impact; quantify usable NOL post-close",
        "Tax Advisor",
        "Pre-close",
        "Medium",
        "Valuation adjustment",
    ),
    RecommendationTemplate(
        "tax_vat",
        "tax",
        ("vat", "sales tax", "indirect tax", "nexus"),
        "Audit indirect tax compliance; register in jurisdictions with nexus",
        "Indirect Tax Lead",
        "Post-close 30d",
        "Medium",
        "Compliance budget",
    ),
    RecommendationTemplate(
        "tax_withholding",
        "tax",
        ("withholding", "payroll tax", "employment tax"),
        "Verify payroll tax compliance; remediate any under-withholding",
        "Payroll",
        "Pre-close",
        "Medium",
        "Seller indemnity",
    ),
    RecommendationTemplate(
        "tax_audit_risk",
        "tax",
        ("tax audit", "tax examination", "irs", "revenue authority"),
        "Assess open audit exposure; negotiate seller indemnity for pre-close periods",
        "Tax Counsel",
        "Pre-close",
        "High",
        "Tax indemnity + escrow",
    ),
    RecommendationTemplate(
        "tax_credits",
        "tax",
        ("tax credit", "r&d credit", "incentive"),
        "Validate R&D credit methodology; assess sustainability post-acquisition",
        "Tax Advisor",
        "Pre-close",
        "Low",
        "Credit recapture risk",
    ),
    RecommendationTemplate(
        "tax_international",
        "tax",
        ("international tax", "repatriation", "pillar two", "beps"),
        "Model Pillar Two impact; assess GILTI/BEAT exposure post-restructure",
        "International Tax",
        "Pre-close",
        "High",
        "Advisory engagement",
    ),
    RecommendationTemplate(
        "tax_state_local",
        "tax",
        ("state tax", "local tax", "apportionment"),
        "Review state apportionment methodology; validate nexus positions",
        "SALT Advisor",
        "Post-close 30d",
        "Low",
        "SALT compliance review",
    ),
    RecommendationTemplate(
        "tax_stamp_duty",
        "tax",
        ("stamp duty", "transfer tax", "transaction tax"),
        "Calculate transfer/stamp duties; budget for transaction tax costs",
        "Tax Advisor",
        "Pre-close",
        "Low",
        "Transaction cost budget",
    ),
    RecommendationTemplate(
        "tax_deferred",
        "tax",
        ("deferred tax", "dta", "valuation allowance"),
        "Assess realizability of deferred tax assets; model post-close reversals",
        "Tax Advisor",
        "Pre-close",
        "Medium",
        "Valuation adjustment",
    ),
    # === REGULATORY (11 templates) ===
    RecommendationTemplate(
        "reg_license",
        "regulatory",
        ("license", "permit", "authorization", "registration"),
        "Inventory all licenses; confirm transferability or re-application requirements",
        "Regulatory Affairs",
        "Pre-close",
        "High",
        "Closing condition",
    ),
    RecommendationTemplate(
        "reg_sanctions",
        "regulatory",
        ("sanctions", "restricted party", "export control", "ofac"),
        "Screen all counterparties against sanctions lists; remediate any matches",
        "Compliance",
        "Pre-close",
        "High",
        "Walk-away if unresolvable",
    ),
    RecommendationTemplate(
        "reg_environmental",
        "regulatory",
        ("environmental", "contamination", "epa", "remediation"),
        "Commission Phase I/II environmental assessment; quantify remediation costs",
        "Environmental Counsel",
        "Pre-close",
        "High",
        "Environmental indemnity",
    ),
    RecommendationTemplate(
        "reg_industry_specific",
        "regulatory",
        ("fda", "fcc", "finra", "sec filing"),
        "Confirm industry-specific compliance; assess pending regulatory actions",
        "Regulatory Counsel",
        "Pre-close",
        "High",
        "Regulatory warranty",
    ),
    RecommendationTemplate(
        "reg_reporting",
        "regulatory",
        ("reporting obligation", "filing requirement", "disclosure"),
        "Map post-close reporting obligations; calendar critical filing deadlines",
        "Compliance Lead",
        "Post-close 30d",
        "Low",
        "Compliance calendar",
    ),
    RecommendationTemplate(
        "reg_consent",
        "regulatory",
        ("regulatory consent", "government approval", "foreign investment"),
        "File required pre-close regulatory consents; assess timeline to approval",
        "Government Affairs",
        "Pre-close",
        "High",
        "Walk-away right",
    ),
    RecommendationTemplate(
        "reg_data_localization",
        "regulatory",
        ("data localization", "data residency", "sovereignty"),
        "Audit data storage locations; plan migration for non-compliant systems",
        "Infrastructure Lead",
        "Post-close 90d",
        "Medium",
        "Migration budget",
    ),
    RecommendationTemplate(
        "reg_anti_corruption",
        "regulatory",
        ("anti-corruption", "fcpa", "bribery", "anti-bribery"),
        "Conduct anti-corruption risk assessment; enhance ABC compliance program",
        "Compliance",
        "Post-close 30d",
        "Medium",
        "Compliance investment",
    ),
    RecommendationTemplate(
        "reg_competition",
        "regulatory",
        ("competition law", "market dominance", "merger control"),
        "Assess merger control filing requirements; prepare market share analysis",
        "Antitrust Counsel",
        "Pre-close",
        "High",
        "Regulatory risk",
    ),
    RecommendationTemplate(
        "reg_consumer_protection",
        "regulatory",
        ("consumer protection", "unfair practices", "ftc"),
        "Review marketing claims and practices; remediate non-compliant materials",
        "Legal/Marketing",
        "Post-close 30d",
        "Low",
        "Compliance review",
    ),
    RecommendationTemplate(
        "reg_healthcare",
        "regulatory",
        ("hipaa", "healthcare", "phi", "patient data"),
        "Conduct HIPAA compliance assessment; remediate identified gaps",
        "Privacy Officer",
        "Post-close 30d",
        "High",
        "HIPAA compliance budget",
    ),
    # === ESG (11 templates) ===
    RecommendationTemplate(
        "esg_carbon",
        "esg",
        ("carbon", "emissions", "climate", "net zero", "ghg"),
        "Baseline Scope 1/2/3 emissions; develop transition plan aligned with targets",
        "Sustainability Lead",
        "Post-close 90d",
        "Medium",
        "ESG investment",
    ),
    RecommendationTemplate(
        "esg_supply_chain",
        "esg",
        ("supply chain", "forced labor", "modern slavery"),
        "Audit supply chain for forced labor indicators; implement due diligence program",
        "Procurement/ESG",
        "Post-close 90d",
        "High",
        "Supply chain program",
    ),
    RecommendationTemplate(
        "esg_diversity",
        "esg",
        ("diversity", "dei", "inclusion", "gender gap"),
        "Assess workforce diversity metrics; develop inclusion integration plan",
        "CHRO/DEI Lead",
        "Post-close 90d",
        "Low",
        "DEI program budget",
    ),
    RecommendationTemplate(
        "esg_governance_board",
        "esg",
        ("board composition", "governance", "independent director"),
        "Align board composition with buyer governance standards; plan transition",
        "General Counsel",
        "Post-close 30d",
        "Low",
        "Governance alignment",
    ),
    RecommendationTemplate(
        "esg_waste",
        "esg",
        ("waste", "circular economy", "recycling", "disposal"),
        "Audit waste management practices; assess regulatory compliance",
        "Operations/ESG",
        "Post-close 90d",
        "Low",
        "Environmental compliance",
    ),
    RecommendationTemplate(
        "esg_health_safety",
        "esg",
        ("health and safety", "osha", "workplace safety", "incident rate"),
        "Review safety record and near-misses; align with buyer's HSE standards",
        "HSE Lead",
        "Post-close 30d",
        "Medium",
        "Safety investment",
    ),
    RecommendationTemplate(
        "esg_community",
        "esg",
        ("community impact", "stakeholder", "social license"),
        "Map community stakeholders; develop engagement plan for integration period",
        "Public Affairs",
        "Post-close 90d",
        "Low",
        "Community budget",
    ),
    RecommendationTemplate(
        "esg_reporting_standard",
        "esg",
        ("esg reporting", "sustainability report", "csrd", "tcfd"),
        "Gap-assess against buyer's ESG reporting framework; plan alignment",
        "Sustainability Lead",
        "Post-close 90d",
        "Medium",
        "Reporting alignment",
    ),
    RecommendationTemplate(
        "esg_biodiversity",
        "esg",
        ("biodiversity", "natural capital", "ecosystem"),
        "Screen operations for biodiversity risk; assess TNFD alignment requirements",
        "Environmental Lead",
        "Post-close 90d",
        "Low",
        "Assessment budget",
    ),
    RecommendationTemplate(
        "esg_water",
        "esg",
        ("water", "water stress", "effluent", "water risk"),
        "Assess water usage and stress exposure; implement monitoring program",
        "Operations/ESG",
        "Post-close 90d",
        "Low",
        "Monitoring program",
    ),
    RecommendationTemplate(
        "esg_human_rights",
        "esg",
        ("human rights", "labor rights", "child labor"),
        "Conduct human rights impact assessment; implement grievance mechanism",
        "Legal/ESG",
        "Post-close 90d",
        "Medium",
        "HRDD program",
    ),
]


# ---------------------------------------------------------------------------
# Matching engine
# ---------------------------------------------------------------------------


def match_recommendation(
    finding: dict[str, Any] | None,
    domain: str = "",
) -> MatchedRecommendation | None:
    """Match a finding to the best recommendation template.

    Matching: domain-first (narrows to ~11 templates), then keyword overlap.
    Same-domain templates win ties over cross-domain matches.
    Returns None if no template matches with at least one keyword.
    """
    if not isinstance(finding, dict):
        return None

    title = str(finding.get("title", "")).lower()
    description = str(finding.get("description", "")).lower()
    text = f"{title} {description}"
    agent = str(finding.get("agent", "")).lower()
    effective_domain = domain or agent

    best: RecommendationTemplate | None = None
    best_score = 0
    best_is_same_domain = False

    for tmpl in TEMPLATES:
        domain_match = tmpl.domain == effective_domain
        score = 0
        for kw in tmpl.keywords:
            if kw in text:
                score += 2 if domain_match else 1

        if score > best_score or (score == best_score and score > 0 and domain_match and not best_is_same_domain):
            best_score = score
            best = tmpl
            best_is_same_domain = domain_match

    if best is None or best_score == 0:
        return None

    severity = str(finding.get("severity", "P3"))
    entity = str(finding.get("_subject_safe_name", finding.get("entity", "")))

    return MatchedRecommendation(
        finding_title=str(finding.get("title", "")),
        finding_severity=severity,
        entity=entity,
        action=best.action,
        owner=best.owner,
        timeline=best.timeline,
        effort=best.effort,
        escalation=best.escalation,
        domain=best.domain,
        pattern_key=best.pattern_key,
    )


def generate_recommendations(
    material_findings: list[dict[str, Any]],
    max_items: int = 30,
) -> list[MatchedRecommendation]:
    """Generate de-duplicated actionable recommendations for material findings.

    All severities matched via keyword overlap; P0/P1 processed first.
    De-duplication: one recommendation per pattern_key.
    """
    seen_patterns: set[str] = set()
    results: list[MatchedRecommendation] = []

    # Sort by severity (P0 first)
    severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    sorted_findings = sorted(
        material_findings,
        key=lambda f: severity_order.get(str(f.get("severity", "P3")), 3),
    )

    for finding in sorted_findings:
        if len(results) >= max_items:
            break

        rec = match_recommendation(finding)
        if rec is None:
            continue

        if rec.pattern_key in seen_patterns:
            continue

        seen_patterns.add(rec.pattern_key)
        results.append(rec)

    return results
