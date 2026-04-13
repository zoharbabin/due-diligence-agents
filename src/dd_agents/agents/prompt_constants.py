"""Shared prompt constants for all specialist agents.

Centralises guardrails, severity rules, citation mandates, and output
format constraints that MUST be consistent across all four specialist
agents (Legal, Finance, Commercial, ProductTech).  Agent-specific
guidance remains in each agent's ``domain_robustness()`` method; this
module provides the **shared** building blocks.

Any change to these constants automatically propagates to all agents,
eliminating the divergence risk of copy-pasted prompt text.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Severity calibration (used in every specialist system prompt)
# ---------------------------------------------------------------------------

SEVERITY_PREAMBLE: str = (
    "Calibrate severity carefully: P0 is reserved for genuine deal-stoppers. "
    "Most findings are P2 or P3. Accuracy over volume."
)

# ---------------------------------------------------------------------------
# JSON output constraint (used in system prompt, output format, etc.)
# ---------------------------------------------------------------------------

JSON_OUTPUT_CONSTRAINT: str = (
    "Your final output message MUST be a single valid JSON object. Do not "
    "wrap it in markdown fences (no ```json). Do not include explanatory text "
    "before or after the JSON. Output ONLY the JSON object."
)

# ---------------------------------------------------------------------------
# Termination for Convenience — shared severity rule
# ---------------------------------------------------------------------------

TFC_SEVERITY_RULE: str = (
    "TfC is NOT a deal-breaker — it is a valuation/revenue quality signal. "
    "Revenue from TfC contracts is non-committed ('at-risk ARR') with lower "
    "certainty than locked-in contracts. TfC affects RPO calculations and "
    "revenue recognition (ASC 606). Report TfC findings as P2 valuation "
    "concerns. Escalate to P1 ONLY if: TfC + >10% revenue + <90 day notice. "
    "NEVER flag TfC as P0."
)

# ---------------------------------------------------------------------------
# Gap protocol — "IF NOT FOUND" rule (used in domain robustness sections)
# ---------------------------------------------------------------------------

GAP_NOT_FOUND: str = "IF NOT FOUND: Write a gap with gap_type 'Not_Found'."

# ---------------------------------------------------------------------------
# Finding JSON schema block (used in output format + robustness instructions)
# ---------------------------------------------------------------------------

#: Canonical JSON schema for a single finding entry.  Used in both
#: ``_build_output_format`` and ``robustness_instructions`` so that the
#: agent receives a single, consistent schema definition.
FINDING_SCHEMA_BLOCK: str = (
    "```json\n"
    "{\n"
    '  "severity": "P0 | P1 | P2 | P3 (required)",\n'
    '  "category": "string (required)",\n'
    '  "title": "string (required, max 120 chars)",\n'
    '  "description": "string (required)",\n'
    '  "confidence": "high | medium | low",\n'
    '  "citations": [\n'
    "    {\n"
    '      "source_type": "file",\n'
    '      "source_path": "exact/path/to/document.pdf (REQUIRED — must be a real file you read)",\n'
    '      "location": "Section X.Y or page number",\n'
    '      "exact_quote": "verbatim text from the document (REQUIRED for all severities)"\n'
    "    }\n"
    "  ]  // ← MUST NOT be empty. Findings with empty citations → auto-downgraded to P3\n"
    "}\n"
    "```"
)

# ---------------------------------------------------------------------------
# TfC severity calibration — abbreviated form for severity tables
# ---------------------------------------------------------------------------

#: Two-line TfC calibration for use in SPECIALIST_FOCUS severity tables.
#: The full prose version is :data:`TFC_SEVERITY_RULE`.
TFC_SEVERITY_CALIBRATION: str = (
    "- TfC clause = P2 (valuation concern, not deal-breaker)\n- TfC on >10% revenue, <90d notice = P1"
)

# ---------------------------------------------------------------------------
# Citation mandate — parameterised per domain
# ---------------------------------------------------------------------------

#: Domain-specific citation examples keyed by agent type name.
_CITATION_EXAMPLES: dict[str, str] = {
    "legal": (
        "Examples of good Legal citations:\n"
        "- MSA clauses: cite the section number, clause heading, and verbatim text\n"
        "- CoC provisions: cite the exact trigger language and remedy text\n"
        "- Assignment restrictions: cite the full restriction clause and any carve-outs\n"
        "- NDAs / IP clauses: cite the definition section and operative clause text\n"
        "- Governance documents: cite the article/section and exact resolution text"
    ),
    "finance": (
        "Examples of good Finance citations:\n"
        "**For contract documents**: cite the section number and verbatim clause text.\n\n"
        "**For spreadsheets**: cite the tab name, row/column header, and the "
        "exact cell value as it appears. Example `exact_quote`:\n"
        '- "Revenue_Projections tab, Row 15 (Acme Corp): ARR = $1,200,000"\n'
        "- \"Pricing_Guidelines tab, Column C header 'Standard Discount': 15%\"\n"
        '- "P&L tab, Row 32 (Professional Services Revenue): $450,000"\n\n'
        "**For financial statements / PDFs**: cite the page number, section "
        "heading, and exact text or numerical value."
    ),
    "commercial": (
        "Examples of good Commercial citations:\n"
        "- Contract clauses: cite the specific contract file, section/clause number, "
        "and verbatim clause text\n"
        "- Renewal/termination: cite the renewal or termination clause with exact "
        "notice periods, dates, and quoted trigger language\n"
        "- Pricing findings: cite the rate card, pricing schedule, or contract exhibit "
        "with the exact pricing language or line item\n"
        "- SLA terms: cite the SLA section number, metric definition, and exact threshold text\n"
        "- Volume commitments: cite the commitment clause with exact quantities and penalties\n"
        "- Customer concentration: cite the revenue data source (spreadsheet tab, row, "
        "cell value) that establishes the concentration figure\n"
        "- Customer health data: cite the specific spreadsheet tab, row, and metric value"
    ),
    "producttech": (
        "Examples of good ProductTech citations:\n"
        "- Security/compliance: cite the specific SOC2 report, pentest report, or "
        "policy document with report title, date, and exact text\n"
        "- Architecture findings: cite the technical documentation, product spec, or "
        "SOW with section heading and exact text\n"
        "- IP findings: cite the IP schedule, patent filing, or license agreement "
        "with clause number and verbatim language\n"
        "- Team/org findings: cite the org chart, HR document, or employment agreement "
        "with exact role titles and terms\n"
        "- DPA clauses: cite the section number and verbatim clause text\n"
        "- SLA commitments: cite the exact uptime percentage and response time from the doc\n"
        "- Pen test reports: cite the finding ID, severity, and remediation status text"
    ),
}


def build_citation_mandate(agent_type: str) -> str:
    """Build the MANDATORY Citation Requirements section for *agent_type*.

    Returns a complete prompt section with the citation mandate, domain-
    specific examples, and the auto-downgrade warning.  The core rules are
    identical across all agents; only the examples differ.
    """
    label = agent_type.replace("_", " ").title()
    examples = _CITATION_EXAMPLES.get(agent_type, _CITATION_EXAMPLES["legal"])

    return (
        f"### MANDATORY Citation Requirements for {label} Findings\n\n"
        "EVERY finding MUST include an `exact_quote` copied verbatim from the "
        "source document.  `exact_quote` is MANDATORY for ALL findings, not "
        "just P0/P1.\n\n"
        "**DO NOT create a finding without a citation.**  If you cannot find a "
        "specific document passage, cell value, or number to cite, you do not "
        "have evidence for the finding and MUST NOT create it.  Write a gap "
        "instead.\n\n"
        "Before writing each finding, verify:\n"
        "1. You have a specific source_path pointing to a real file you read\n"
        "2. You have an exact_quote copied verbatim from that file\n"
        "3. The quote actually supports the finding's claim\n\n"
        f"{examples}\n\n"
        "**WARNING**: Findings without citations are AUTOMATICALLY DOWNGRADED "
        "to P3 during merge.  A finding downgraded from P1 to P3 is worthless — "
        "it loses all impact.  Invest the extra turn to read the source document "
        "and copy the exact quote."
    )
