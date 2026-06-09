"""Tests for pipeline-run chronicle logging (Issue #217).

The engine must record a PIPELINE_RUN entry in the analysis chronicle at the
canonical knowledge dir (the same one the CLI/chat read) — and the knowledge
base must compile to that same root, not a nested ``<project>/knowledge`` tree.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dd_agents.orchestrator.engine import PipelineEngine
from dd_agents.orchestrator.state import PipelineState

if TYPE_CHECKING:
    from pathlib import Path


def _make_engine(tmp_path: Path) -> PipelineEngine:
    config_path = tmp_path / "deal-config.json"
    config_path.write_text("{}")
    return PipelineEngine(tmp_path, config_path)


def _seed_merged_findings(run_dir: Path) -> None:
    merged = run_dir / "findings" / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    (merged / "acme.json").write_text(
        json.dumps(
            {
                "subject": "Acme",
                "findings": [
                    {"severity": "P0", "title": "Critical", "agent": "legal"},
                    {"severity": "P2", "title": "Minor", "agent": "finance"},
                ],
                "gaps": [{"priority": "P1", "missing_item": "MSA"}],
            }
        )
    )


class TestPipelineChronicle:
    def test_logs_pipeline_run_to_canonical_chronicle(self, tmp_path: Path) -> None:
        engine = _make_engine(tmp_path)
        state = PipelineState(project_dir=tmp_path.resolve())
        state.run_id = "run_test_001"
        state.run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_test_001"
        state.run_dir.mkdir(parents=True, exist_ok=True)
        state.subject_safe_names = ["acme"]
        state.deal_config = {"buyer": {"name": "Summit"}, "target": {"name": "Acme"}}
        _seed_merged_findings(state.run_dir)

        engine._log_pipeline_to_chronicle(state)

        chronicle = tmp_path.resolve() / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl"
        assert chronicle.exists()
        entry = json.loads(chronicle.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert entry["interaction_type"] == "pipeline_run"
        assert entry["details"]["run_id"] == "run_test_001"
        assert entry["findings_summary"]["total"] == 2
        assert entry["findings_summary"]["p0"] == 1
        assert entry["entities_affected"] == ["acme"]
        # No nested knowledge dir.
        assert not (tmp_path / "knowledge" / "_dd").exists()

    def test_chronicle_logging_never_raises(self, tmp_path: Path) -> None:
        """A missing run_dir must not break the pipeline — best-effort only."""
        engine = _make_engine(tmp_path)
        state = PipelineState(project_dir=tmp_path.resolve())
        state.run_id = "run_x"
        state.run_dir = tmp_path / "nonexistent"
        # Must not raise even with no merged findings.
        engine._log_pipeline_to_chronicle(state)

    def test_idempotent_on_resume(self, tmp_path: Path) -> None:
        """Re-running step 36 for the same run_id writes exactly ONE entry (#216 audit)."""
        engine = _make_engine(tmp_path)
        state = PipelineState(project_dir=tmp_path.resolve())
        state.run_id = "run_resume_001"
        state.run_dir = tmp_path / "_dd" / "forensic-dd" / "runs" / "run_resume_001"
        state.run_dir.mkdir(parents=True, exist_ok=True)
        state.subject_safe_names = ["acme"]
        _seed_merged_findings(state.run_dir)

        engine._log_pipeline_to_chronicle(state)
        engine._log_pipeline_to_chronicle(state)  # simulates a resume re-running step 36

        chronicle = tmp_path.resolve() / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl"
        lines = [ln for ln in chronicle.read_text(encoding="utf-8").splitlines() if ln.strip()]
        run_entries = [ln for ln in lines if "run_resume_001" in ln]
        assert len(run_entries) == 1
