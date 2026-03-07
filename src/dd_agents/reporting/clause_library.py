"""Contract clause taxonomy and classification (Issue #119, Phase 1).

Defines canonical clause types with risk implications and market norms.
Maps agent findings to clause taxonomy for standardized reporting.
"""

from __future__ import annotations

from typing import Any, TypedDict


class ClauseType(TypedDict):
    """Canonical clause type definition."""

    name: str
    category: str
    domain: str
    risk_implications: str
    market_norm: str
    keywords: list[str]


def _ct(
    name: str,
    category: str,
    domain: str,
    risk: str,
    norm: str,
    keywords: list[str],
) -> ClauseType:
    return ClauseType(
        name=name,
        category=category,
        domain=domain,
        risk_implications=risk,
        market_norm=norm,
        keywords=keywords,
    )


CLAUSE_LIBRARY: dict[str, ClauseType] = {
    "change_of_control": _ct(
        "Change of Control",
        "governance",
        "legal",
        "May trigger consent requirements, termination rights, or automatic termination upon acquisition.",
        "Most enterprise contracts include CoC clauses. Consent-required with 30-60 day cure is standard.",
        ["change of control", "change in control", "coc", "acquisition trigger", "merger trigger"],
    ),
    "termination_for_convenience": _ct(
        "Termination for Convenience",
        "termination",
        "legal",
        "Allows counterparty to exit without cause. Affects revenue quality and committed ARR calculations.",
        "Common in enterprise SaaS. 30-90 day notice period is standard. TfC with <30 day notice is non-standard.",
        ["termination for convenience", "terminate without cause", "terminate at will", "tfc"],
    ),
    "termination_for_cause": _ct(
        "Termination for Cause",
        "termination",
        "legal",
        "Standard protective clause. Risk increases with broad or subjective cause definitions.",
        "Universal in commercial contracts. 30-day cure period for material breach is standard.",
        ["termination for cause", "material breach", "default", "cure period"],
    ),
    "anti_assignment": _ct(
        "Anti-Assignment",
        "governance",
        "legal",
        "May block assignment of contracts to acquirer post-close without counterparty consent.",
        "Most contracts restrict assignment without consent but include carve-outs for affiliates or mergers.",
        ["assignment", "anti-assignment", "non-assignable", "transfer of rights", "successor"],
    ),
    "liability_cap": _ct(
        "Liability Cap",
        "risk_allocation",
        "legal",
        "Caps limit financial exposure. Asymmetric caps or missing carve-outs for IP breaches increase risk.",
        "Cap at 12-24 months of fees paid is standard. Mutual caps are preferred.",
        ["liability cap", "limitation of liability", "aggregate liability", "maximum liability", "cap on damages"],
    ),
    "indemnification": _ct(
        "Indemnification",
        "risk_allocation",
        "legal",
        "Defines who bears loss for third-party claims or IP infringement. Inadequate indemnity shifts risk.",
        "Mutual indemnification for IP infringement and confidentiality breach is standard.",
        ["indemnif", "hold harmless", "defend and indemnify", "third-party claim"],
    ),
    "mfn": _ct(
        "Most Favored Nation",
        "pricing",
        "commercial",
        "MFN clauses constrain pricing flexibility and may require retroactive price adjustments.",
        "Uncommon in standard SaaS. More frequent in enterprise or government contracts.",
        ["most favored nation", "mfn", "most favored customer", "price parity", "best price"],
    ),
    "exclusivity": _ct(
        "Exclusivity",
        "commercial",
        "commercial",
        "Grants exclusive rights within a scope, limiting ability to serve competing customers.",
        "Exclusivity is uncommon in SaaS. Should be time-limited and narrowly scoped.",
        ["exclusive", "exclusivity", "sole provider", "sole supplier", "exclusive license"],
    ),
    "non_compete": _ct(
        "Non-Compete",
        "restrictive_covenant",
        "legal",
        "May restrict acquirer's ability to compete in certain markets or hire key personnel post-close.",
        "Should be reasonable in scope. 1-2 year duration is standard. Overly broad may be unenforceable.",
        ["non-compete", "non compete", "noncompete", "restriction on competition", "covenant not to compete"],
    ),
    "ip_ownership": _ct(
        "IP Ownership",
        "intellectual_property",
        "legal",
        "Unclear IP ownership can undermine the core asset. Work-for-hire and joint ownership create complexity.",
        "Clear assignment of all work product to hiring party is standard. Joint ownership is risky.",
        ["ip ownership", "intellectual property", "work for hire", "work product", "assignment of invention"],
    ),
    "data_privacy": _ct(
        "Data Privacy & DPA",
        "compliance",
        "producttech",
        "Missing or inadequate DPAs create regulatory exposure. Cross-border transfer issues affect operations.",
        "DPA required for all EU personal data processing. SCCs or adequacy decisions for cross-border transfers.",
        ["data processing", "dpa", "gdpr", "personal data", "data protection", "data privacy", "subprocessor"],
    ),
    "insurance": _ct(
        "Insurance Requirements",
        "risk_allocation",
        "finance",
        "Contractual insurance requirements may be costly. Gaps in coverage create liability exposure.",
        "General liability, E&O, and cyber insurance are standard. Policy limits vary by contract value.",
        ["insurance", "cyber insurance", "professional liability", "errors and omissions", "policy limits"],
    ),
    "warranty": _ct(
        "Warranty",
        "risk_allocation",
        "legal",
        "Broad warranties increase exposure. Extended periods or uncapped remedies create ongoing liability.",
        "Limited warranty for conformance to specs. 12-month period "
        "is standard. Disclaimer of implied warranties is common.",
        ["warranty", "warrant", "representation", "fitness for purpose", "merchantability"],
    ),
    "force_majeure": _ct(
        "Force Majeure",
        "risk_allocation",
        "legal",
        "Defines relief from obligations due to extraordinary events. "
        "Overly broad clauses may excuse common disruptions.",
        "Standard in enterprise contracts. Should include specific trigger events, notice requirements.",
        ["force majeure", "act of god", "extraordinary event", "pandemic", "unforeseeable"],
    ),
    "governing_law": _ct(
        "Governing Law & Jurisdiction",
        "governance",
        "legal",
        "Unfavorable jurisdiction increases litigation cost. Multiple governing laws create complexity.",
        "Governing law typically matches vendor's primary jurisdiction. Arbitration is common internationally.",
        ["governing law", "jurisdiction", "venue", "arbitration", "dispute resolution", "applicable law"],
    ),
    "renewal": _ct(
        "Renewal & Auto-Renewal",
        "commercial",
        "commercial",
        "Auto-renewal provides revenue predictability. Manual renewal with short notice creates churn risk.",
        "Auto-renewal with 30-90 day opt-out is standard in SaaS. 3-5% annual escalation caps are common.",
        ["renewal", "auto-renew", "evergreen", "renewal term", "opt-out", "notice of non-renewal"],
    ),
    "sla": _ct(
        "Service Level Agreement",
        "performance",
        "commercial",
        "Aggressive SLAs with uncapped service credits create financial exposure.",
        "99.5-99.9% uptime for SaaS. Service credits capped at 10-30% of monthly fees.",
        ["sla", "service level", "uptime", "availability", "service credit", "performance guarantee"],
    ),
    "confidentiality": _ct(
        "Confidentiality & NDA",
        "information_protection",
        "legal",
        "Missing or expired NDAs create information security risk. Broad carve-outs may expose sensitive data.",
        "Mutual NDA with 2-5 year term is standard. Carve-outs for independently developed information are expected.",
        ["confidential", "nda", "non-disclosure", "proprietary information", "trade secret"],
    ),
}


def classify_finding(finding: dict[str, Any]) -> str | None:
    """Map a finding to a clause type using category and keyword matching.

    Returns the clause type key (e.g. ``"change_of_control"``) or ``None``
    if the finding doesn't match any known clause type.
    """
    cat = str(finding.get("category", "")).lower().replace(" ", "_")
    title = str(finding.get("title", "")).lower()
    desc = str(finding.get("description", "")).lower()
    combined = f"{title} {desc}"

    # Direct category match
    if cat in CLAUSE_LIBRARY:
        return cat

    # Keyword-based matching
    for clause_key, clause_def in CLAUSE_LIBRARY.items():
        for kw in clause_def["keywords"]:
            if kw in combined or kw in cat:
                return clause_key

    return None


def get_clause_context(clause_type: str) -> dict[str, str]:
    """Return market norm and risk implications for a clause type.

    Raises ``KeyError`` if *clause_type* is not in the library.
    """
    clause = CLAUSE_LIBRARY[clause_type]
    return {
        "name": clause["name"],
        "market_norm": clause["market_norm"],
        "risk_implications": clause["risk_implications"],
        "domain": clause["domain"],
        "category": clause["category"],
    }


def list_clause_types() -> list[str]:
    """Return all known clause type keys."""
    return list(CLAUSE_LIBRARY.keys())
