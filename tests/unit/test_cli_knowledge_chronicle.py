"""Tests for knowledge-command chronicle wiring (Issue #217).

Verifies that `annotate` records an ANALYSIS chronicle entry (so `dd-agents
log` surfaces it) and that the engine's pipeline-run chronicle write lands in
the SAME knowledge dir the CLI reads from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from dd_agents.cli import main

if TYPE_CHECKING:
    from pathlib import Path


def _chronicle_path(data_room: Path) -> Path:
    return data_room / "_dd" / "forensic-dd" / "knowledge" / "chronicle.jsonl"


class TestAnnotateChronicle:
    def test_annotate_writes_chronicle_entry(self, tmp_path: Path) -> None:
        runner = CliRunner()
        dr = tmp_path / "data_room"
        dr.mkdir()
        result = runner.invoke(
            main,
            ["annotate", "--data-room", str(dr), "--entity", "acme_corp", "Key risk noted"],
        )
        assert result.exit_code == 0, result.output
        # Chronicle file exists at the canonical (CLI-read) location.
        cp = _chronicle_path(dr)
        assert cp.exists()
        text = cp.read_text(encoding="utf-8")
        assert "annotation" in text
        assert "acme_corp" in text

    def test_log_surfaces_the_annotation(self, tmp_path: Path) -> None:
        runner = CliRunner()
        dr = tmp_path / "data_room"
        dr.mkdir()
        runner.invoke(main, ["annotate", "--data-room", str(dr), "Vendor lock-in risk"])
        result = runner.invoke(main, ["log", "--data-room", str(dr)])
        assert result.exit_code == 0, result.output
        # The annotation must appear in the chronicle timeline, not "No history".
        assert "No analysis history" not in result.output
        assert "Total entries: 1" in result.output
        # Filtering by annotation type also surfaces it.
        filtered = runner.invoke(main, ["log", "--data-room", str(dr), "--type", "annotation"])
        assert filtered.exit_code == 0, filtered.output
        assert "Total entries: 1" in filtered.output

    def test_annotate_does_not_nest_knowledge_dir(self, tmp_path: Path) -> None:
        """Annotation must NOT create a nested data_room/knowledge/_dd tree (#217)."""
        runner = CliRunner()
        dr = tmp_path / "data_room"
        dr.mkdir()
        runner.invoke(main, ["annotate", "--data-room", str(dr), "note"])
        assert not (dr / "knowledge" / "_dd").exists()
        assert (dr / "_dd" / "forensic-dd" / "knowledge").is_dir()
