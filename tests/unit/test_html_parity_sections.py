"""Tests for HTML/PDF parity of Excel-only sections (Issue #244).

Covers the ContractDatesRenderer, the QualityRenderer entity-resolution block,
and the CompletenessRenderer reference-files block — XSS-safe + parity (nothing
when data absent).
"""

from __future__ import annotations

from typing import Any

from dd_agents.reporting.computed_metrics import ReportDataComputer
from dd_agents.reporting.html_completeness import CompletenessRenderer
from dd_agents.reporting.html_contract_dates import ContractDatesRenderer
from dd_agents.reporting.html_quality import QualityRenderer


def _computed() -> Any:
    return ReportDataComputer().compute({})


class TestContractDatesRenderer:
    def test_parity_empty_when_absent(self) -> None:
        assert ContractDatesRenderer(_computed(), {}, {"_run_metadata": {}}).render() == ""
        assert ContractDatesRenderer(_computed(), {}, {"_run_metadata": None}).render() == ""

    def test_renders_entries_and_arr_kpis(self) -> None:
        recon = {
            "entries": [
                {
                    "subject": "Acme Corp",
                    "status": "Expired-Confirmed",
                    "database_end_date": "2025-12-31",
                    "actual_end_date": "2024-06-30",
                    "arr": 500000.0,
                    "evidence": "Contract expired",
                    "evidence_file": "Acme/msa.pdf",
                }
            ],
            "total_expired_arr": 500000.0,
            "total_reclassified_arr": 0.0,
        }
        html = ContractDatesRenderer(
            _computed(), {}, {"_run_metadata": {"contract_date_reconciliation": recon}}
        ).render()
        assert "Contract Date Reconciliation" in html
        assert "Acme Corp" in html
        assert "Expired-Confirmed" in html
        assert "id='sec-contract-dates'" in html
        assert "$500K" in html  # fmt_currency abbreviates

    def test_escapes_subject_and_evidence(self) -> None:
        recon = {
            "entries": [
                {
                    "subject": "<script>x</script>",
                    "status": "s",
                    "arr": 0,
                    "evidence": "<img src=x>",
                    "evidence_file": "",
                }
            ]
        }
        html = ContractDatesRenderer(
            _computed(), {}, {"_run_metadata": {"contract_date_reconciliation": recon}}
        ).render()
        assert "<script>x</script>" not in html
        assert "<img src=x>" not in html
        assert "&lt;script&gt;" in html


class TestEntityResolutionSection:
    def test_parity_empty_when_no_matches(self) -> None:
        assert QualityRenderer(_computed(), {}, {"_run_metadata": {}})._render_entity_resolution() == ""

    def test_renders_match_log(self) -> None:
        matches = [
            {"source_name": "ACME", "canonical_name": "Acme Corp", "match_method": "fuzzy", "confidence": 0.92},
        ]
        html = QualityRenderer(
            _computed(), {}, {"_run_metadata": {"entity_matches": matches}}
        )._render_entity_resolution()
        assert "Entity Resolution Log" in html
        assert "Acme Corp" in html
        assert "92%" in html

    def test_escapes_names(self) -> None:
        matches = [{"source_name": "<b>x</b>", "canonical_name": "y", "match_method": "m", "confidence": "n/a"}]
        html = QualityRenderer(
            _computed(), {}, {"_run_metadata": {"entity_matches": matches}}
        )._render_entity_resolution()
        assert "<b>x</b>" not in html
        assert "&lt;b&gt;" in html


class TestReferenceFilesSection:
    def test_parity_empty_when_absent(self) -> None:
        # No reference_files (and no other completeness data) → whole section empty.
        assert CompletenessRenderer(_computed(), {}, {"_run_metadata": {}}).render() == ""

    def test_renders_reference_files(self) -> None:
        refs = [{"file_path": "DD_Output/deck.pptx", "category": "dd_output", "description": "Readout deck"}]
        html = CompletenessRenderer(_computed(), {}, {"_run_metadata": {"reference_files": refs}}).render()
        assert "Reference Files (1)" in html
        assert "DD_Output/deck.pptx" in html
        assert "id='sec-completeness'" in html

    def test_escapes_reference_paths(self) -> None:
        refs = [{"file_path": "<x>", "category": "<y>", "description": "<z>"}]
        html = CompletenessRenderer(_computed(), {}, {"_run_metadata": {"reference_files": refs}}).render()
        assert "<x>" not in html and "<y>" not in html
        assert "&lt;x&gt;" in html
