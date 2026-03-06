"""validate_finding MCP tool.

Validates a finding dict against the AgentFinding Pydantic model and runs
additional domain checks (category whitelist, P0/P1 citation requirements).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from dd_agents.models.enums import Severity
from dd_agents.models.finding import AgentFinding

# Recognized finding categories
VALID_CATEGORIES: set[str] = {
    "change_of_control",
    "assignment",
    "termination",
    "liability",
    "indemnification",
    "governing_law",
    "ip_ownership",
    "non_compete",
    "exclusivity",
    "mfn",
    "pricing",
    "payment_terms",
    "discount",
    "revenue_recognition",
    "renewal",
    "sla",
    "service_credits",
    "territory",
    "dpa",
    "security",
    "data_residency",
    "regulatory",
    "missing_document",
    "data_gap",
    "domain_reviewed_no_issues",
    "revenue_composition",
    "unit_economics",
    "financial_projections",
    "cost_structure",
    "customer_segmentation",
    "pricing_model",
    "expansion_contraction",
    "competitive_positioning",
    # Red flag categories (Issue #125)
    "litigation",
    "ip_gap",
    "financial_restatement",
    "key_person_risk",
    "debt_covenant",
    "customer_concentration",
    "Other",
}


def validate_finding(finding_json: dict[str, Any]) -> dict[str, Any]:
    """Validate a finding dict.

    Returns:
        ``{"valid": True}`` on success, or
        ``{"valid": False, "errors": [...]}`` on failure.
    """
    errors: list[str] = []

    try:
        finding = AgentFinding.model_validate(finding_json)
    except ValidationError as exc:
        return {
            "valid": False,
            "errors": [f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()],
        }

    # Domain checks beyond Pydantic
    if finding.severity in (Severity.P0, Severity.P1):
        for idx, cit in enumerate(finding.citations):
            if not cit.exact_quote:
                errors.append(f"citations[{idx}]: {finding.severity} finding requires non-empty exact_quote")

    if finding.category not in VALID_CATEGORIES:
        errors.append(f"category '{finding.category}' not in recognized categories")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True}
