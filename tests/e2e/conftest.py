"""E2E test fixtures and shared setup.

E2E tests require:
- A valid ANTHROPIC_API_KEY environment variable
- Network access for Claude API calls
- A sample data room directory

Mark all E2E tests with @pytest.mark.e2e so they can be skipped
in CI or local runs without API credentials.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path  # noqa: TC003

import pytest


def _has_api_key() -> bool:
    """Check if an Anthropic API key is available."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


skip_no_api_key = pytest.mark.skipif(
    not _has_api_key(),
    reason="ANTHROPIC_API_KEY not set; skipping E2E test",
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
          GroupB/
            Gamma LLC/
              license_gamma.docx.md
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
        "## Clause 4.2 - Auto-Renewal\n"
        "This agreement shall auto-renew for successive 12-month periods "
        "unless either party provides 90 days written notice.\n\n"
        "## Clause 7.1 - Liability Cap\n"
        "Total liability shall not exceed $500,000.\n"
    )
    (acme / "invoice_acme_2024.xlsx.md").write_text(
        "# Invoice Summary - Acme Corp 2024\n\n"
        "| Date | Amount | Description |\n"
        "|------|--------|-------------|\n"
        "| 2024-01-15 | $10,000 | Monthly subscription |\n"
        "| 2024-02-15 | $10,000 | Monthly subscription |\n"
        "| 2024-03-15 | $10,000 | Monthly subscription |\n"
    )

    # GroupA / Beta Inc
    beta = root / "GroupA" / "Beta Inc"
    beta.mkdir(parents=True)
    (beta / "msa_beta.pdf.md").write_text(
        "# Service Agreement - Beta Inc\n\n"
        "Start Date: 2022-06-01\n"
        "End Date: 2025-05-31\n"
        "Contract Value: $85,000/year\n\n"
        "## Section 3 - Termination\n"
        "Either party may terminate with 60 days notice.\n"
        "Early termination fee: 50% of remaining term value.\n"
    )

    # GroupB / Gamma LLC
    gamma = root / "GroupB" / "Gamma LLC"
    gamma.mkdir(parents=True)
    (gamma / "license_gamma.docx.md").write_text(
        "# Software License Agreement - Gamma LLC\n\n"
        "License Type: Enterprise\n"
        "Seats: 500\n"
        "Annual Fee: $200,000\n\n"
        "## IP Assignment\n"
        "All intellectual property remains with the licensor.\n"
    )

    # Reference files
    ref = root / "_reference"
    ref.mkdir()
    (ref / "buyer_overview.pdf.md").write_text(
        "# Buyer Company Overview\n\nCompany: Meridian Holdings\nIndustry: Enterprise SaaS\nRevenue: $500M ARR\n"
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
        "deal": {
            "type": "acquisition",
            "focus_areas": ["legal", "financial", "commercial"],
            "acquisition_date": "2025-03-01",
        },
        "execution": {
            "execution_mode": "full",
            "staleness_threshold": 3,
            "force_full_on_config_change": True,
        },
        "judge": {
            "enabled": False,
            "max_iteration_rounds": 1,
            "score_threshold": 70,
        },
        "reporting": {
            "include_diff_sheet": True,
            "include_metadata_sheet": True,
        },
    }

    config_path = tmp_path / "deal-config.json"
    config_path.write_text(json.dumps(config, indent=2))
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
