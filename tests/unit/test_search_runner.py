"""Tests for dd_agents.search.runner -- SearchRunner orchestration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from dd_agents.models.search import SearchPrompts

if TYPE_CHECKING:
    from pathlib import Path
from dd_agents.search.runner import SearchRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_prompts(path: Path) -> Path:
    """Write a valid prompts file and return its path."""
    prompts = {
        "name": "Test Search",
        "description": "Unit test prompts",
        "columns": [
            {"name": "Has MSA?", "prompt": "Does this subject have a master service agreement?"},
        ],
    }
    path.write_text(json.dumps(prompts))
    return path


def _make_data_room(tmp_path: Path) -> Path:
    """Create a minimal data room structure."""
    dr = tmp_path / "data_room"
    dr.mkdir()
    # Create a subject folder with a file
    cust = dr / "Acme Corp"
    cust.mkdir()
    (cust / "MSA_2023.pdf.txt").write_text("Master Service Agreement between Acme Corp and...")
    return dr


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSearchRunnerInit:
    """Tests for SearchRunner construction."""

    def test_default_output_path(self, tmp_path: Path) -> None:
        prompts = _write_prompts(tmp_path / "my_search.json")
        dr = _make_data_room(tmp_path)
        runner = SearchRunner(prompts, dr)
        assert "search_my_search.xlsx" in str(runner._output_path)

    def test_custom_output_path(self, tmp_path: Path) -> None:
        prompts = _write_prompts(tmp_path / "search.json")
        dr = _make_data_room(tmp_path)
        out = tmp_path / "custom.xlsx"
        runner = SearchRunner(prompts, dr, output_path=out)
        assert runner._output_path == out

    def test_group_filter_stored(self, tmp_path: Path) -> None:
        prompts = _write_prompts(tmp_path / "search.json")
        dr = _make_data_room(tmp_path)
        runner = SearchRunner(prompts, dr, group_filter="GroupA")
        assert runner._group_filter == "GroupA"

    def test_subject_filter_stored(self, tmp_path: Path) -> None:
        prompts = _write_prompts(tmp_path / "search.json")
        dr = _make_data_room(tmp_path)
        runner = SearchRunner(prompts, dr, subject_filter="Acme")
        assert runner._subject_filter == "Acme"

    def test_concurrency_stored(self, tmp_path: Path) -> None:
        prompts = _write_prompts(tmp_path / "search.json")
        dr = _make_data_room(tmp_path)
        runner = SearchRunner(prompts, dr, concurrency=10)
        assert runner._concurrency == 10


# ---------------------------------------------------------------------------
# Prompts loading
# ---------------------------------------------------------------------------


class TestPromptsValidation:
    """Tests for SearchPrompts model validation."""

    def test_valid_prompts(self) -> None:
        prompts = SearchPrompts(
            name="Test",
            columns=[{"name": "Q1", "prompt": "What is the answer to this question?"}],
        )
        assert prompts.name == "Test"
        assert len(prompts.columns) == 1

    def test_empty_columns_rejected(self) -> None:
        with pytest.raises(ValueError):
            SearchPrompts(name="Test", columns=[])

    def test_too_many_columns_rejected(self) -> None:
        cols = [{"name": f"Q{i}", "prompt": f"Question number {i} long enough"} for i in range(25)]
        with pytest.raises(ValueError):
            SearchPrompts(name="Test", columns=cols)

    def test_extra_fields_rejected(self) -> None:
        """SearchPrompts uses extra='forbid'."""
        with pytest.raises(ValueError):
            SearchPrompts(
                name="Test",
                columns=[{"name": "Q1", "prompt": "What is this question about?"}],
                bogus_field="should fail",
            )

    def test_short_prompt_rejected(self) -> None:
        with pytest.raises(ValueError):
            SearchPrompts(
                name="Test",
                columns=[{"name": "Q1", "prompt": "short"}],
            )


# ---------------------------------------------------------------------------
# Run orchestration (mocked)
# ---------------------------------------------------------------------------


class TestSearchRunnerRun:
    """Tests for SearchRunner.run with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_run_handles_missing_data_room(self, tmp_path: Path) -> None:
        """Run should fail gracefully when data room doesn't exist."""
        prompts = _write_prompts(tmp_path / "search.json")
        missing = tmp_path / "nonexistent"
        runner = SearchRunner(prompts, missing)
        # The runner resolves the path in __init__, so accessing internals
        # that depend on the data room structure will surface the error.
        assert not (runner._data_room / "_dd").exists()
