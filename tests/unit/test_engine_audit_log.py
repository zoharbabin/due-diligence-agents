"""Tests for PipelineEngine audit log writing and batch scheduler integration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from dd_agents.orchestrator.engine import PipelineEngine

# ---------------------------------------------------------------------------
# _write_audit_log tests
# ---------------------------------------------------------------------------


class TestWriteAuditLog:
    """Test the per-agent JSONL audit log writer (DoD #11)."""

    @staticmethod
    def _make_result(**overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "is_error": False,
            "duration_ms": 1234,
            "num_turns": 5,
            "input_tokens_est": 3000,
            "output_tokens_est": 1500,
            "cost_usd": 0.012,
            "model": "claude-sonnet-4-6",
        }
        base.update(overrides)
        return base

    def test_creates_audit_dir_and_file(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(), "16_spawn_specialists")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        assert log_path.exists()
        assert log_path.stat().st_size > 0

    def test_entry_fields(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "finance", self._make_result(), "16_spawn_specialists")

        log_path = run_dir / "audit" / "finance" / "audit_log.jsonl"
        entry = json.loads(log_path.read_text().strip())

        assert entry["agent"] == "finance"
        assert entry["step"] == "16_spawn_specialists"
        assert entry["status"] == "success"
        assert entry["duration_ms"] == 1234
        assert entry["num_turns"] == 5
        assert entry["input_tokens_est"] == 3000
        assert entry["output_tokens_est"] == 1500
        assert entry["cost_usd"] == pytest.approx(0.012)
        assert entry["model"] == "claude-sonnet-4-6"
        assert "timestamp" in entry

    def test_error_status(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(is_error=True), "16_spawn_specialists")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["status"] == "error"

    def test_appends_multiple_entries(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(), "16_spawn_specialists")
        PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(num_turns=10), "17_respawn")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        second = json.loads(lines[1])
        assert first["num_turns"] == 5
        assert second["num_turns"] == 10

    def test_multiple_agents_separate_files(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        for agent in ("legal", "finance", "commercial", "producttech"):
            PipelineEngine._write_audit_log(run_dir, agent, self._make_result(), "16_spawn_specialists")

        for agent in ("legal", "finance", "commercial", "producttech"):
            log_path = run_dir / "audit" / agent / "audit_log.jsonl"
            assert log_path.exists()
            entry = json.loads(log_path.read_text().strip())
            assert entry["agent"] == agent

    def test_judge_audit_log(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "judge", self._make_result(), "19_spawn_judge")

        log_path = run_dir / "audit" / "judge" / "audit_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["agent"] == "judge"
        assert entry["step"] == "19_spawn_judge"

    def test_missing_result_fields_default_safely(self, tmp_path: Path) -> None:
        """Sparse result dict should not crash — fields default to zero/empty."""
        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "legal", {}, "16_spawn_specialists")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["status"] == "success"  # is_error absent → not error
        assert entry["duration_ms"] == 0
        assert entry["num_turns"] == 0
        assert entry["cost_usd"] == 0.0
        assert entry["model"] == ""

    def test_valid_jsonl_format(self, tmp_path: Path) -> None:
        """Each line must be valid JSON (JSONL spec)."""
        run_dir = tmp_path / "run_001"
        for i in range(5):
            PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(num_turns=i), "16_spawn_specialists")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

    def test_timestamp_is_utc_iso(self, tmp_path: Path) -> None:
        import datetime

        run_dir = tmp_path / "run_001"
        PipelineEngine._write_audit_log(run_dir, "legal", self._make_result(), "16_spawn_specialists")

        log_path = run_dir / "audit" / "legal" / "audit_log.jsonl"
        entry = json.loads(log_path.read_text().strip())
        ts = datetime.datetime.fromisoformat(entry["timestamp"])
        assert ts.tzinfo is not None  # Must be timezone-aware


# ---------------------------------------------------------------------------
# QA audit integration: audit logs now pass DoD #11
# ---------------------------------------------------------------------------


class TestQAAuditLogValidation:
    """Verify that written audit logs satisfy the QA audit check."""

    def test_audit_logs_pass_qa_check(self, tmp_path: Path) -> None:
        from dd_agents.validation.qa_audit import QAAuditor

        run_dir = tmp_path / "run_001"
        # Write audit logs for all specialist agents
        from dd_agents.agents.registry import AgentRegistry

        for agent in AgentRegistry.all_specialist_names():
            PipelineEngine._write_audit_log(
                run_dir,
                agent,
                {"duration_ms": 100, "num_turns": 3, "model": "claude-sonnet-4-6"},
                "16_spawn_specialists",
            )

        auditor = QAAuditor(run_dir=run_dir, inventory_dir=run_dir, subject_safe_names=["acme"])
        name, check = auditor.check_audit_logs()

        assert name == "audit_logs"
        assert check.passed is True
        assert len(check.details["agents_with_logs"]) == 9
        assert len(check.details["missing_logs"]) == 0

    def test_partial_logs_fails_qa_check(self, tmp_path: Path) -> None:
        from dd_agents.agents.registry import AgentRegistry
        from dd_agents.validation.qa_audit import QAAuditor

        run_dir = tmp_path / "run_001"
        # Only write for 2 out of 9 agents
        for agent in ("legal", "finance"):
            PipelineEngine._write_audit_log(
                run_dir,
                agent,
                {"duration_ms": 100},
                "16_spawn_specialists",
            )

        auditor = QAAuditor(run_dir=run_dir, inventory_dir=run_dir, subject_safe_names=["acme"])
        name, check = auditor.check_audit_logs()

        assert name == "audit_logs"
        assert check.passed is False
        total_agents = len(AgentRegistry.all_specialist_names())
        assert len(check.details["missing_logs"]) == total_agents - 2


# ---------------------------------------------------------------------------
# Manifest backfill tests
# ---------------------------------------------------------------------------


class TestBackfillCoverageManifests:
    """Tests for PipelineEngine._backfill_coverage_manifests."""

    def test_backfill_populates_empty_manifest(self, tmp_path: Path) -> None:
        """Manifest with no files_read gets backfilled from subject JSONs."""
        run_dir = tmp_path / "run"
        agent_dir = run_dir / "findings" / "legal"
        agent_dir.mkdir(parents=True)

        # Write a minimal manifest
        manifest = {"agent": "legal", "run_id": "r1", "coverage_pct": 1.0}
        (agent_dir / "coverage_manifest.json").write_text(json.dumps(manifest))

        # Write a subject JSON with file_headers
        subject = {
            "file_headers": [
                {"file_path": "contracts/msa.pdf"},
                {"file_path": "contracts/sow.pdf"},
            ]
        }
        (agent_dir / "acme.json").write_text(json.dumps(subject))

        PipelineEngine._backfill_coverage_manifests(run_dir, ["acme"])

        updated = json.loads((agent_dir / "coverage_manifest.json").read_text())
        assert len(updated["files_read"]) == 2
        assert updated["files_read"][0]["path"] == "contracts/msa.pdf"
        assert len(updated["subjects"]) == 1
        assert updated["subjects"][0]["name"] == "acme"
        assert updated["analysis_units_completed"] == 1

    def test_backfill_skips_manifest_with_existing_data(self, tmp_path: Path) -> None:
        """Manifest that already has files_read is not modified."""
        run_dir = tmp_path / "run"
        agent_dir = run_dir / "findings" / "legal"
        agent_dir.mkdir(parents=True)

        manifest = {
            "agent": "legal",
            "files_read": [{"path": "existing.pdf", "extraction_quality": "primary"}],
        }
        (agent_dir / "coverage_manifest.json").write_text(json.dumps(manifest))
        (agent_dir / "acme.json").write_text(json.dumps({"file_headers": [{"file_path": "new.pdf"}]}))

        PipelineEngine._backfill_coverage_manifests(run_dir, ["acme"])

        updated = json.loads((agent_dir / "coverage_manifest.json").read_text())
        assert len(updated["files_read"]) == 1
        assert updated["files_read"][0]["path"] == "existing.pdf"

    def test_backfill_deduplicates_files_across_subjects(self, tmp_path: Path) -> None:
        """Same file in two subjects is only listed once."""
        run_dir = tmp_path / "run"
        agent_dir = run_dir / "findings" / "finance"
        agent_dir.mkdir(parents=True)

        manifest = {"agent": "finance", "run_id": "r1", "coverage_pct": 1.0}
        (agent_dir / "coverage_manifest.json").write_text(json.dumps(manifest))

        for ssn in ("acme", "globex"):
            (agent_dir / f"{ssn}.json").write_text(json.dumps({"file_headers": [{"file_path": "shared.pdf"}]}))

        PipelineEngine._backfill_coverage_manifests(run_dir, ["acme", "globex"])

        updated = json.loads((agent_dir / "coverage_manifest.json").read_text())
        assert len(updated["files_read"]) == 1


# ---------------------------------------------------------------------------
# Batch scheduler integration in step 14
# ---------------------------------------------------------------------------


class TestBatchSchedulerIntegration:
    """Test that score_subject_complexity is usable for step 14 ordering."""

    def test_ordering_simple_first(self) -> None:
        from dd_agents.orchestrator.batch_scheduler import score_subject_complexity

        scores = [
            score_subject_complexity("complex_co", file_count=20, total_bytes=5_000_000),
            score_subject_complexity("simple_co", file_count=1, total_bytes=500),
            score_subject_complexity("medium_co", file_count=5, total_bytes=200_000),
        ]

        sorted_scores = sorted(scores, key=lambda s: s.score)
        assert sorted_scores[0].subject_safe_name == "simple_co"
        assert sorted_scores[-1].subject_safe_name == "complex_co"

    def test_zero_files_zero_score(self) -> None:
        from dd_agents.orchestrator.batch_scheduler import score_subject_complexity

        result = score_subject_complexity("empty", file_count=0, total_bytes=0)
        assert result.score == 0.0
        assert result.tier == "simple"
        assert result.estimated_tokens == 0
