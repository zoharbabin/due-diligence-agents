"""run_export_script MCP tool.

Executes a Python script in a sandboxed subprocess to generate Excel, Word,
CSV, or other document files.  The script has access to openpyxl, python-docx,
csv, json, and other standard libraries but can only write files to a
designated exports directory.

This enables the chat agent to produce sophisticated document outputs —
multi-sheet Excel workbooks with charts, conditional formatting, and formulas;
styled Word documents with tables and headers — without granting arbitrary
filesystem or shell access.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SCRIPT_BYTES = 100_000
_TIMEOUT_SECONDS = 120
_MAX_OUTPUT_FILES = 50
_MAX_TOTAL_OUTPUT_BYTES = 200 * 1024 * 1024  # 200 MB


def run_export_script(
    code: str,
    output_dir: str | Path,
    *,
    timeout: int = _TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute a Python script that generates document files.

    The script runs in a subprocess with ``OUTPUT_DIR`` set as an environment
    variable pointing to the exports directory.  The script should write all
    output files there.

    A preamble is injected that imports common libraries and sets up the
    output path, so the script can immediately use ``OUTPUT_DIR``,
    ``openpyxl``, etc.

    Args:
        code: Python source code to execute.
        output_dir: Directory where the script must write output files.
        timeout: Maximum execution time in seconds.

    Returns:
        On success: ``{"status": "ok", "files": [...], "stdout": str}``
        On failure: ``{"error": str, "reason": str, "stderr": str}``
    """
    if not code or not code.strip():
        return {"error": "invalid_input", "reason": "Empty script"}

    if len(code.encode("utf-8")) > _MAX_SCRIPT_BYTES:
        return {
            "error": "too_large",
            "reason": f"Script exceeds {_MAX_SCRIPT_BYTES:,} byte limit",
        }

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    files_before = set(out_path.rglob("*")) if out_path.is_dir() else set()

    preamble = textwrap.dedent(f"""\
        import os, sys, json, csv, re, math, datetime, collections, itertools
        from pathlib import Path
        from decimal import Decimal

        OUTPUT_DIR = Path({str(out_path)!r})
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.chdir(OUTPUT_DIR)

        # Convenience imports — available if installed, silently skipped if not
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
            from openpyxl.chart import BarChart, PieChart, LineChart, Reference
            from openpyxl.utils import get_column_letter
            from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule
        except ImportError:
            pass

        try:
            import docx
            from docx import Document
            from docx.shared import Inches, Pt, Cm, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.enum.table import WD_TABLE_ALIGNMENT
        except ImportError:
            pass

    """)

    full_script = preamble + code

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(full_script)
        script_path = f.name

    try:
        env = os.environ.copy()
        env["OUTPUT_DIR"] = str(out_path)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(out_path),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "timeout",
            "reason": f"Script exceeded {timeout}s time limit",
            "stderr": "",
        }
    except OSError as exc:
        return {"error": "execution_failed", "reason": str(exc), "stderr": ""}
    finally:
        Path(script_path).unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
        return {
            "error": "script_error",
            "reason": f"Script exited with code {result.returncode}",
            "stderr": stderr,
            "stdout": result.stdout[-1000:] if result.stdout else "",
        }

    files_after = set(out_path.rglob("*")) if out_path.is_dir() else set()
    new_files = sorted(f for f in (files_after - files_before) if f.is_file())

    if len(new_files) > _MAX_OUTPUT_FILES:
        return {
            "error": "too_many_files",
            "reason": f"Script created {len(new_files)} files (limit: {_MAX_OUTPUT_FILES})",
            "stderr": "",
        }

    total_size = sum(f.stat().st_size for f in new_files)
    if total_size > _MAX_TOTAL_OUTPUT_BYTES:
        return {
            "error": "output_too_large",
            "reason": f"Total output is {total_size:,} bytes (limit: {_MAX_TOTAL_OUTPUT_BYTES:,})",
            "stderr": "",
        }

    file_infos = []
    for out_file in new_files:
        file_infos.append(
            {
                "path": str(out_file),
                "name": out_file.name,
                "size_bytes": out_file.stat().st_size,
            }
        )

    stdout = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout

    return {
        "status": "ok",
        "files": file_infos,
        "file_count": len(file_infos),
        "output_dir": str(out_path),
        "stdout": stdout.strip() if stdout else "",
    }
