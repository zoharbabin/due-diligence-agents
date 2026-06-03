"""Specialist prompt section ordering (audit §3.2, highest-recall tail).

The subject/file listing sits in the MIDDLE; the severity rubric, output
format, and citation/robustness mandates come last, with the non-removable
safety floor appended after everything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.agents.prompt_builder import PromptBuilder
from dd_agents.agents.prompt_constants import SAFETY_FLOOR_HEADER

if TYPE_CHECKING:
    from pathlib import Path

_SUBJECT_LIST_MARKER = "## ALL SUBJECTS"
_SEVERITY_RUBRIC_MARKER = "## SEVERITY CALIBRATION"


def _prompt(tmp_path: Path) -> str:
    builder = PromptBuilder(project_dir=tmp_path, run_dir=tmp_path, run_id="test")
    return builder.build_specialist_prompt("legal", ["Subject A"])


def test_subject_list_precedes_severity_rubric(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    assert _SUBJECT_LIST_MARKER in prompt
    assert _SEVERITY_RUBRIC_MARKER in prompt
    assert prompt.index(_SUBJECT_LIST_MARKER) < prompt.index(_SEVERITY_RUBRIC_MARKER)


def test_safety_floor_is_last(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)
    assert SAFETY_FLOOR_HEADER in prompt
    # Severity rubric (a "tail" section) must precede the appended floor.
    assert prompt.index(_SEVERITY_RUBRIC_MARKER) < prompt.index(SAFETY_FLOOR_HEADER)
