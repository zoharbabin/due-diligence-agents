"""Tests for dd_agents.tools.run_export_script."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dd_agents.tools.run_export_script import run_export_script

if TYPE_CHECKING:
    from pathlib import Path


class TestRunExportScript:
    """Tests for the sandboxed export script execution."""

    def test_empty_code_rejected(self, tmp_path: Path) -> None:
        result = run_export_script("", tmp_path / "out")
        assert result["error"] == "invalid_input"

    def test_whitespace_only_rejected(self, tmp_path: Path) -> None:
        result = run_export_script("   \n  ", tmp_path / "out")
        assert result["error"] == "invalid_input"

    def test_oversized_script_rejected(self, tmp_path: Path) -> None:
        code = "x = 1\n" * 100_000
        result = run_export_script(code, tmp_path / "out")
        assert result["error"] == "too_large"

    def test_simple_csv_creation(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = """
with open(OUTPUT_DIR / "report.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Subject", "Severity", "Finding"])
    w.writerow(["Acme", "P1", "Change of control risk"])
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 1
        assert result["files"][0]["name"] == "report.csv"
        assert (out / "report.csv").exists()

    def test_excel_creation(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = """
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Findings"
ws.append(["Subject", "Severity", "Title"])
ws.append(["Acme Corp", "P0", "Critical IP risk"])
for cell in ws[1]:
    cell.font = Font(bold=True)
wb.save(OUTPUT_DIR / "findings.xlsx")
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 1
        assert result["files"][0]["name"] == "findings.xlsx"
        assert result["files"][0]["size_bytes"] > 0

    def test_script_error_returns_stderr(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = "raise ValueError('test error')"
        result = run_export_script(code, out)
        assert result["error"] == "script_error"
        assert "test error" in result["stderr"]

    def test_timeout_enforcement(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = "import time; time.sleep(10)"
        result = run_export_script(code, out, timeout=1)
        assert result["error"] == "timeout"

    def test_stdout_captured(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = 'print("Generated 3 files")'
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert "Generated 3 files" in result["stdout"]

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "exports"
        code = """
with open(OUTPUT_DIR / "test.txt", "w") as f:
    f.write("hello")
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert out.exists()

    def test_preamble_imports_available(self, tmp_path: Path) -> None:
        """Standard libraries from preamble are importable."""
        out = tmp_path / "exports"
        code = """
import json, csv, re, math, datetime, collections, itertools
from decimal import Decimal
from pathlib import Path
assert isinstance(OUTPUT_DIR, Path)
with open(OUTPUT_DIR / "ok.json", "w") as f:
    json.dump({"status": "all_imports_ok"}, f)
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"

    def test_multiple_files_created(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = """
for name in ["a.csv", "b.csv", "c.csv"]:
    with open(OUTPUT_DIR / name, "w") as f:
        f.write("data")
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 3

    def test_no_files_created_still_ok(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        code = "x = 1 + 1"
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 0

    def test_existing_files_not_counted_as_new(self, tmp_path: Path) -> None:
        out = tmp_path / "exports"
        out.mkdir(parents=True)
        (out / "existing.txt").write_text("pre-existing")

        code = """
with open(OUTPUT_DIR / "new.txt", "w") as f:
    f.write("new file")
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 1
        assert result["files"][0]["name"] == "new.txt"

    def test_word_doc_creation(self, tmp_path: Path) -> None:
        """python-docx integration — skip if not installed."""
        out = tmp_path / "exports"
        code = """
try:
    doc = Document()
    doc.add_heading("Due Diligence Report", level=1)
    doc.add_paragraph("Summary of findings.")
    doc.save(OUTPUT_DIR / "report.docx")
except NameError:
    # python-docx not installed — write a placeholder
    with open(OUTPUT_DIR / "report.txt", "w") as f:
        f.write("docx not available")
"""
        result = run_export_script(code, out)
        assert result["status"] == "ok"
        assert result["file_count"] == 1


class TestExportScriptSandboxEscape:
    """Security regression: the export sandbox must block code-execution escapes.

    The AST module-denylist alone is insufficient because the preamble provides
    ``os`` (for ``os.chdir``). These tests lock the call-surface denylist that
    closes the arbitrary-shell / filesystem-escape hole found in the release audit.
    """

    import pytest

    _ESCAPES = [
        "import os; os.system('echo x > /tmp/should_not_exist_dd.txt')",
        "import os; os.popen('echo x').read()",
        "os.system('echo x')",  # os comes from the preamble, no import
        "eval(\"__import__('os').system('echo x')\")",
        "exec(\"import os; os.system('echo x')\")",
        "__import__('os').system('echo x')",
        "getattr(os, 'system')('echo x')",
        "import importlib; importlib.import_module('os').system('echo x')",
        "import subprocess; subprocess.run(['echo', 'x'])",
        "import ctypes",
        "os.fork()",
        "os.execv('/bin/sh', ['/bin/sh'])",
    ]

    @pytest.mark.parametrize("code", _ESCAPES)
    def test_escape_attempt_is_blocked(self, code: str, tmp_path: Path) -> None:
        from dd_agents.tools.run_export_script import run_export_script

        result = run_export_script(code, tmp_path)
        assert result.get("error") == "blocked_import", f"escape not blocked: {code!r} -> {result}"

    def test_legitimate_export_still_works(self, tmp_path: Path) -> None:
        from dd_agents.tools.run_export_script import run_export_script

        code = "import openpyxl\nwb = openpyxl.Workbook()\nwb.save(str(OUTPUT_DIR / 'ok.xlsx'))"
        result = run_export_script(code, tmp_path)
        assert result.get("status") == "ok"
        assert result.get("file_count") == 1
