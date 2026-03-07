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
            "Analyze contracts for consent and notice requirements triggered "
            "by a change of control or ownership of the service provider."
        ),
        "columns": [
            {
                "name": "Consent Required (CoC)",
                "prompt": (
                    "Does this agreement require consent, approval, or waiver from the customer "
                    "specifically upon a change of control or change in ownership of the service "
                    "provider (sale of shares, merger, amalgamation, or acquisition)? "
                    "Do NOT include consent requirements triggered only by assignment or transfer. "
                    'If consent is required, state "Yes". If not, state "No". '
                    "Provide the section reference and page number."
                ),
            },
            {
                "name": "Consent Clause Summary",
                "prompt": (
                    "If this agreement requires consent upon a change of control, summarize the "
                    "relevant clause and provide the section reference and page number."
                ),
            },
            {
                "name": "Notice Required (CoC)",
                "prompt": (
                    "Does this agreement require notice to the customer upon a change of control? "
                    'State "Yes" or "No" with section reference and page number.'
                ),
            },
            {
                "name": "Termination Right on CoC",
                "prompt": (
                    "Does the customer have a right to terminate the agreement specifically upon "
                    "a change of control event? If yes, describe the termination right, any cure "
                    "period, and consequences. Provide section reference and page number."
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
                    'State "Yes" or "No". Provide section reference and page number.'
                ),
            },
            {
                "name": "TfC Details",
                "prompt": (
                    "If a termination-for-convenience right exists, specify: (1) who holds the right, "
                    "(2) notice period required, (3) any termination fee or penalty, "
                    "(4) wind-down obligations. Provide section reference."
                ),
            },
            {
                "name": "Mutual or One-Sided",
                "prompt": (
                    "Is the termination-for-convenience right mutual (both parties) or one-sided "
                    "(customer only)? Provide the section reference."
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
                    "or section reference."
                ),
            },
            {
                "name": "Regulatory Framework",
                "prompt": (
                    "Which data protection regulations are referenced (GDPR, CCPA, HIPAA, etc.)? "
                    "List all mentioned frameworks with section references."
                ),
            },
            {
                "name": "Data Transfer Mechanisms",
                "prompt": (
                    "Are there cross-border data transfer provisions (SCCs, BCRs, adequacy decisions)? "
                    "Summarize the mechanism and provide section reference."
                ),
            },
            {
                "name": "Breach Notification",
                "prompt": (
                    "What are the data breach notification obligations? Specify the notification "
                    "timeline, who must be notified, and section reference."
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
                    "Provide section reference and page number."
                ),
            },
            {
                "name": "Auto-Renewal",
                "prompt": (
                    "Does the contract auto-renew? If yes, what is the renewal period "
                    "and the notice period required to prevent renewal? "
                    "Provide section reference."
                ),
            },
            {
                "name": "Early Termination",
                "prompt": (
                    "Are there early termination provisions beyond termination for cause? "
                    "Describe any penalties or wind-down obligations. Provide section reference."
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
                    "Who owns intellectual property created during the engagement? "
                    "Describe the IP ownership allocation (customer owns, vendor owns, joint). "
                    "Provide section reference."
                ),
            },
            {
                "name": "License Scope",
                "prompt": (
                    "What license rights are granted? Describe scope (exclusive/non-exclusive, "
                    "territory, field of use, sublicensing rights). Provide section reference."
                ),
            },
            {
                "name": "Source Code Access",
                "prompt": (
                    "Are there source code escrow or access provisions? If yes, describe "
                    "the trigger conditions and section reference."
                ),
            },
            {
                "name": "Assignment of IP",
                "prompt": (
                    "Can IP rights be assigned or transferred? Are there restrictions "
                    "on assignment upon change of control? Provide section reference."
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
                    "excludes certain categories. Provide section reference."
                ),
            },
            {
                "name": "Uncapped Liabilities",
                "prompt": (
                    "Are any liabilities excluded from the cap (e.g., IP infringement, "
                    "data breach, confidentiality breach)? List all uncapped categories "
                    "with section references."
                ),
            },
            {
                "name": "Indemnification Obligations",
                "prompt": (
                    "What are the indemnification obligations? Summarize who indemnifies whom, "
                    "for what claims, and any procedural requirements. Provide section reference."
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
                    "What service level commitments exist (uptime %, response time, "
                    "resolution time)? List all SLA metrics with target values "
                    "and section references."
                ),
            },
            {
                "name": "SLA Remedies",
                "prompt": (
                    "What remedies apply for SLA failures (service credits, termination right, "
                    "fee reduction)? Describe the remedy structure and section reference."
                ),
            },
            {
                "name": "Performance Benchmarks",
                "prompt": (
                    "Are there performance benchmarking or MFN (most favored nation) clauses? "
                    "Describe any right to benchmark pricing or service against competitors. "
                    "Provide section reference."
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
                    "the scope (territory, field, duration) and section reference."
                ),
            },
            {
                "name": "Non-Compete Clause",
                "prompt": (
                    "Are there non-compete or non-solicitation restrictions? Describe the scope, "
                    "duration, and geographic limitations. Provide section reference."
                ),
            },
            {
                "name": "Preferred Vendor Status",
                "prompt": (
                    "Does the customer designate the vendor as a preferred or exclusive supplier? "
                    "Describe the arrangement and section reference."
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
