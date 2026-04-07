"""E2E test fixtures and shared setup.

E2E tests require:
- A valid ANTHROPIC_API_KEY or AWS Bedrock credentials
- Network access for Claude API calls
- A sample data room directory

Mark E2E tests with @pytest.mark.e2e (CI) or @pytest.mark.local (deep, local-only).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path  # noqa: TC003

import pytest


def _has_api_key() -> bool:
    """Check if Claude API credentials are available (direct or Bedrock)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    # AWS Bedrock: CLAUDE_CODE_USE_BEDROCK + AWS credentials
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return bool(
            os.environ.get("AWS_PROFILE")
            or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
        )
    return False


skip_no_api_key = pytest.mark.skipif(
    not _has_api_key(),
    reason="No API credentials (ANTHROPIC_API_KEY or Bedrock); skipping",
)


@pytest.fixture()
def e2e_data_room(tmp_path: Path) -> Path:
    """Create a realistic sample data room for E2E testing.

    Structure::

        data_room/
          GroupA/
            Acme Corp/
              contract_acme.pdf.md
              invoice_acme_2024.xlsx.md
            Beta Inc/
              msa_beta.pdf.md
              sow_beta.pdf.md
          GroupB/
            Gamma LLC/
              license_gamma.docx.md
              data_processing_gamma.pdf.md
          _reference/
            buyer_overview.pdf.md
    """
    root = tmp_path / "data_room"
    root.mkdir()

    # GroupA / Acme Corp
    acme = root / "GroupA" / "Acme Corp"
    acme.mkdir(parents=True)
    (acme / "contract_acme.pdf.md").write_text(
        "# Master Service Agreement - Acme Corp\n\n"
        "Effective Date: 2023-01-15\n"
        "Term: 36 months\n"
        "Annual Value: $120,000\n\n"
        "## Section 1 — Scope of Services\n"
        'NovaBridge Solutions ("Provider") shall deliver the NovaBridge Analytics Platform '
        'to Acme Corp ("Customer"), including data ingestion, dashboarding, and API access. '
        "Provider shall maintain 99.9% uptime SLA measured monthly.\n\n"
        "## Section 2 — Fees and Payment Terms\n"
        "Customer shall pay $10,000 per month, invoiced quarterly in advance. "
        "Late payments incur 1.5% monthly interest. Annual escalation: CPI + 2%, "
        "capped at 5%.\n\n"
        "## Section 3 — Intellectual Property\n"
        "All pre-existing IP remains with its owner. Customer data remains Customer property. "
        "Provider retains all rights to the Platform, including improvements derived from "
        "Customer usage patterns. Any custom developments paid for by Customer shall be "
        "jointly owned.\n\n"
        "## Section 4 — Change of Control\n"
        "### 4.1 Assignment\n"
        "Neither party may assign this Agreement without prior written consent, "
        "except in connection with a merger, acquisition, or sale of substantially all assets. "
        "### 4.2 Auto-Renewal\n"
        "This agreement shall auto-renew for successive 12-month periods "
        "unless either party provides 90 days written notice.\n"
        "### 4.3 Change of Control Termination Right\n"
        "In the event of a Change of Control of Provider, Customer may terminate this "
        "Agreement within 60 days of receiving notice, without penalty.\n\n"
        "## Section 5 — Data Security\n"
        "Provider shall maintain SOC 2 Type II compliance. Customer data shall be encrypted "
        "at rest (AES-256) and in transit (TLS 1.2+). Provider shall notify Customer of any "
        "data breach within 72 hours. Annual penetration testing required.\n\n"
        "## Section 6 — Liability and Indemnification\n"
        "Total aggregate liability shall not exceed $500,000 or 12 months of fees paid, "
        "whichever is greater. Provider indemnifies Customer against third-party IP claims "
        "arising from Platform use. Consequential damages are excluded for both parties.\n\n"
        "## Section 7 — Termination\n"
        "Either party may terminate for cause with 30 days written notice after uncured "
        "material breach. Provider may terminate if Customer fails to pay for 60+ days. "
        "Upon termination, Provider shall return or destroy all Customer data within 30 days.\n\n"
        "## Section 8 — Governing Law\n"
        "This Agreement shall be governed by the laws of the State of Delaware. "
        "Disputes shall be resolved by binding arbitration under AAA rules.\n",
        encoding="utf-8",
    )
    (acme / "invoice_acme_2024.xlsx.md").write_text(
        "# Invoice Summary - Acme Corp 2024\n\n"
        "Account: Acme Corp | Contract #AC-2023-001\n"
        "Payment Terms: Net 30 | Currency: USD\n\n"
        "## Quarterly Invoices\n\n"
        "| Invoice # | Date | Period | Amount | Status |\n"
        "|-----------|------|--------|--------|--------|\n"
        "| INV-2024-001 | 2024-01-15 | Q1 2024 | $30,000 | Paid |\n"
        "| INV-2024-002 | 2024-04-15 | Q2 2024 | $30,000 | Paid |\n"
        "| INV-2024-003 | 2024-07-15 | Q3 2024 | $30,000 | Paid |\n"
        "| INV-2024-004 | 2024-10-15 | Q4 2024 | $30,000 | Outstanding - 45 days overdue |\n\n"
        "## Revenue Summary\n"
        "- Total invoiced 2024: $120,000\n"
        "- Total collected: $90,000\n"
        "- Outstanding: $30,000 (Q4 overdue)\n"
        "- Prior year (2023): $110,000\n"
        "- YoY growth: 9.1%\n\n"
        "## Notes\n"
        "- Q4 invoice past due; collections team has escalated\n"
        "- Customer requested NET-60 terms starting 2025; pending approval\n",
        encoding="utf-8",
    )

    # GroupA / Beta Inc
    beta = root / "GroupA" / "Beta Inc"
    beta.mkdir(parents=True)
    (beta / "msa_beta.pdf.md").write_text(
        "# Master Service Agreement - Beta Inc\n\n"
        "Start Date: 2022-06-01\n"
        "End Date: 2025-05-31\n"
        "Contract Value: $85,000/year\n\n"
        "## Article 1 — License Grant\n"
        "NovaBridge Solutions grants Beta Inc a non-exclusive, non-transferable license to "
        "use the NovaBridge Platform for up to 200 named users. License is enterprise-wide "
        "within Beta Inc's legal entity only; no sublicensing permitted.\n\n"
        "## Article 2 — Fees and Payment\n"
        "Annual license fee: $85,000, payable in advance. Implementation services billed "
        "at $250/hour, T&M basis. Support tier: Premium (24/7, 4-hour response SLA). "
        "Overdue invoices accrue 1% monthly interest.\n\n"
        "## Article 3 — Intellectual Property\n"
        "Provider retains all IP in the Platform. Customer retains all IP in Customer Data. "
        "Custom integrations developed under SOW become Provider IP unless SOW specifies otherwise. "
        "No implied licenses.\n\n"
        "## Article 4 — Assignment and Change of Control\n"
        "This Agreement may not be assigned without prior written consent. Consent shall not "
        "be unreasonably withheld. A Change of Control of Provider shall require 90 days "
        "advance written notice to Customer. Customer may terminate within 120 days of Change "
        "of Control notification without early termination penalty.\n\n"
        "## Article 5 — Termination\n"
        "Either party may terminate with 60 days notice. Early termination fee: 50% of "
        "remaining term value. Material breach: 30 days to cure after written notice. "
        "Data portability: Provider must export Customer data in CSV/JSON within 15 business "
        "days of termination.\n\n"
        "## Article 6 — Dispute Resolution\n"
        "Disputes shall first be escalated to senior management for 30 days. If unresolved, "
        "binding arbitration under ICC rules, seated in New York. Each party bears its own costs.\n\n"
        "## Article 7 — Technology and Integration\n"
        "Provider shall maintain REST API (v2+) compatibility. Breaking API changes require "
        "12 months deprecation notice. Provider supports SSO via SAML 2.0 and OAuth 2.0. "
        "Customer's AWS us-east-1 deployment requires Provider's platform to maintain "
        "sub-100ms p99 latency to that region.\n\n"
        "## Article 8 — Confidentiality\n"
        "All non-public information exchanged is Confidential Information. Obligations survive "
        "3 years post-termination. Standard carve-outs for publicly available information.\n",
        encoding="utf-8",
    )
    (beta / "sow_beta.pdf.md").write_text(
        "# Statement of Work #1 - Beta Inc Platform Implementation\n\n"
        "SOW Reference: SOW-BETA-2022-001\n"
        "MSA Reference: MSA-BETA-2022\n"
        "Effective Date: 2022-07-15\n\n"
        "## 1. Project Scope\n"
        "Implementation of NovaBridge Analytics Platform for Beta Inc, including:\n"
        "- Data pipeline integration with Beta's Snowflake data warehouse\n"
        "- Custom dashboard development (5 executive dashboards)\n"
        "- SSO integration with Beta's Okta identity provider\n"
        "- Data migration from legacy Tableau deployment\n\n"
        "## 2. Timeline and Milestones\n\n"
        "| Phase | Milestone | Target Date | Payment |\n"
        "|-------|-----------|-------------|----------|\n"
        "| Phase 1 | Environment Setup & SSO | 2022-08-15 | $15,000 |\n"
        "| Phase 2 | Data Pipeline Integration | 2022-09-30 | $25,000 |\n"
        "| Phase 3 | Dashboard Development | 2022-11-15 | $20,000 |\n"
        "| Phase 4 | UAT & Go-Live | 2022-12-15 | $10,000 |\n\n"
        "Total Implementation Fee: $70,000\n\n"
        "## 3. Technical Requirements\n"
        "- Snowflake connector: real-time CDC via Snowpipe Streaming\n"
        "- API rate limits: minimum 1,000 requests/minute per tenant\n"
        "- Data retention: 7 years per Beta's compliance requirements\n"
        "- Disaster recovery: RPO 1 hour, RTO 4 hours\n\n"
        "## 4. Acceptance Criteria\n"
        "Each milestone requires written sign-off from Beta Inc project sponsor. "
        "Provider has 10 business days to remediate any defects identified during UAT. "
        "Final acceptance triggers warranty period of 90 days.\n\n"
        "## 5. IP Ownership\n"
        "Custom dashboards developed under this SOW are Provider IP (per MSA Article 3). "
        "Beta Inc receives a perpetual license to use the custom dashboards. "
        "Data pipeline connectors are open-sourced under Apache 2.0.\n",
        encoding="utf-8",
    )

    # GroupB / Gamma LLC
    gamma = root / "GroupB" / "Gamma LLC"
    gamma.mkdir(parents=True)
    (gamma / "license_gamma.docx.md").write_text(
        "# Enterprise Software License Agreement - Gamma LLC\n\n"
        "License Type: Enterprise\n"
        "Seats: 500\n"
        "Annual Fee: $200,000\n"
        "Effective Date: 2024-03-01\n"
        "Term: 24 months\n\n"
        "## 1. License Scope\n"
        "NovaBridge Solutions grants Gamma LLC an enterprise license for the NovaBridge "
        "Analytics Platform for up to 500 named users across Gamma LLC and its wholly-owned "
        "subsidiaries. Usage beyond 500 seats incurs overage at $400/user/year.\n\n"
        "## 2. Fees and Payment\n"
        "Annual license fee: $200,000, payable semi-annually ($100,000 per invoice). "
        "Professional services: $300/hour. Volume discount: 10% on renewals if paid annually "
        "in advance. Late payment: 1.5% per month.\n\n"
        "## 3. Service Level Agreement\n"
        "Platform availability: 99.95% monthly. Scheduled maintenance windows: Sundays "
        "02:00-06:00 UTC. Unplanned downtime credits: 5% of monthly fee per hour beyond SLA. "
        "Maximum credit: 30% of monthly fee. Support: 24/7 for P0/P1, business hours for P2/P3.\n\n"
        "## 4. Data Security and Privacy\n"
        "Provider shall comply with SOC 2 Type II, ISO 27001, and GDPR (as applicable). "
        "Customer data hosted in EU (Frankfurt region) per Gamma LLC requirement. "
        "Encryption: AES-256 at rest, TLS 1.3 in transit. Annual third-party security audit "
        "results shared with Customer. Provider shall maintain cyber liability insurance "
        "of at least $5,000,000.\n\n"
        "## 5. Change of Control\n"
        "In the event of a Change of Control of Provider (merger, acquisition, or sale of "
        ">50% voting interests), Provider shall notify Customer within 15 business days. "
        "Customer shall have the right to terminate this Agreement within 90 days of such "
        "notice without penalty and receive a pro-rata refund of prepaid fees.\n\n"
        "## 6. Liability\n"
        "Provider's aggregate liability: lesser of $1,000,000 or 2x annual fees paid. "
        "Exclusions: indirect, consequential, punitive damages (mutual). "
        "Exceptions to cap: IP indemnification, data breach, gross negligence.\n\n"
        "## 7. IP and Ownership\n"
        "All intellectual property in the Platform remains with Provider. "
        "Customer retains ownership of all Customer Data. Provider may use anonymized, "
        "aggregated usage data for product improvement.\n\n"
        "## 8. Governing Law and Venue\n"
        "Laws of England and Wales. Exclusive jurisdiction: London Commercial Court.\n",
        encoding="utf-8",
    )
    (gamma / "data_processing_gamma.pdf.md").write_text(
        "# Data Processing Agreement - Gamma LLC\n\n"
        "DPA Effective Date: 2024-03-01\n"
        "Associated Agreement: Enterprise License Agreement dated 2024-03-01\n\n"
        "## 1. Definitions\n"
        'This DPA is entered into between Gamma LLC ("Controller") and NovaBridge Solutions '
        '("Processor") pursuant to Article 28 of the GDPR. Personal data means any data '
        "relating to an identified or identifiable natural person.\n\n"
        "## 2. Scope of Processing\n"
        "Processor shall process personal data solely for the purpose of providing the "
        "NovaBridge Analytics Platform services. Categories of data subjects: Gamma LLC "
        "employees, Gamma LLC customers, Gamma LLC business contacts. "
        "Categories of personal data: name, email, job title, usage analytics, IP address.\n\n"
        "## 3. Sub-Processors\n"
        "Current authorized sub-processors:\n"
        "- Amazon Web Services (EU-Frankfurt) — infrastructure hosting\n"
        "- Snowflake Inc (EU) — data warehousing\n"
        "- Datadog Inc (EU) — monitoring and observability\n\n"
        "Processor shall notify Controller at least 30 days before engaging new sub-processors. "
        "Controller may object within 14 days; if objection is not resolved, Controller may "
        "terminate the Agreement.\n\n"
        "## 4. Data Retention and Deletion\n"
        "Personal data shall be retained for the duration of the Agreement plus 90 days. "
        "Upon termination, Processor shall delete all personal data within 90 days and "
        "provide written certification of deletion. Controller may request data export "
        "in machine-readable format before deletion.\n\n"
        "## 5. Data Subject Rights\n"
        "Processor shall assist Controller in fulfilling data subject access, rectification, "
        "erasure, and portability requests within 10 business days.\n\n"
        "## 6. Security Measures\n"
        "Technical measures: encryption, access controls, audit logging, intrusion detection. "
        "Organizational measures: staff training, background checks, DPO appointment. "
        "Breach notification: within 48 hours of discovery (stricter than GDPR 72-hour requirement).\n\n"
        "## 7. Audit Rights\n"
        "Controller may audit Processor's compliance with this DPA once per calendar year "
        "with 30 days written notice. Processor shall provide access to relevant systems, "
        "records, and personnel. Audit costs borne by Controller unless non-compliance found.\n\n"
        "## 8. International Transfers\n"
        "No personal data shall be transferred outside the EEA without Controller's prior "
        "written consent. If transfer is necessary, Standard Contractual Clauses (SCC) "
        "shall apply. Processor warrants that no government access requests have been "
        "received to date.\n",
        encoding="utf-8",
    )

    # Reference files
    ref = root / "_reference"
    ref.mkdir()
    (ref / "buyer_overview.pdf.md").write_text(
        "# Buyer Company Overview — Meridian Holdings\n\n"
        "## Company Profile\n"
        "- Legal Name: Meridian Holdings, Inc.\n"
        "- Industry: Enterprise SaaS / Business Intelligence\n"
        "- Revenue: $500M ARR\n"
        "- Employees: 2,800\n"
        "- Headquarters: San Francisco, CA\n"
        "- Public/Private: Private (PE-backed, Sequoia Capital)\n\n"
        "## Acquisition Rationale\n"
        "Meridian seeks to acquire NovaBridge Solutions to expand its analytics platform "
        "offering. Key synergies include cross-selling to Meridian's 800+ enterprise clients, "
        "consolidating cloud infrastructure, and integrating NovaBridge's AI capabilities. "
        "Deal thesis: NovaBridge's customer base is complementary (mid-market focus) with "
        "minimal overlap (<5% customer overlap).\n\n"
        "## Strategic Priorities\n"
        "1. Retain NovaBridge's top 20 customers (>80% of revenue)\n"
        "2. Migrate NovaBridge to Meridian's AWS infrastructure within 12 months\n"
        "3. Consolidate sales teams and eliminate redundant G&A\n"
        "4. Cross-sell Meridian BI suite to NovaBridge customers\n\n"
        "## Risk Tolerance\n"
        "Moderate. Meridian will not proceed if material Change of Control termination "
        "rights affect >30% of NovaBridge's ARR.\n",
        encoding="utf-8",
    )

    return root


@pytest.fixture()
def e2e_deal_config(tmp_path: Path, e2e_data_room: Path) -> Path:
    """Create a deal-config.json for E2E testing."""
    config = {
        "config_version": "1.0.0",
        "buyer": {
            "name": "Meridian Holdings",
            "industry": "Enterprise SaaS",
        },
        "target": {
            "name": "NovaBridge Solutions",
            "industry": "Data Analytics Platform",
            "subsidiaries": [],
        },
        "entity_aliases": {
            "canonical_to_variants": {
                "Acme Corp": ["Acme Corporation", "Acme"],
                "Beta Inc": ["Beta Incorporated", "Beta"],
                "Gamma LLC": ["Gamma", "Gamma Limited"],
            },
            "short_name_guard": ["NB"],
            "exclusions": ["N/A", "TBD"],
            "parent_child": {},
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": [
                "change_of_control_clauses",
                "ip_ownership",
                "revenue_recognition",
                "customer_concentration",
                "data_security",
                "technology_stack",
            ],
            "acquisition_date": "2025-03-01",
        },
        "execution": {
            "execution_mode": "full",
            "staleness_threshold": 3,
            "force_full_on_config_change": True,
        },
        "judge": {
            "enabled": True,
            "max_iteration_rounds": 2,
            "score_threshold": 70,
            "sampling_rates": {
                "p0": 1.0,
                "p1": 0.20,
                "p2": 0.10,
                "p3": 0.0,
            },
            "ocr_completeness_check": True,
            "cross_agent_contradiction_check": True,
        },
        "agent_models": {
            "profile": "economy",
        },
        "reporting": {
            "include_diff_sheet": True,
            "include_metadata_sheet": True,
        },
    }

    config_path = tmp_path / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


@pytest.fixture()
def e2e_project_dir(tmp_path: Path, e2e_data_room: Path, e2e_deal_config: Path) -> Path:
    """Set up a complete project directory for E2E testing.

    Copies the data room and config into a single project directory
    that the pipeline engine can work with.
    """
    project = tmp_path / "project"
    shutil.copytree(e2e_data_room, project)
    shutil.copy2(e2e_deal_config, project / "deal-config.json")
    return project


@pytest.fixture(scope="class")
def live_pipeline_result(tmp_path_factory: pytest.TempPathFactory) -> tuple[object, Path]:
    """Run the full pipeline once (all features incl. Judge), share across test class.

    Returns (PipelineState, project_dir). Expensive — runs real agents via API.
    """
    from dd_agents.orchestrator.engine import PipelineEngine

    tmp_path = tmp_path_factory.mktemp("live_e2e")
    root = tmp_path / "data_room"
    root.mkdir()

    # --- Build data room (same content as e2e_data_room but class-scoped) ---
    acme = root / "GroupA" / "Acme Corp"
    acme.mkdir(parents=True)
    (acme / "contract_acme.pdf.md").write_text(
        "# Master Service Agreement - Acme Corp\n\n"
        "Effective Date: 2023-01-15\nTerm: 36 months\nAnnual Value: $120,000\n\n"
        "## Section 1 — Scope of Services\n"
        'NovaBridge Solutions ("Provider") shall deliver the NovaBridge Analytics Platform '
        'to Acme Corp ("Customer"), including data ingestion, dashboarding, and API access. '
        "Provider shall maintain 99.9% uptime SLA measured monthly.\n\n"
        "## Section 2 — Fees and Payment Terms\n"
        "Customer shall pay $10,000 per month, invoiced quarterly in advance. "
        "Late payments incur 1.5% monthly interest. Annual escalation: CPI + 2%, capped at 5%.\n\n"
        "## Section 3 — Intellectual Property\n"
        "All pre-existing IP remains with its owner. Customer data remains Customer property. "
        "Provider retains all rights to the Platform, including improvements derived from "
        "Customer usage patterns. Any custom developments paid for by Customer shall be jointly owned.\n\n"
        "## Section 4 — Change of Control\n"
        "### 4.1 Assignment\n"
        "Neither party may assign this Agreement without prior written consent, "
        "except in connection with a merger, acquisition, or sale of substantially all assets.\n"
        "### 4.2 Auto-Renewal\n"
        "This agreement shall auto-renew for successive 12-month periods "
        "unless either party provides 90 days written notice.\n"
        "### 4.3 Change of Control Termination Right\n"
        "In the event of a Change of Control of Provider, Customer may terminate this "
        "Agreement within 60 days of receiving notice, without penalty.\n\n"
        "## Section 5 — Data Security\n"
        "Provider shall maintain SOC 2 Type II compliance. Customer data encrypted "
        "at rest (AES-256) and in transit (TLS 1.2+). Breach notification within 72 hours.\n\n"
        "## Section 6 — Liability and Indemnification\n"
        "Total aggregate liability: $500,000 or 12 months of fees, whichever is greater. "
        "Provider indemnifies Customer against third-party IP claims. "
        "Consequential damages excluded.\n\n"
        "## Section 7 — Termination\n"
        "Either party may terminate for cause with 30 days written notice after uncured breach. "
        "Upon termination, Provider returns or destroys Customer data within 30 days.\n\n"
        "## Section 8 — Governing Law\n"
        "Governed by Delaware law. Disputes resolved by binding arbitration under AAA rules.\n",
        encoding="utf-8",
    )
    (acme / "invoice_acme_2024.xlsx.md").write_text(
        "# Invoice Summary - Acme Corp 2024\n\n"
        "Account: Acme Corp | Contract #AC-2023-001\nPayment Terms: Net 30 | Currency: USD\n\n"
        "| Invoice # | Date | Period | Amount | Status |\n"
        "|-----------|------|--------|--------|--------|\n"
        "| INV-2024-001 | 2024-01-15 | Q1 2024 | $30,000 | Paid |\n"
        "| INV-2024-002 | 2024-04-15 | Q2 2024 | $30,000 | Paid |\n"
        "| INV-2024-003 | 2024-07-15 | Q3 2024 | $30,000 | Paid |\n"
        "| INV-2024-004 | 2024-10-15 | Q4 2024 | $30,000 | Outstanding - 45 days overdue |\n\n"
        "Total invoiced 2024: $120,000 | Collected: $90,000 | Outstanding: $30,000\n"
        "Prior year (2023): $110,000 | YoY growth: 9.1%\n",
        encoding="utf-8",
    )
    beta = root / "GroupA" / "Beta Inc"
    beta.mkdir(parents=True)
    (beta / "msa_beta.pdf.md").write_text(
        "# Master Service Agreement - Beta Inc\n\n"
        "Start Date: 2022-06-01\nEnd Date: 2025-05-31\nContract Value: $85,000/year\n\n"
        "## Article 1 — License Grant\n"
        "NovaBridge Solutions grants Beta Inc a non-exclusive, non-transferable license "
        "for up to 200 named users. No sublicensing.\n\n"
        "## Article 2 — Fees and Payment\n"
        "Annual fee: $85,000, payable in advance. Implementation: $250/hour T&M. "
        "Support: Premium 24/7, 4-hour response SLA.\n\n"
        "## Article 3 — Intellectual Property\n"
        "Provider retains Platform IP. Customer retains Customer Data IP. "
        "Custom integrations under SOW become Provider IP unless SOW specifies otherwise.\n\n"
        "## Article 4 — Assignment and Change of Control\n"
        "Assignment requires prior written consent. Change of Control of Provider requires "
        "90 days advance notice. Customer may terminate within 120 days of CoC notification "
        "without early termination penalty.\n\n"
        "## Article 5 — Termination\n"
        "Either party may terminate with 60 days notice. Early termination fee: "
        "50% of remaining term value. Data portability: CSV/JSON export within 15 business days.\n\n"
        "## Article 6 — Technology\n"
        "REST API v2+ compatibility. 12 months deprecation notice for breaking changes. "
        "SSO via SAML 2.0 and OAuth 2.0.\n",
        encoding="utf-8",
    )
    (beta / "sow_beta.pdf.md").write_text(
        "# Statement of Work #1 - Beta Inc\n\n"
        "SOW Ref: SOW-BETA-2022-001 | MSA Ref: MSA-BETA-2022\nEffective: 2022-07-15\n\n"
        "## Scope\n"
        "NovaBridge Analytics Platform implementation: data pipeline with Snowflake, "
        "5 executive dashboards, SSO via Okta, Tableau migration.\n\n"
        "## Milestones\n"
        "| Phase | Target | Payment |\n|-------|--------|--------|\n"
        "| Environment & SSO | 2022-08-15 | $15,000 |\n"
        "| Data Pipeline | 2022-09-30 | $25,000 |\n"
        "| Dashboards | 2022-11-15 | $20,000 |\n"
        "| UAT & Go-Live | 2022-12-15 | $10,000 |\n\n"
        "Total: $70,000\n\n"
        "## Technical Requirements\n"
        "Snowflake CDC via Snowpipe Streaming. API: 1,000 req/min. "
        "Retention: 7 years. DR: RPO 1hr, RTO 4hr.\n\n"
        "## IP\n"
        "Custom dashboards are Provider IP (per MSA). Beta gets perpetual license. "
        "Data pipeline connectors open-sourced (Apache 2.0).\n",
        encoding="utf-8",
    )
    gamma = root / "GroupB" / "Gamma LLC"
    gamma.mkdir(parents=True)
    (gamma / "license_gamma.docx.md").write_text(
        "# Enterprise Software License Agreement - Gamma LLC\n\n"
        "License Type: Enterprise | Seats: 500 | Annual Fee: $200,000\n"
        "Effective: 2024-03-01 | Term: 24 months\n\n"
        "## 1. License Scope\n"
        "Enterprise license for NovaBridge Analytics Platform, 500 named users. "
        "Overage: $400/user/year.\n\n"
        "## 2. Fees\n"
        "Annual: $200,000 semi-annually. Professional services: $300/hr. "
        "10% renewal discount if paid annually.\n\n"
        "## 3. SLA\n"
        "99.95% monthly availability. Downtime credits: 5%/hour beyond SLA, max 30%.\n\n"
        "## 4. Data Security\n"
        "SOC 2 Type II, ISO 27001, GDPR. EU hosting (Frankfurt). "
        "AES-256 at rest, TLS 1.3 in transit. $5M cyber liability insurance.\n\n"
        "## 5. Change of Control\n"
        "Provider must notify within 15 business days of CoC. Customer may terminate "
        "within 90 days without penalty; pro-rata refund of prepaid fees.\n\n"
        "## 6. Liability\n"
        "Aggregate cap: lesser of $1,000,000 or 2x annual fees. "
        "Exceptions: IP indemnification, data breach, gross negligence.\n\n"
        "## 7. IP\n"
        "Platform IP: Provider. Customer Data: Customer. "
        "Provider may use anonymized aggregated usage data.\n\n"
        "## 8. Governing Law\n"
        "Laws of England and Wales. London Commercial Court.\n",
        encoding="utf-8",
    )
    (gamma / "data_processing_gamma.pdf.md").write_text(
        "# Data Processing Agreement - Gamma LLC\n\n"
        "DPA Effective: 2024-03-01 | Per GDPR Article 28\n\n"
        "## Scope\n"
        "Processor (NovaBridge) processes personal data for Controller (Gamma LLC). "
        "Data subjects: employees, customers, contacts. "
        "Data categories: name, email, job title, usage analytics, IP address.\n\n"
        "## Sub-Processors\n"
        "- AWS (EU-Frankfurt) — hosting\n- Snowflake (EU) — data warehouse\n"
        "- Datadog (EU) — monitoring\n"
        "30 days notice before new sub-processors. 14 days to object.\n\n"
        "## Retention\n"
        "Duration of Agreement + 90 days. Deletion certification provided. "
        "Export in machine-readable format on request.\n\n"
        "## Security\n"
        "Encryption, access controls, audit logging, intrusion detection. "
        "Breach notification: 48 hours (stricter than GDPR 72-hour).\n\n"
        "## Audit Rights\n"
        "Annual audit with 30 days notice. Costs borne by Controller unless non-compliance found.\n\n"
        "## International Transfers\n"
        "No transfers outside EEA without written consent. SCCs apply if needed.\n",
        encoding="utf-8",
    )
    ref = root / "_reference"
    ref.mkdir()
    (ref / "buyer_overview.pdf.md").write_text(
        "# Buyer Overview — Meridian Holdings\n\n"
        "Enterprise SaaS / BI. $500M ARR, 2,800 employees, PE-backed. "
        "Acquiring NovaBridge for analytics expansion. "
        "Cross-sell to 800+ enterprise clients, consolidate infra, integrate AI. "
        "<5% customer overlap. Risk tolerance: moderate — will not proceed if CoC "
        "termination rights affect >30% of NovaBridge ARR.\n",
        encoding="utf-8",
    )

    # --- Build deal config ---
    config = {
        "config_version": "1.0.0",
        "buyer": {"name": "Meridian Holdings", "industry": "Enterprise SaaS"},
        "target": {
            "name": "NovaBridge Solutions",
            "industry": "Data Analytics Platform",
            "subsidiaries": [],
        },
        "entity_aliases": {
            "canonical_to_variants": {
                "Acme Corp": ["Acme Corporation", "Acme"],
                "Beta Inc": ["Beta Incorporated", "Beta"],
                "Gamma LLC": ["Gamma", "Gamma Limited"],
            },
            "short_name_guard": ["NB"],
            "exclusions": ["N/A", "TBD"],
            "parent_child": {},
        },
        "deal": {
            "type": "acquisition",
            "focus_areas": [
                "change_of_control_clauses",
                "ip_ownership",
                "revenue_recognition",
                "customer_concentration",
                "data_security",
                "technology_stack",
            ],
            "acquisition_date": "2025-03-01",
        },
        "execution": {
            "execution_mode": "full",
            "staleness_threshold": 3,
            "force_full_on_config_change": True,
        },
        "judge": {
            "enabled": True,
            "max_iteration_rounds": 2,
            "score_threshold": 70,
            "sampling_rates": {"p0": 1.0, "p1": 0.20, "p2": 0.10, "p3": 0.0},
            "ocr_completeness_check": True,
            "cross_agent_contradiction_check": True,
        },
        "agent_models": {"profile": "economy"},
        "reporting": {"include_diff_sheet": True, "include_metadata_sheet": True},
    }
    project = tmp_path / "project"
    shutil.copytree(root, project)
    config_path = project / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # --- Run pipeline with live progress ---
    # Enable live logging so step progress is visible during the run.
    # The engine logs "Step N/35: step_name" via dd_agents.orchestrator.engine.
    root_logger = logging.getLogger("dd_agents")
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    print("\n" + "=" * 70)
    print("LIVE E2E: Starting full pipeline (all features, Judge enabled)")
    print(f"  Project dir: {project}")
    print("=" * 70, flush=True)

    t0 = time.monotonic()
    engine = PipelineEngine(project_dir=project, deal_config_path=config_path)
    state = asyncio.run(engine.run(resume_from_step=0))
    elapsed = time.monotonic() - t0

    print("=" * 70)
    print(f"LIVE E2E: Pipeline finished in {elapsed:.0f}s — {len(state.completed_steps)} steps completed")
    print("=" * 70 + "\n", flush=True)

    root_logger.removeHandler(handler)

    return state, project
