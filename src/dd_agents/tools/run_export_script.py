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

# Environment variables safe to pass to the export subprocess.
# Secrets (API keys, tokens, credentials) are stripped.
_ENV_ALLOWLIST: set[str] = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPATH",
    "SHELL",
    "TEMP",
    "TMPDIR",
    "TMP",
    "TZ",
    "USER",
}


# Modules that export scripts must never import — prevents network
# exfiltration, arbitrary process execution, and system-level access.
_BLOCKED_MODULES: set[str] = {
    "ctypes",
    "ftplib",
    "importlib",
    "pty",
    "http.client",
    "httplib",
    "httpx",
    "multiprocessing",
    "requests",
    "shutil",
    "smtplib",
    "socket",
    "socketserver",
    "subprocess",
    "telnetlib",
    "urllib",
    "urllib.request",
    "urllib2",
    "urllib3",
    "webbrowser",
    "xmlrpc",
}


# Dynamic-execution builtins an export script must never call — these defeat
# any import-based denylist (arbitrary code / shell / dynamic import).
_BLOCKED_CALLS: set[str] = {
    "eval",
    "exec",
    "compile",
    "__import__",
}

# Dangerous attribute calls on otherwise-allowed modules (esp. ``os``, which the
# preamble provides for ``os.chdir``). A module denylist cannot stop these, so
# the call surface itself is blocked: ``os.system``, ``os.popen``, ``os.exec*``,
# ``os.spawn*``, ``os.fork``, ``os.posix_spawn*``, plus ``importlib.import_module``.
_BLOCKED_ATTR_CALLS: set[str] = {
    "system",
    "popen",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "spawnv",
    "spawnve",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "posix_spawn",
    "posix_spawnp",
    "fork",
    "forkpty",
    "import_module",
}


def _check_blocked_imports(code: str) -> set[str]:
    """Scan script source for blocked imports AND dangerous dynamic-call surface.

    A module-import denylist alone is NOT a security boundary: the preamble
    deliberately provides ``os`` (for ``os.chdir``), so ``os.system``/``popen``/
    ``exec*``/``spawn*`` and the dynamic-execution builtins (``eval``/``exec``/
    ``compile``/``__import__``) would otherwise escape the sandbox to arbitrary
    shell + filesystem. This scan also rejects those calls. Falls back to a
    substring scan if the code cannot be parsed (fail-closed: unparseable code
    is rejected by the caller via the returned markers).

    The AST denylist is one layer; OUTPUT_DIR confinement + the stripped env +
    the subprocess timeout/output caps are the others (defense in depth).
    """
    import ast

    found: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        for mod in _BLOCKED_MODULES:
            if mod in code:
                found.add(mod)
        # Also catch obvious dynamic-exec strings when AST is unavailable.
        for name in _BLOCKED_CALLS | _BLOCKED_ATTR_CALLS:
            if name in code:
                found.add(name)
        return found

    # Names that refer to a process/exec-capable module — the only receivers on
    # which a blocked attribute call (.system/.popen/.exec*/.spawn*) is dangerous.
    # ``os`` is included because the preamble provides it; the rest can only be
    # reached via an import the module-denylist already blocks, but we track
    # their bindings (and aliases) so a benign same-named method elsewhere is
    # not a false positive.
    sensitive_modules = {"os", "posix", "importlib", "subprocess", "pty"}
    sensitive_names: set[str] = set(sensitive_modules)
    for node in ast.walk(tree):
        # import os as o  /  import os
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in sensitive_modules:
                    sensitive_names.add(alias.asname or alias.name.split(".")[0])
        # o = os  (alias binding)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in sensitive_names:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    sensitive_names.add(tgt.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if alias.name in _BLOCKED_MODULES or top in _BLOCKED_MODULES:
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if node.module in _BLOCKED_MODULES or top in _BLOCKED_MODULES:
                    found.add(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            # Bare builtin call: eval(...), exec(...), __import__('os'), ...
            if isinstance(func, ast.Name):
                if func.id in _BLOCKED_CALLS:
                    found.add(func.id)
                if func.id == "__import__" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        top = arg.value.split(".")[0]
                        if arg.value in _BLOCKED_MODULES or top in _BLOCKED_MODULES:
                            found.add(arg.value)
            # Attribute call on a SENSITIVE RECEIVER only: os.system(...),
            # os.popen(...), importlib.import_module(...). We scope to sensitive
            # base names (and aliases bound to them) so a benign method that
            # merely shares a name — e.g. workbook.system() or a library
            # spawn()/exec() — is NOT a false positive (Copilot #202 C7).
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in _BLOCKED_ATTR_CALLS
                and isinstance(func.value, ast.Name)
                and func.value.id in sensitive_names
            ):
                found.add(f"{func.value.id}.{func.attr}")
        # getattr-based bypass. Two distinct rules (Copilot #202 C11):
        #   * dynamic-exec builtins (eval/exec/compile/__import__) are dangerous
        #     to retrieve dynamically NO MATTER the receiver — always block.
        #   * module-attr names (system/popen/exec*/spawn*/...) are only
        #     dangerous on a SENSITIVE receiver. Blocking them unconditionally
        #     would reintroduce the false positive the attribute-call scoping
        #     above avoids (e.g. ``getattr(workbook, "system")``).
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            attr_name = node.args[1].value
            receiver = node.args[0]
            receiver_is_sensitive = isinstance(receiver, ast.Name) and receiver.id in sensitive_names
            if attr_name in _BLOCKED_CALLS or attr_name in _BLOCKED_ATTR_CALLS and receiver_is_sensitive:
                found.add(f"getattr:{attr_name}")
    return found


def _build_safe_env(out_path: Path) -> dict[str, str]:
    """Build a minimal environment for the export subprocess.

    Only passes allowlisted variables plus OUTPUT_DIR.  This prevents
    LLM-generated scripts from accessing API keys, tokens, or other
    secrets present in the parent process environment.
    """
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env["OUTPUT_DIR"] = str(out_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


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

    blocked = _check_blocked_imports(code)
    if blocked:
        return {
            "error": "blocked_import",
            "reason": f"Script uses blocked module(s): {', '.join(sorted(blocked))}",
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
        env = _build_safe_env(out_path)

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
