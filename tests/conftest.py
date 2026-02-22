"""Shared test fixtures for the dd-agents test suite."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_config_dict() -> dict[str, Any]:
    """Full realistic deal config."""
    return json.loads((FIXTURES_DIR / "deal_config_valid.json").read_text())


@pytest.fixture
def minimal_config_dict() -> dict[str, Any]:
    """Minimal valid config with only required fields."""
    return json.loads((FIXTURES_DIR / "deal_config_minimal.json").read_text())


@pytest.fixture
def invalid_config_dict() -> dict[str, Any]:
    """Config with intentional violations for negative testing."""
    return json.loads((FIXTURES_DIR / "deal_config_invalid.json").read_text())


# ---------------------------------------------------------------------------
# Data room fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_data_room_path(tmp_path: Path) -> Path:
    """Copy sample data room to a temp directory for isolated testing.

    Returns the temp directory path with the data room contents and a
    deal-config.json copied alongside.
    """
    src = FIXTURES_DIR / "sample_data_room"
    dst = tmp_path / "data_room"
    if src.exists():
        shutil.copytree(src, dst)
    else:
        # If sample_data_room doesn't exist yet, create a minimal structure
        dst.mkdir(parents=True)
    # Copy valid config as the deal config
    config_src = FIXTURES_DIR / "deal_config_valid.json"
    if config_src.exists():
        shutil.copy(config_src, dst / "deal-config.json")
    return dst


# ---------------------------------------------------------------------------
# Agent output fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_agent_outputs() -> dict[str, dict[str, Any]]:
    """Pre-recorded agent outputs for integration tests.

    Returns a nested dict: {agent_name: {customer_name: output_dict}}.
    """
    outputs: dict[str, dict[str, Any]] = {}
    outputs_dir = FIXTURES_DIR / "sample_agent_outputs"
    if not outputs_dir.exists():
        return outputs
    for agent_dir in outputs_dir.iterdir():
        if agent_dir.is_dir():
            outputs[agent_dir.name] = {}
            for f in agent_dir.glob("*.json"):
                outputs[agent_dir.name][f.stem] = json.loads(f.read_text())
    return outputs


# ---------------------------------------------------------------------------
# Entity resolution fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_customer_list() -> list[str]:
    """Standard customer list for entity resolution tests."""
    return [
        "Acme Corporation",
        "Global Analytics Group",
        "Acme Holdings",
        "Globex Corp",
        "Alpine Systems Inc.",
        "Meridian Partners LLC",
    ]


# ---------------------------------------------------------------------------
# Finding fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_finding_dict() -> dict[str, Any]:
    """A valid finding dict that should pass Finding model validation."""
    return {
        "id": "forensic-dd_legal_acme_corporation_0001",
        "customer": "Acme Corporation",
        "customer_safe_name": "acme_corporation",
        "agent": "legal",
        "domain": "change_of_control",
        "title": "Change of control clause allows termination without cure period",
        "severity": "P1",
        "description": (
            "Section 12.3 of the MSA grants the customer the right to terminate "
            "the agreement upon a change of control event with no cure period."
        ),
        "citation": {
            "source_path": "Acme_Corporation/MSA_2023.pdf",
            "page": 15,
            "exact_quote": (
                "In the event of a Change of Control, Customer may terminate "
                "this Agreement immediately upon written notice."
            ),
        },
        "recommendation": "Negotiate a 90-day cure period before termination right triggers.",
        "financial_impact": "$1.2M ARR at risk",
    }


# ---------------------------------------------------------------------------
# Report schema fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def report_schema() -> dict[str, Any]:
    """The report_schema.json loaded as a dict."""
    schema_path = Path(__file__).parent.parent / "config" / "report_schema.json"
    if schema_path.exists():
        return json.loads(schema_path.read_text())
    return {}
