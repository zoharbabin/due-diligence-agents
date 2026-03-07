"""Search prompt templates library (Issue #141).

Ready-to-use legal analysis prompt templates for the ``dd-agents search``
command. Each template contains a set of columns (questions) designed for
specific M&A due diligence provisions.

Based on Addleshaw Goddard RAG Report (2024) — AG-4: provision-specific
prompts outperform generic extraction.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

PROMPT_TEMPLATES: dict[str, dict[str, Any]] = {
    "change_of_control": {
        "name": "Change of Control Analysis",
        "description": (
            "Analyze customer contracts for consent and notice requirements triggered specifically "
            "by a change of control or ownership of the service provider. These prompts are designed "
            "to exclude assignment/transfer-only provisions that would not be triggered under a share "
            "acquisition."
        ),
        "columns": [
            {
                "name": "Consent Required (Change of Control)",
                "prompt": (
                    "Does this agreement require consent, approval, or waiver from the customer "
                    "specifically upon a change of control or change in ownership of the service "
                    "provider (such as a sale of shares, merger, amalgamation, or acquisition)? "
                    "Do NOT include consent requirements that are triggered only by assignment or "
                    "transfer of the agreement itself. Focus exclusively on provisions that are "
                    "triggered by a change in who owns or controls the contracting party, not by "
                    "transfer of contractual rights or obligations. "
                    'If consent is required, state "Yes". If consent is not required, state "No". '
                    "Pin point the section reference (if available) and page number in the agreement "
                    "in your response."
                ),
            },
            {
                "name": "Consent Clause Summary",
                "prompt": (
                    "If this agreement requires consent upon a change of control or change in "
                    "ownership of the service provider (such as a sale of shares, merger, "
                    "amalgamation, or acquisition), summarize the relevant clause that creates "
                    "this requirement and provide the section reference and page number where it "
                    "appears. Do not include clauses that only require consent for assignment or "
                    "transfer of the agreement itself."
                ),
            },
            {
                "name": "Notice Required (Change of Control)",
                "prompt": (
                    "Does this agreement require notice to the customer specifically upon a change "
                    "of control or change in ownership of the service provider (such as a sale of "
                    "shares, merger, amalgamation, or acquisition)? Do NOT include notice requirements "
                    "that are triggered only by assignment or transfer of the agreement itself. "
                    'If notice is required, state "Yes". If notice is not required, state "No". '
                    "Pin point the section reference (if available) and page number in the agreement "
                    "in your response."
                ),
            },
            {
                "name": "Notice Clause Summary",
                "prompt": (
                    "If this agreement requires notice upon a change of control or change in "
                    "ownership of the service provider (such as a sale of shares, merger, "
                    "amalgamation, or acquisition), summarize the relevant clause that creates "
                    "this requirement and provide the section reference and page number where it "
                    "appears. Do not include clauses that only require notice for assignment or "
                    "transfer of the agreement itself."
                ),
            },
            {
                "name": "Termination for Convenience",
                "prompt": (
                    "Does this agreement grant the customer a right to terminate without cause "
                    "(termination for convenience, termination at will, or termination in the "
                    "customer's sole/absolute discretion) with or without a notice period? This is "
                    "critical for M&A due diligence because a termination-for-convenience right "
                    "allows the customer to exit the contract at any time regardless of whether a "
                    "change of control occurs, creating significant revenue risk for an acquirer. "
                    'If such a right exists, state "Yes" and specify: (1) who holds the right '
                    "(customer only, or mutual), (2) the required notice period (if any), "
                    "(3) whether any termination fee, penalty, or wind-down payment applies, and "
                    "(4) the section reference and page number. If no termination-for-convenience "
                    'right exists, state "No".'
                ),
            },
            {
                "name": "Termination for Convenience Summary",
                "prompt": (
                    "If this agreement grants the customer a right to terminate without cause "
                    "(termination for convenience, termination at will, or termination in the "
                    "customer's sole/absolute discretion), summarize the relevant clause including: "
                    "who holds the right, the notice period required, any termination fees or "
                    "penalties, and any wind-down or transition obligations. Provide the section "
                    "reference and page number where the clause appears. Also note if the termination "
                    "right is asymmetric (customer-only vs. mutual) and whether it could be exercised "
                    "in response to a change of control even though it is not explicitly triggered "
                    "by one."
                ),
            },
        ],
    },
    "termination_for_convenience": {
        "name": "Termination for Convenience Analysis",
        "description": (
            "Identify contracts with termination-for-convenience rights that create "
            "revenue risk regardless of service performance."
        ),
        "columns": [
            {
                "name": "TfC Right Exists",
                "prompt": (
                    "Does this agreement grant the customer a right to terminate without cause "
                    "(termination for convenience, at will, or in sole discretion)? "
                    'State "Yes" or "No". Provide the section reference and page number.'
                ),
            },
            {
                "name": "TfC Details",
                "prompt": (
                    "If a termination-for-convenience right exists, specify: (1) who holds the right, "
                    "(2) the notice period required, (3) any termination fee or penalty, "
                    "(4) wind-down obligations. Provide the section reference and page number."
                ),
            },
            {
                "name": "Mutual or One-Sided",
                "prompt": (
                    "Is the termination-for-convenience right mutual (both parties) or one-sided "
                    "(customer only)? Provide the section reference and page number."
                ),
            },
        ],
    },
    "data_privacy": {
        "name": "Data Privacy & Protection Analysis",
        "description": (
            "Assess data protection compliance, DPA status, and data handling obligations across customer contracts."
        ),
        "columns": [
            {
                "name": "DPA Present",
                "prompt": (
                    "Does this agreement include a Data Processing Agreement (DPA) or data "
                    "processing addendum? State 'Yes' or 'No'. If yes, identify the document "
                    "or section reference and page number."
                ),
            },
            {
                "name": "Regulatory Framework",
                "prompt": (
                    "Does this agreement reference any data protection regulations (GDPR, CCPA, "
                    "HIPAA, etc.)? List all mentioned frameworks with section references and "
                    "page numbers."
                ),
            },
            {
                "name": "Data Transfer Mechanisms",
                "prompt": (
                    "Does this agreement include cross-border data transfer provisions (SCCs, BCRs, "
                    "adequacy decisions)? If yes, summarize the mechanism and provide the section "
                    "reference and page number."
                ),
            },
            {
                "name": "Breach Notification",
                "prompt": (
                    "Does this agreement specify data breach notification obligations? If yes, "
                    "state the notification timeline, who must be notified, and provide the "
                    "section reference and page number."
                ),
            },
        ],
    },
    "renewal_and_expiry": {
        "name": "Renewal & Contract Expiry Analysis",
        "description": (
            "Map contract renewal terms, auto-renewal provisions, and expiration dates for portfolio risk assessment."
        ),
        "columns": [
            {
                "name": "Contract Term",
                "prompt": (
                    "What is the initial contract term (start date, end date, duration)? "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Auto-Renewal",
                "prompt": (
                    "Does the contract auto-renew? If yes, state the renewal period "
                    "and the notice period required to prevent renewal. "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Early Termination",
                "prompt": (
                    "Are there early termination provisions beyond termination for cause? "
                    "If yes, describe any penalties or wind-down obligations. "
                    "Provide the section reference and page number."
                ),
            },
        ],
    },
    "ip_ownership": {
        "name": "IP & Technology License Analysis",
        "description": ("Analyze intellectual property ownership, license grants, and technology transfer provisions."),
        "columns": [
            {
                "name": "IP Ownership",
                "prompt": (
                    "Does this agreement address intellectual property ownership for work "
                    "created during the engagement? If yes, describe the IP ownership allocation "
                    "(customer owns, vendor owns, joint). Provide the section reference and "
                    "page number."
                ),
            },
            {
                "name": "License Scope",
                "prompt": (
                    "Does this agreement grant license rights? If yes, describe scope "
                    "(exclusive/non-exclusive, territory, field of use, sublicensing rights). "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Source Code Access",
                "prompt": (
                    "Does this agreement include source code escrow or access provisions? "
                    "If yes, describe the trigger conditions. Provide the section reference "
                    "and page number."
                ),
            },
            {
                "name": "Assignment of IP",
                "prompt": (
                    "Can IP rights be assigned or transferred under this agreement? Are there "
                    "restrictions on assignment upon change of control? Provide the section "
                    "reference and page number."
                ),
            },
        ],
    },
    "liability_and_indemnification": {
        "name": "Liability & Indemnification Analysis",
        "description": (
            "Map liability caps, indemnification obligations, and insurance requirements across the contract portfolio."
        ),
        "columns": [
            {
                "name": "Liability Cap",
                "prompt": (
                    "Is there a cap on liability? If yes, state the cap amount or formula "
                    "(e.g., 12 months of fees), and whether it applies to all claims or "
                    "excludes certain categories. Provide the section reference and page number."
                ),
            },
            {
                "name": "Uncapped Liabilities",
                "prompt": (
                    "Are any liabilities excluded from the cap (e.g., IP infringement, "
                    "data breach, confidentiality breach)? List all uncapped categories "
                    "with section references and page numbers."
                ),
            },
            {
                "name": "Indemnification Obligations",
                "prompt": (
                    "Does this agreement include indemnification obligations? If yes, summarize "
                    "who indemnifies whom, for what claims, and any procedural requirements. "
                    "Provide the section reference and page number."
                ),
            },
        ],
    },
    "sla_and_performance": {
        "name": "SLA & Performance Obligations",
        "description": ("Assess service level commitments, performance guarantees, and remedy provisions."),
        "columns": [
            {
                "name": "SLA Commitments",
                "prompt": (
                    "Does this agreement include service level commitments (uptime %, response time, "
                    "resolution time)? If yes, list all SLA metrics with target values. "
                    "Provide section references and page numbers."
                ),
            },
            {
                "name": "SLA Remedies",
                "prompt": (
                    "Does this agreement specify remedies for SLA failures (service credits, "
                    "termination right, fee reduction)? If yes, describe the remedy structure. "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Performance Benchmarks",
                "prompt": (
                    "Does this agreement include performance benchmarking or MFN (most favored "
                    "nation) clauses? If yes, describe the right to benchmark pricing or service "
                    "against competitors. Provide the section reference and page number."
                ),
            },
        ],
    },
    "exclusivity_and_non_compete": {
        "name": "Exclusivity & Non-Compete Analysis",
        "description": ("Identify exclusivity arrangements, non-compete provisions, and competitive restrictions."),
        "columns": [
            {
                "name": "Exclusivity Provision",
                "prompt": (
                    "Does this agreement grant exclusivity to either party? If yes, describe "
                    "the scope (territory, field, duration). Provide the section reference "
                    "and page number."
                ),
            },
            {
                "name": "Non-Compete Clause",
                "prompt": (
                    "Does this agreement include non-compete or non-solicitation restrictions? "
                    "If yes, describe the scope, duration, and geographic limitations. "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Preferred Vendor Status",
                "prompt": (
                    "Does the customer designate the vendor as a preferred or exclusive supplier? "
                    "If yes, describe the arrangement. Provide the section reference and page number."
                ),
            },
        ],
    },
    "pricing": {
        "name": "Pricing & Fee Structure Analysis",
        "description": (
            "Analyze pricing models, fee structures, discount provisions, and "
            "MFN clauses across the contract portfolio."
        ),
        "columns": [
            {
                "name": "Pricing Model",
                "prompt": (
                    "Does this agreement specify a pricing model? If yes, identify the type "
                    "(per-user, per-unit, tiered, flat-rate, consumption-based, hybrid). "
                    "State the pricing amounts or rates. Provide the section reference and "
                    "page number."
                ),
            },
            {
                "name": "Discount or Concession",
                "prompt": (
                    "Does this agreement include any discounts, concessions, or preferential "
                    "pricing? If yes, state the discount percentage or amount and any conditions "
                    "for the discount. Provide the section reference and page number."
                ),
            },
            {
                "name": "Price Escalation",
                "prompt": (
                    "Does this agreement include price escalation or annual increase provisions? "
                    "If yes, state the escalation mechanism (CPI, fixed %, cap). "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "MFN Clause",
                "prompt": (
                    "Does this agreement include a Most Favored Nation (MFN) or best-price "
                    "guarantee clause? If yes, describe the scope and benchmarking mechanism. "
                    "Provide the section reference and page number."
                ),
            },
        ],
    },
    "confidentiality": {
        "name": "Confidentiality & NDA Analysis",
        "description": (
            "Assess confidentiality obligations, NDA coverage, and information "
            "handling restrictions across customer contracts."
        ),
        "columns": [
            {
                "name": "Confidentiality Provision",
                "prompt": (
                    "Does this agreement include confidentiality or non-disclosure obligations? "
                    'State "Yes" or "No". If yes, identify whether it is mutual or one-sided. '
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Confidentiality Term",
                "prompt": (
                    "Does this agreement specify a duration for confidentiality obligations? "
                    "If yes, state the term (e.g., 2 years after termination, perpetual). "
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Exceptions",
                "prompt": (
                    "Does this agreement list exceptions to confidentiality (e.g., publicly "
                    "available information, independently developed, required by law)? "
                    "If yes, list all exceptions. Provide the section reference and page number."
                ),
            },
            {
                "name": "Surviving Obligations",
                "prompt": (
                    "Do confidentiality obligations survive termination or expiration of the "
                    'agreement? State "Yes" or "No". If yes, state the survival period. '
                    "Provide the section reference and page number."
                ),
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_template(name: str) -> dict[str, Any] | None:
    """Return a template by name, or None if not found."""
    return PROMPT_TEMPLATES.get(name)


def list_templates() -> list[str]:
    """Return all template names."""
    return list(PROMPT_TEMPLATES.keys())


def export_template(name: str) -> str:
    """Export a template as JSON string ready for ``dd-agents search``."""
    tpl = PROMPT_TEMPLATES.get(name)
    if tpl is None:
        raise KeyError(f"Unknown template: {name}")
    return json.dumps(tpl, indent=2)
