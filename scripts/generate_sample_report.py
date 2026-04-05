#!/usr/bin/env python3
"""Generate a realistic sample HTML report for GitHub Pages demo.

Usage:
    python scripts/generate_sample_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path so we can import dd_agents
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dd_agents.reporting.html import HTMLReportGenerator


def _make_sample_data() -> dict[str, object]:
    """Build realistic multi-customer merged data for demo purposes.

    All names, figures, and clauses are entirely fictional.
    """
    return {
        "novabridge_software": {
            "customer": "NovaBridge Software",
            "findings": [
                {
                    "severity": "P0",
                    "title": "Change of control triggers immediate termination",
                    "description": (
                        "Section 14.2 of the MSA grants NovaBridge the right to terminate "
                        "the agreement immediately upon any change of control of the Provider, "
                        "with no cure period. This affects $2.4M in annual recurring revenue "
                        "and could result in complete revenue loss from this customer post-close."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "change_of_control",
                    "citations": [
                        {
                            "source_path": "NovaBridge/MSA_2023.pdf",
                            "location": "Section 14.2, page 8",
                            "exact_quote": (
                                "Upon any Change of Control of Provider, Customer may terminate "
                                "this Agreement immediately upon written notice without penalty."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P0",
                    "title": "IP assignment clause missing for custom integrations",
                    "description": (
                        "Three custom integration modules were developed for NovaBridge under "
                        "SOW-2024-003 but the SOW lacks an IP assignment clause. Work product "
                        "ownership defaults to the developer under applicable law, creating "
                        "ambiguity about who owns the integration code post-acquisition."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "ip_ownership",
                    "citations": [
                        {
                            "source_path": "NovaBridge/SOW_2024_003.pdf",
                            "location": "Section 4, page 2",
                            "exact_quote": (
                                "Provider shall deliver the Custom Integration Modules described "
                                "in Exhibit A within 90 days of the Effective Date."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P1",
                    "title": "Revenue recognition timing mismatch",
                    "description": (
                        "Contract specifies quarterly billing in advance, but financial records "
                        "show monthly revenue recognition. The $600K quarterly prepayment is "
                        "recognized as $200K/month, which is appropriate under ASC 606, but the "
                        "deferred revenue balance of $400K at any given time represents a "
                        "liability that must be carried through the acquisition."
                    ),
                    "agent": "finance",
                    "confidence": "high",
                    "category": "revenue_recognition",
                    "citations": [
                        {
                            "source_path": "NovaBridge/Order_Form_2024.pdf",
                            "location": "Section 3, page 1",
                            "exact_quote": "Annual License Fee: $2,400,000, payable quarterly in advance.",
                        }
                    ],
                },
                {
                    "severity": "P1",
                    "title": "Auto-renewal with 120-day notice period",
                    "description": (
                        "Agreement auto-renews for successive 1-year terms unless either party "
                        "provides 120 days written notice. The next renewal window closes on "
                        "August 1, 2026, creating a narrow window for renegotiation post-close."
                    ),
                    "agent": "commercial",
                    "confidence": "high",
                    "category": "renewal_terms",
                    "citations": [
                        {
                            "source_path": "NovaBridge/MSA_2023.pdf",
                            "location": "Section 2.2, page 1",
                            "exact_quote": (
                                "This Agreement shall automatically renew for additional one (1) year "
                                "periods unless either party provides written notice of non-renewal at "
                                "least one hundred twenty (120) days prior to the end of the then-current term."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P2",
                    "title": "SLA uptime guarantee at 99.95% with service credits",
                    "description": (
                        "SLA requires 99.95% monthly uptime with graduated service credits: "
                        "10% credit for 99.9-99.95%, 25% for 99.0-99.9%, and 50% for below 99.0%. "
                        "Historical uptime has been 99.97% over the past 12 months."
                    ),
                    "agent": "product_tech",
                    "confidence": "medium",
                    "category": "technical_sla",
                    "citations": [
                        {
                            "source_path": "NovaBridge/SLA_Addendum.pdf",
                            "location": "Exhibit B, page 1",
                            "exact_quote": "Provider guarantees 99.95% monthly uptime for the Platform.",
                        }
                    ],
                },
            ],
            "gaps": [
                {
                    "priority": "P0",
                    "gap_type": "Missing_Doc",
                    "missing_item": "SOW IP Assignment Amendment",
                    "risk_if_missing": "IP ownership of custom integrations remains ambiguous",
                },
                {
                    "priority": "P1",
                    "gap_type": "Stale_Doc",
                    "missing_item": "Current DPA (last version from 2021)",
                    "risk_if_missing": "Data processing agreement may not comply with current GDPR requirements",
                },
            ],
            "governance_resolution_pct": 78.5,
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "$2,400,000",
                    "reference_value": "$2,400,000",
                    "match_status": "match",
                },
                {
                    "data_point": "Contract End Date",
                    "contract_value": "2026-12-01",
                    "reference_value": "2026-11-30",
                    "match_status": "mismatch",
                },
            ],
        },
        "pinnacle_analytics": {
            "customer": "Pinnacle Analytics Group",
            "findings": [
                {
                    "severity": "P0",
                    "title": "Customer concentration risk exceeds 35% of total ARR",
                    "description": (
                        "Pinnacle Analytics represents $1.8M of $4.9M total ARR (36.7%). "
                        "Loss of this single customer would materially impact the business. "
                        "Combined with the CoC termination right, this creates compounding risk."
                    ),
                    "agent": "finance",
                    "confidence": "high",
                    "category": "concentration_risk",
                    "citations": [
                        {
                            "source_path": "_reference/Customer_Revenue_2024.xlsx",
                            "location": "Sheet 1, Row 3",
                            "exact_quote": "Pinnacle Analytics Group | ARR: $1,800,000 | Status: Active",
                        }
                    ],
                },
                {
                    "severity": "P1",
                    "title": "Assignment requires prior written consent",
                    "description": (
                        "Section 15.1 requires Pinnacle's prior written consent for any "
                        "assignment of the agreement, including by operation of law or merger. "
                        "Consent is not to be unreasonably withheld but adds friction to close."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "assignment_consent",
                    "citations": [
                        {
                            "source_path": "Pinnacle_Analytics/MSA_2022.pdf",
                            "location": "Section 15.1, page 9",
                            "exact_quote": (
                                "Neither party may assign this Agreement without the prior written "
                                "consent of the other party, which consent shall not be unreasonably "
                                "withheld. Any attempted assignment without such consent shall be void."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P1",
                    "title": "MFN pricing clause limits future price increases",
                    "description": (
                        "Section 7.3 contains a most-favored-nation clause requiring that "
                        "Pinnacle receives pricing no less favorable than any similarly situated "
                        "customer. This constrains post-acquisition pricing optimization."
                    ),
                    "agent": "commercial",
                    "confidence": "high",
                    "category": "pricing_risk",
                    "citations": [
                        {
                            "source_path": "Pinnacle_Analytics/MSA_2022.pdf",
                            "location": "Section 7.3, page 4",
                            "exact_quote": (
                                "Provider represents that the fees charged to Customer are no less "
                                "favorable than those charged to any other customer of comparable size "
                                "and usage volume."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P2",
                    "title": "No SOC 2 Type II certification requirement",
                    "description": (
                        "Despite handling sensitive financial data, the agreement does not "
                        "require SOC 2 Type II certification from the Provider. Pinnacle may "
                        "request this as a condition of consent to assignment."
                    ),
                    "agent": "product_tech",
                    "confidence": "medium",
                    "category": "security_compliance",
                    "citations": [],
                },
            ],
            "gaps": [
                {
                    "priority": "P1",
                    "gap_type": "Missing_Doc",
                    "missing_item": "Data Processing Agreement",
                    "risk_if_missing": "No formal DPA despite processing financial data",
                },
            ],
            "governance_resolution_pct": 91.2,
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "$1,800,000",
                    "reference_value": "$1,800,000",
                    "match_status": "match",
                },
            ],
        },
        "horizon_logistics": {
            "customer": "Horizon Logistics",
            "findings": [
                {
                    "severity": "P1",
                    "title": "Termination for convenience with 30-day notice",
                    "description": (
                        "Either party may terminate for convenience with only 30 days written "
                        "notice. This is unusually short for an enterprise agreement and provides "
                        "minimal runway to find replacement revenue."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "termination_rights",
                    "citations": [
                        {
                            "source_path": "Horizon_Logistics/Services_Agreement.pdf",
                            "location": "Section 8.1, page 5",
                            "exact_quote": (
                                "Either party may terminate this Agreement for any reason upon "
                                "thirty (30) days prior written notice to the other party."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P2",
                    "title": "Below-market pricing with no escalation clause",
                    "description": (
                        "Horizon's per-seat pricing of $85/month is 32% below the standard "
                        "rate card of $125/month, with no annual escalation clause. The "
                        "agreement locks in this rate for the full 3-year term."
                    ),
                    "agent": "finance",
                    "confidence": "medium",
                    "category": "pricing_risk",
                    "citations": [
                        {
                            "source_path": "Horizon_Logistics/Order_Form_2024.pdf",
                            "location": "Section 2, page 1",
                            "exact_quote": "Per-seat license fee: $85.00/month per named user.",
                        }
                    ],
                },
                {
                    "severity": "P3",
                    "title": "Standard limitation of liability at 12 months fees",
                    "description": (
                        "Liability is capped at total fees paid in the 12 months preceding "
                        "the claim. This is market-standard and does not present unusual risk."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "liability_indemnification",
                    "citations": [
                        {
                            "source_path": "Horizon_Logistics/Services_Agreement.pdf",
                            "location": "Section 10.2, page 6",
                            "exact_quote": (
                                "In no event shall either party's aggregate liability exceed the "
                                "total fees paid by Customer during the twelve (12) month period "
                                "preceding the claim giving rise to liability."
                            ),
                        }
                    ],
                },
            ],
            "gaps": [],
            "governance_resolution_pct": 95.0,
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "$510,000",
                    "reference_value": "$510,000",
                    "match_status": "match",
                },
            ],
        },
        "meridian_health": {
            "customer": "Meridian Health Systems",
            "findings": [
                {
                    "severity": "P1",
                    "title": "HIPAA BAA with strict breach notification requirements",
                    "description": (
                        "The Business Associate Agreement requires breach notification within "
                        "24 hours (stricter than the HIPAA 60-day requirement). Non-compliance "
                        "penalties are uncapped and survive termination."
                    ),
                    "agent": "legal",
                    "confidence": "high",
                    "category": "data_privacy",
                    "citations": [
                        {
                            "source_path": "Meridian_Health/BAA_2023.pdf",
                            "location": "Section 4.1, page 2",
                            "exact_quote": (
                                "Business Associate shall notify Covered Entity of any Breach of "
                                "Unsecured PHI within twenty-four (24) hours of discovery."
                            ),
                        }
                    ],
                },
                {
                    "severity": "P2",
                    "title": "Technical integration dependency on legacy API",
                    "description": (
                        "Meridian's integration relies on the v1 REST API which is scheduled "
                        "for deprecation in Q3 2026. Migration to v2 requires Meridian's "
                        "development team involvement and has not been scheduled."
                    ),
                    "agent": "product_tech",
                    "confidence": "medium",
                    "category": "technical_debt",
                    "citations": [
                        {
                            "source_path": "Meridian_Health/Integration_Spec.pdf",
                            "location": "Section 2.1, page 3",
                            "exact_quote": "All API calls shall use the Provider REST API v1 endpoint.",
                        }
                    ],
                },
            ],
            "gaps": [
                {
                    "priority": "P2",
                    "gap_type": "Missing_Doc",
                    "missing_item": "Penetration test report (last available: 2023)",
                    "risk_if_missing": "Security posture unverified for healthcare data handling",
                },
            ],
            "governance_resolution_pct": 88.0,
            "cross_references": [
                {
                    "data_point": "Annual Revenue",
                    "contract_value": "$340,000",
                    "reference_value": "$340,000",
                    "match_status": "match",
                },
            ],
        },
    }


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "docs" / "sample-report"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "index.html"

    deal_config = {
        "buyer": {"name": "Meridian Capital Partners"},
        "target": {"name": "CloudSync Technologies"},
        "deal": {"type": "acquisition", "expected_close": "2026-Q3"},
    }

    executive_synthesis = {
        "go_no_go": "Conditional Go",
        "executive_narrative": (
            "CloudSync Technologies presents a compelling acquisition opportunity with strong "
            "recurring revenue ($4.9M ARR) and solid customer relationships across 4 enterprise "
            "accounts. However, two critical risks require pre-close resolution: (1) the NovaBridge "
            "change-of-control termination right exposes $2.4M ARR (49% of total), and (2) customer "
            "concentration in Pinnacle Analytics (36.7% of ARR) creates single-point-of-failure risk. "
            "The IP assignment gap in NovaBridge SOW-2024-003 should be remedied before close. "
            "Recommend proceeding with targeted reps & warranties covering CoC consent and IP ownership."
        ),
        "deal_breakers": [
            "NovaBridge CoC termination right ($2.4M ARR at risk)",
            "IP assignment gap in custom integration modules",
            "Customer concentration: top 2 customers represent 86% of ARR",
        ],
        "severity_overrides": [],
    }

    merged_data = _make_sample_data()

    gen = HTMLReportGenerator()
    gen.generate(
        merged_data,
        output_path,
        run_id="sample_demo_001",
        title="CloudSync Technologies — M&A Due Diligence Report",
        deal_config=deal_config,
        executive_synthesis=executive_synthesis,
    )

    print(f"Sample report generated: {output_path}")
    print(f"Open in browser: file://{output_path}")


if __name__ == "__main__":
    main()
