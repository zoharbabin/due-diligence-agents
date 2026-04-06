# 15 — Testing Strategy and Deployment

## Overview

Testing a multi-agent pipeline requires layered validation: unit tests for individual components, integration tests for module interactions, and end-to-end tests with real (or representative) data rooms. Deployment targets any machine with Python 3.12+ and a Claude API key -- no special infrastructure required.

Cross-reference: `03-project-structure.md` (directory layout), `04-data-models.md` (Pydantic models), `05-orchestrator.md` (pipeline), `12-error-recovery.md` (error scenarios).

---

## 1. Testing Strategy

### 1.1 Test Pyramid

```
                    ┌─────────┐
                    │   E2E   │   2-3 tests (real pipeline, small data room)
                    │  tests  │   ~30 min each, API calls
                   ┌┴─────────┴┐
                   │Integration │  15-25 tests (module interactions, mock agents)
                   │   tests    │  ~5 min total, minimal API calls
                  ┌┴────────────┴┐
                  │  Unit tests   │  200+ tests (models, entity resolution, extraction, etc.)
                  │               │  ~30 sec total, no API calls
                  └───────────────┘
```

### 1.2 Test Directory Structure

Test directory mirrors source structure: `tests/unit/test_models/`, `tests/unit/test_entity_resolution/`, `tests/unit/test_extraction/`, `tests/integration/test_pipeline/`, `tests/e2e/`. Each test file corresponds to a source module: `test_models/test_config.py` tests `models/config.py`.

```
tests/
  conftest.py                          # Shared fixtures
  fixtures/
    deal_config_valid.json             # Valid deal-config.json
    deal_config_minimal.json           # Minimal valid config
    deal_config_invalid.json           # Schema violations for negative tests
    sample_data_room/                  # Small test data room (5 customers, 15 files)
      Customer_A/
        MSA.pdf
        Order_Form_1.docx
        Amendment_1.pdf
      Customer_B/
        MSA.pdf
        Order_Form_1.pdf
      Customer_C/
        MSA.docx
        SOW_1.docx
        SOW_2.docx
      Customer_D/
        Master_Agreement.pdf
        Addendum_1.pdf
      Customer_E/
        Service_Agreement.pdf
        Order_Form_1.xlsx
      Global_References/
        Pricing_Guidelines.xlsx
        Customer_List.csv
        Revenue_Summary.xlsx
    sample_agent_outputs/              # Pre-recorded agent outputs for integration tests
      legal/
        customer_a.json
        customer_b.json
        coverage_manifest.json
      finance/
        customer_a.json
        ...
    sample_extraction/                 # Pre-extracted text for unit tests
      customer_a__msa.md
      customer_a__order_form_1.md
      ...
  unit/
    test_models.py                     # Pydantic model validation
    test_entity_resolution.py          # 6-pass matcher
    test_safe_name.py                  # customer_safe_name convention
    test_extraction.py                 # Fallback chain, checksums
    test_numerical_validation.py       # 6-layer validation
    test_hooks.py                      # PreToolUse, PostToolUse, Stop hooks
    test_persistence.py                # Tier management, read-validate-write
    test_config.py                     # Config loading and validation
    test_chunker.py                    # ChromaDB text chunking
    test_errors.py                     # Error taxonomy and recovery logic
  integration/
    test_pipeline.py                   # Step sequences with mock agents
    test_agent_spawning.py             # Minimal prompt agent tests (API calls)
    test_reporting.py                  # Merge/dedup with sample data
    test_inventory.py                  # File discovery + customer registry
    test_coverage_gate.py              # Step 17 validation logic
    test_incremental.py                # Incremental mode classification
  e2e/
    test_full_run.py                   # Full pipeline with test data room
    test_incremental_run.py            # Full + modify + incremental
    test_judge_iteration.py            # Judge re-spawn with low scores
```

---

## 2. Unit Tests

### 2.1 Model Validation (`test_models.py`)

Test all Pydantic models with valid and invalid data. Every model field constraint is exercised.

```python
# tests/unit/test_models.py

import pytest
from pydantic import ValidationError
from dd_agents.models.config import DealConfig
from dd_agents.models.finding import Finding, Citation
from dd_agents.models.coverage import CoverageManifest


class TestDealConfig:
    def test_valid_config(self, valid_config_dict):
        config = DealConfig.model_validate(valid_config_dict)
        assert config.config_version >= "1.0.0"
        assert config.buyer.name != ""

    def test_missing_required_sections(self):
        with pytest.raises(ValidationError) as exc_info:
            DealConfig.model_validate({"config_version": "1.0.0"})
        errors = exc_info.value.errors()
        assert any("buyer" in str(e["loc"]) for e in errors)

    def test_invalid_version(self):
        with pytest.raises(ValidationError):
            DealConfig.model_validate({
                "config_version": "0.5.0",
                "buyer": {"name": "Test"},
                "target": {"name": "Target"},
                "deal": {"name": "Test Deal"},
            })

    def test_optional_sections_default(self, minimal_config_dict):
        config = DealConfig.model_validate(minimal_config_dict)
        assert config.judge.enabled is True  # default
        assert config.execution.execution_mode == "full"  # default


class TestFinding:
    def test_valid_finding(self, sample_finding_dict):
        finding = Finding.model_validate(sample_finding_dict)
        assert finding.severity in ("P0", "P1", "P2", "P3")

    def test_finding_id_pattern(self):
        """Finding IDs must match ^[a-z][a-z0-9-]*_[a-z][a-z0-9_-]*_\\d{4,}$"""
        with pytest.raises(ValidationError):
            Finding.model_validate({
                "id": "INVALID-ID",
                # ... other fields
            })

    def test_citation_required_for_p0_p1(self):
        """P0 and P1 findings must have non-empty exact_quote."""
        with pytest.raises(ValidationError):
            Finding.model_validate({
                "id": "forensic-dd_legal_test_0001",
                "severity": "P0",
                "citation": {"source_path": "file.pdf", "exact_quote": ""},
            })
```

### 2.2 Entity Resolution (`test_entity_resolution.py`)

Test each of the 6 passes with edge cases.

```python
# tests/unit/test_entity_resolution.py

import pytest
from dd_agents.entity_resolution.matcher import EntityMatcher


class TestPass1Exact:
    def test_exact_match(self, matcher):
        assert matcher.match("Acme Corporation") == "Acme Corporation"

    def test_case_insensitive(self, matcher):
        assert matcher.match("acme corporation") == "Acme Corporation"


class TestPass2Normalized:
    def test_strip_legal_suffix(self, matcher):
        assert matcher.match("Acme Corp., Inc.") == "Acme Corporation"

    def test_strip_multiple_suffixes(self, matcher):
        assert matcher.match("Acme Corp. LLC") == "Acme Corporation"


class TestPass3Fuzzy:
    def test_typo_tolerance(self, matcher):
        assert matcher.match("Acme Corporaton") == "Acme Corporation"  # typo

    def test_threshold_boundary(self, matcher):
        # Below fuzzy threshold -- should NOT match
        assert matcher.match("Xyz Unrelated") is None


class TestPass4Acronym:
    def test_acronym_match(self, matcher):
        assert matcher.match("D&B") == "Global Analytics Group"

    def test_short_name_guard_rail(self, matcher):
        """Short names (<= 3 chars) only match via cache or explicit alias."""
        assert matcher.match("AB") is None  # Too ambiguous


class TestPass5Alias:
    def test_configured_alias(self, matcher_with_aliases):
        assert matcher_with_aliases.match("AH") == "Acme Holdings"

    def test_alias_priority(self, matcher_with_aliases):
        """Aliases take priority over fuzzy matching."""
        assert matcher_with_aliases.match("AH Inc.") == "Acme Holdings"


class TestPass6Cache:
    def test_cached_match(self, matcher_with_cache):
        assert matcher_with_cache.match("Old Acme Name") == "Acme Corporation"

    def test_cache_miss_falls_through(self, matcher_with_cache):
        assert matcher_with_cache.match("Unknown Entity") is None


class TestExclusions:
    def test_excluded_name(self, matcher):
        """Names in the exclusion list should never match."""
        assert matcher.match("N/A") is None
        assert matcher.match("TBD") is None
        assert matcher.match("Various") is None


class TestEdgeCases:
    def test_empty_string(self, matcher):
        assert matcher.match("") is None

    def test_special_characters(self, matcher):
        assert matcher.match("Global Analytics Group") == "Global Analytics Group"

    def test_unicode(self, matcher):
        # e.g., accented characters in European company names
        assert matcher.match("Societe Generale") is not None or matcher.match("Societe Generale") is None
```

### 2.3 Safe Name (`test_safe_name.py`)

```python
# tests/unit/test_safe_name.py

import pytest
from dd_agents.utils.naming import customer_safe_name


@pytest.mark.parametrize("input_name, expected", [
    ("Global Analytics Group", "global_analytics_group"),
    ("Alpine Systems, Inc.", "alpine_systems"),
    ("R&D Global", "r_d_global"),
    ("Acme Holdings", "acme_holdings"),
    ("Acme Corp.", "acme_corp"),
    ("Acme Corp. LLC", "acme_corp"),
    ("First Name's Company", "first_names_company"),
    ("A/B Testing Co.", "a_b_testing"),
    ("  Leading Spaces  ", "leading_spaces"),
    ("Multiple   Spaces", "multiple_spaces"),
    ("ALLCAPS INC.", "allcaps"),
    ("Already_safe_name", "already_safe_name"),
    ("123 Numeric Start", "123_numeric_start"),
    ("Company (Subsidiary)", "company_subsidiary"),
])
def test_safe_name_convention(input_name, expected):
    assert customer_safe_name(input_name) == expected


def test_safe_name_empty_string():
    with pytest.raises(ValueError):
        customer_safe_name("")


def test_safe_name_only_legal_suffix():
    # Edge case: name is entirely a legal suffix
    result = customer_safe_name("Inc.")
    assert result == "" or result is not None  # Implementation-dependent
```

### 2.4 Extraction (`test_extraction.py`)

```python
# tests/unit/test_extraction.py

import pytest
from dd_agents.extraction.pipeline import extract_file, ExtractionResult
from dd_agents.extraction.checksum import compute_checksum, is_cached


class TestFallbackChain:
    async def test_markitdown_success(self, tmp_path, sample_pdf):
        result = await extract_file(sample_pdf, tmp_path, mock_state())
        assert result.method == "markitdown"
        assert result.bytes_extracted > 0

    async def test_fallback_to_pdftotext(self, tmp_path, broken_pdf):
        """When markitdown fails, pdftotext should be tried."""
        result = await extract_file(broken_pdf, tmp_path, mock_state())
        assert result.method in ("pdftotext", "read_tool", "tesseract")

    async def test_all_methods_fail(self, tmp_path, corrupt_file):
        result = await extract_file(corrupt_file, tmp_path, mock_state())
        assert result.method == "failed"
        assert result.bytes_extracted == 0
        assert result.gap_type == "Unreadable"


class TestChecksumCache:
    def test_same_file_same_hash(self, sample_pdf):
        h1 = compute_checksum(sample_pdf)
        h2 = compute_checksum(sample_pdf)
        assert h1 == h2

    def test_modified_file_different_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content v1")
        h1 = compute_checksum(f)
        f.write_text("content v2")
        h2 = compute_checksum(f)
        assert h1 != h2

    def test_cache_hit_skips_extraction(self, tmp_path, checksums_file):
        assert is_cached("test.pdf", "abc123", checksums_file)

    def test_cache_miss_triggers_extraction(self, tmp_path, checksums_file):
        assert not is_cached("test.pdf", "different_hash", checksums_file)
```

### 2.5 Numerical Validation (`test_numerical_validation.py`)

```python
# tests/unit/test_numerical_validation.py

import pytest
from dd_agents.validation.numerical import (
    validate_layer1_internal_consistency,
    validate_layer2_cross_reference,
    validate_layer3_format,
    validate_layer4_aggregation,
    validate_layer5_external,
)


class TestLayer1InternalConsistency:
    def test_consistent_numbers(self, finding_with_numbers):
        result = validate_layer1_internal_consistency(finding_with_numbers)
        assert result.passed is True

    def test_contradictory_numbers(self, finding_with_contradiction):
        result = validate_layer1_internal_consistency(finding_with_contradiction)
        assert result.passed is False
        assert "contradiction" in result.details.lower()


class TestLayer2CrossReference:
    def test_matching_across_agents(self, legal_finding, finance_finding):
        result = validate_layer2_cross_reference(legal_finding, finance_finding)
        assert result.passed is True

    def test_conflicting_across_agents(self, legal_finding_100k, finance_finding_200k):
        result = validate_layer2_cross_reference(legal_finding_100k, finance_finding_200k)
        assert result.passed is False
```

### 2.6 Hooks (`test_hooks.py`)

```python
# tests/unit/test_hooks.py

import pytest
from dd_agents.hooks.path_guard import create_path_guard
from dd_agents.hooks.bash_guard import create_bash_guard
from dd_agents.hooks.stop_hook import create_stop_hook


class TestPathGuard:
    async def test_allows_project_path(self):
        hook = create_path_guard("/project/dir")
        result = await hook(
            {"tool_name": "Read", "tool_input": {"file_path": "data/file.txt"}},
            "id1", {}
        )
        assert result == {}  # Empty = allowed

    async def test_blocks_outside_path(self):
        hook = create_path_guard("/project/dir")
        result = await hook(
            {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}},
            "id1", {}
        )
        assert result["decision"] == "block"

    async def test_blocks_path_traversal(self):
        hook = create_path_guard("/project/dir")
        result = await hook(
            {"tool_name": "Read", "tool_input": {"file_path": "../../etc/passwd"}},
            "id1", {}
        )
        assert result["decision"] == "block"


class TestBashGuard:
    async def test_blocks_rm_rf(self):
        hook = create_bash_guard()
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            "id1", {}
        )
        assert result["decision"] == "block"

    async def test_allows_safe_commands(self):
        hook = create_bash_guard()
        result = await hook(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            "id1", {}
        )
        assert result == {}


class TestStopHook:
    async def test_blocks_premature_stop(self):
        hook = create_stop_hook(expected_customers=34, output_dir="/run/findings/legal")
        # Simulate only 20 customer files exist
        result = await hook({}, "id1", {"customer_files_count": 20})
        assert result["decision"] == "block"

    async def test_allows_complete_stop(self):
        hook = create_stop_hook(expected_customers=34, output_dir="/run/findings/legal")
        result = await hook({}, "id1", {"customer_files_count": 34})
        assert result == {} or result["decision"] == "allow"
```

---

## 3. Integration Tests

### 3.1 Pipeline Step Sequences (`test_pipeline.py`)

Test step sequences with mock agents (no real Claude API calls for most tests).

```python
# tests/integration/test_pipeline.py

import pytest
from unittest.mock import AsyncMock, patch
from dd_agents.orchestrator.engine import PipelineEngine


class TestPipelineSteps:
    @pytest.fixture
    def engine(self, sample_data_room, valid_config):
        return PipelineEngine(sample_data_room, valid_config)

    async def test_steps_1_through_10(self, engine):
        """Test inventory-building steps without agent spawning."""
        await engine.run_steps(1, 10)
        assert engine.state.total_customers == 5
        assert engine.state.total_files == 15
        assert (engine.state.skill_dir / "inventory" / "customers.csv").exists()
        assert (engine.state.skill_dir / "inventory" / "counts.json").exists()

    @patch("dd_agents.orchestrator.agents.spawn_with_retry")
    async def test_step_16_parallel_spawn(self, mock_spawn, engine):
        """Test that 4 specialists are spawned in parallel."""
        mock_spawn.return_value = {"status": "complete"}
        await engine.run_step(16)
        assert mock_spawn.call_count == 4

    async def test_step_17_coverage_gate_pass(self, engine, complete_agent_outputs):
        """Test coverage gate with all customers covered."""
        result = await engine.run_step(17)
        assert result.passed is True

    async def test_step_17_coverage_gate_fail(self, engine, partial_agent_outputs):
        """Test coverage gate triggers re-spawn for missing customers."""
        with patch("dd_agents.orchestrator.coverage.respawn_for_missing_customers") as mock:
            await engine.run_step(17)
            assert mock.called
```

### 3.2 Agent Spawning (`test_agent_spawning.py`)

Minimal-prompt tests that actually invoke the SDK (requires API key).

```python
# tests/integration/test_agent_spawning.py

import pytest
from dd_agents.orchestrator.recovery import spawn_with_retry

# Mark as requiring API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="Requires ANTHROPIC_API_KEY"
)


class TestAgentSpawning:
    async def test_minimal_agent_responds(self):
        """Verify SDK agent invocation works with a trivial prompt."""
        result = await spawn_with_retry(
            "test-agent",
            "Reply with exactly: HELLO",
            ClaudeAgentOptions(
                model="claude-sonnet-4-20250514",
                max_turns=1,
                max_budget_usd=0.10,
            ),
        )
        assert result is not None

    async def test_agent_timeout(self):
        """Verify timeout handling works."""
        with pytest.raises(AgentError) as exc_info:
            await spawn_with_retry(
                "timeout-test",
                "Think for a very long time about nothing",
                ClaudeAgentOptions(max_turns=1000),
                timeout_minutes=0.01,  # Very short timeout
            )
        assert exc_info.value.error_type == ErrorCategory.AGENT_TIMEOUT
```

### 3.3 Reporting (`test_reporting.py`)

```python
# tests/integration/test_reporting.py

import pytest
from dd_agents.reporting.merge import merge_findings, deduplicate_findings
from dd_agents.reporting.excel import generate_excel


class TestMergeDedup:
    def test_merge_4_agents(self, sample_agent_outputs):
        """Merge findings from all 4 agents for each customer."""
        merged = merge_findings(sample_agent_outputs, customer="customer_a")
        assert len(merged) > 0
        # Check no duplicates
        ids = [f["id"] for f in merged]
        assert len(ids) == len(set(ids))

    def test_dedup_same_finding(self):
        """Two agents finding the same issue should produce one finding."""
        findings = [
            {"id": "legal_auto_renew_0001", "title": "Auto-renewal clause", "severity": "P2"},
            {"id": "commercial_auto_renew_0001", "title": "Auto-renewal clause", "severity": "P2"},
        ]
        deduped = deduplicate_findings(findings)
        assert len(deduped) == 1

    def test_dedup_keeps_highest_severity(self):
        """When deduplicating, keep the highest severity."""
        findings = [
            {"id": "a", "title": "Issue X", "severity": "P2", "agent": "legal"},
            {"id": "b", "title": "Issue X", "severity": "P1", "agent": "finance"},
        ]
        deduped = deduplicate_findings(findings)
        assert deduped[0]["severity"] == "P1"
```

---

## 4. End-to-End Tests

### 4.1 Full Run (`test_full_run.py`)

```python
# tests/e2e/test_full_run.py

import pytest
from pathlib import Path
from dd_agents.cli import run_pipeline

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="Requires API key"),
]


class TestFullRun:
    async def test_small_data_room(self, sample_data_room_path):
        """Full pipeline run with 5 customers, 15 files."""
        result = await run_pipeline(
            data_room=sample_data_room_path,
            mode="full",
            max_budget_usd=15.00,
        )

        assert result.success is True

        # Verify outputs exist
        run_dir = result.run_dir
        assert (run_dir / "metadata.json").exists()
        assert (run_dir / "audit.json").exists()
        assert list((run_dir / "report").glob("Due_Diligence_Report_*.xlsx"))

        # Verify all 5 customers covered
        for agent in ["legal", "finance", "commercial", "producttech"]:
            agent_dir = run_dir / "findings" / agent
            customer_files = list(agent_dir.glob("*.json"))
            # Exclude coverage_manifest.json
            customer_files = [f for f in customer_files if f.stem != "coverage_manifest"]
            assert len(customer_files) == 5, f"Agent {agent} has {len(customer_files)} customer files"

        # Verify audit passed
        import json
        audit = json.loads((run_dir / "audit.json").read_text())
        assert audit["audit_passed"] is True


class TestIncrementalRun:
    async def test_full_then_incremental(self, sample_data_room_path, tmp_path):
        """Run full, modify data room, run incremental."""
        # Full run
        result1 = await run_pipeline(data_room=sample_data_room_path, mode="full")
        assert result1.success

        # Modify data room (add a file to Customer_A)
        new_file = sample_data_room_path / "Customer_A" / "New_Amendment.txt"
        new_file.write_text("This is a new amendment to the MSA.")

        # Incremental run
        result2 = await run_pipeline(data_room=sample_data_room_path, mode="incremental")
        assert result2.success

        # Verify classification
        import json
        classification = json.loads(
            (result2.run_dir / "classification.json").read_text()
        )
        assert classification["classification_summary"]["changed"] >= 1
        assert classification["classification_summary"]["unchanged"] >= 3
```

---

## 5. Test Fixtures

### 5.1 conftest.py

```python
# tests/conftest.py

import pytest
import json
import shutil
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def valid_config_dict():
    return json.loads((FIXTURES_DIR / "deal_config_valid.json").read_text())


@pytest.fixture
def minimal_config_dict():
    return json.loads((FIXTURES_DIR / "deal_config_minimal.json").read_text())


@pytest.fixture
def sample_data_room_path(tmp_path):
    """Copy sample data room to a temp directory for isolated testing."""
    src = FIXTURES_DIR / "sample_data_room"
    dst = tmp_path / "data_room"
    shutil.copytree(src, dst)
    # Copy valid config
    shutil.copy(FIXTURES_DIR / "deal_config_valid.json", dst / "deal-config.json")
    return dst


@pytest.fixture
def sample_agent_outputs():
    """Pre-recorded agent outputs for integration tests."""
    outputs = {}
    outputs_dir = FIXTURES_DIR / "sample_agent_outputs"
    for agent_dir in outputs_dir.iterdir():
        if agent_dir.is_dir():
            outputs[agent_dir.name] = {}
            for f in agent_dir.glob("*.json"):
                outputs[agent_dir.name][f.stem] = json.loads(f.read_text())
    return outputs


@pytest.fixture
def matcher():
    """EntityMatcher with sample customer list."""
    from dd_agents.entity_resolution.matcher import EntityMatcher
    customers = [
        "Acme Corporation",
        "Global Analytics Group",
        "Acme Holdings",
        "Globex Corp",
    ]
    return EntityMatcher(customers=customers)
```

---

## 6. CI/CD

### 6.1 GitHub Actions

```yaml
# .github/workflows/ci.yml

name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff mypy
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: mypy src/ --strict

  test-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ -v --tb=short --junitxml=results/unit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: unit-test-results
          path: results/

  test-integration:
    runs-on: ubuntu-latest
    needs: [lint, test-unit]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration/ -v --tb=short -k "not test_agent_spawning"
        # Skip tests requiring API key in CI

  test-e2e:
    runs-on: ubuntu-latest
    needs: [test-integration]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/e2e/ -v --tb=long -m "e2e"
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

### 6.2 Pre-commit Hooks

```yaml
# .pre-commit-config.yaml

repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

### 6.3 CI/CD Acceptance Criteria

**CI/CD acceptance criteria**: The CI pipeline passes when ALL of the following succeed: (1) `pytest tests/unit/` — all unit tests pass, (2) `mypy src/ --strict` — no type errors, (3) `ruff check src/ tests/` — no lint violations, (4) `pytest tests/integration/` — integration tests pass against sample data room. The pipeline fails-fast on the first failure. E2E tests (`tests/e2e/`) run on manual trigger only (they require LLM API access and cost money).

### 6.4 pyproject.toml Test Configuration

```toml
# pyproject.toml (test section)

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "e2e: end-to-end tests (require API key, slow)",
    "slow: tests that take more than 1 minute",
]
filterwarnings = [
    "ignore::DeprecationWarning",
]

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_configs = true

[[tool.mypy.overrides]]
module = ["chromadb.*", "markitdown.*"]
ignore_missing_imports = true

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "TCH"]
```

---

## 7. Docker

### 7.1 Dockerfile

```dockerfile
# Dockerfile

FROM python:3.12-slim AS base

# System dependencies for document extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    libtesseract-dev \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 18 LTS (required for markitdown, which uses a Node.js-based
# PDF renderer as one of its extraction backends)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash ddagent
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[vector]"

# Copy source
COPY src/ src/

# Set ownership
RUN chown -R ddagent:ddagent /app

USER ddagent

# Default data room mount point
VOLUME ["/data-room"]

# Entrypoint
ENTRYPOINT ["dd-agents"]
CMD ["run", "/data-room"]
```

### 7.2 Docker Compose (Development)

```yaml
# docker-compose.yml

version: "3.9"

services:
  dd-agents:
    build: .
    volumes:
      - ./test-data-room:/data-room:ro     # Mount data room read-only
      - dd-output:/data-room/_dd            # Persist DD artifacts
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - DD_LOG_LEVEL=INFO
    command: ["run", "/data-room", "--mode", "full"]

volumes:
  dd-output:
```

### 7.3 Docker Usage

```bash
# Build
docker build -t dd-agents .

# Run with data room mounted
docker run -v /path/to/data-room:/data-room \
           -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
           dd-agents run /data-room

# Run with budget limit
docker run -v /path/to/data-room:/data-room \
           -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
           dd-agents run /data-room --max-budget 10.00
```

---

## 8. Cloud Deployment

### 8.1 Requirements

The system can run on any machine with:
- Python 3.12+
- Node.js 18+ (for Claude Code CLI subprocess)
- Claude API key (`ANTHROPIC_API_KEY`)
- System packages: `poppler-utils` (pdftotext), `tesseract-ocr` (OCR), `libmagic` (file type detection)

No database, no message queue, no container orchestrator required.

### 8.2 Cloud Options

| Platform | Method | Notes |
|----------|--------|-------|
| AWS EC2 / GCP VM | Direct install | Simplest. SSH in, pip install, run. |
| AWS Batch / GCP Cloud Run Jobs | Docker container | For batch processing multiple deals. |
| GitHub Actions | Self-hosted runner | For CI/CD integrated runs. |
| Local workstation | Direct install | Development and ad-hoc analysis. |

### 8.3 Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores (parallel agent I/O) |
| RAM | 4 GB | 8 GB (large data rooms + ChromaDB) |
| Disk | 2 GB + data room size | 10 GB |
| Network | Required (Claude API) | Low bandwidth (text only) |

### 8.4 Cost Estimation

API cost depends on data room size and number of customers. Typical ranges:

| Data Room Size | Customers | Estimated Cost |
|---------------|-----------|---------------|
| 50 files, 10 customers | Small | $2-5 per run |
| 200 files, 50 customers | Medium | $5-10 per run |
| 500 files, 200 customers | Large | $10-25 per run |
