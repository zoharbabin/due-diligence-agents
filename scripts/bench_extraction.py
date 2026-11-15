#!/usr/bin/env python3
"""Benchmark text extraction on the synthetic corpus (tests/fixtures/extraction_corpus).

Every arm is optional. An arm whose library or binary is missing is skipped and
named in the output. No OCR arms: scanned pages are expected to give no text.

    PYTHONPATH=src python scripts/bench_extraction.py \
        --out-json /tmp/bench.json --out-md /tmp/bench.md

Extra libraries can live in a throwaway directory (``pip install --target DIR``)
and be added with ``--extra-path DIR``.

Arms
----
PDF files:   pdfium (``dd_agents.extraction.pdf_engine``), pdf_inspector
             (``extract_text`` and ``process_pdf`` markdown), pdftotext (subprocess).
Other files: markitdown, builtin_fallback (``office_convert._FALLBACKS``),
             anydoc (``firecrawl-anydoc``).

Metrics
-------
phrase recall      Key phrases found in the output, whitespace ignored. Only phrases from
                   pages that have a text layer, so scans do not count against anyone.
table-cell recall  Table cells found in the output (files that have a table).
numeric recall     Numeric cells found in any common number format (XLSX).
reading order      Two-column PDF: phrases appear in the order the ground truth lists.
hard failures      An exception on a file that should be readable. ``ValueError`` from
                   pdf_inspector counts here.
expected failures  Files labeled encrypted or unreadable: the arm should raise.
seconds per file   Median of ``--repeats`` timed calls per file, after one warm-up call.
classification     pdf_inspector page labels (text or scanned) against the ground truth.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "tests" / "fixtures" / "extraction_corpus"

# Text that sits in <script> and <style> in office_terms_en.html. It must not reach the output.
HTML_NOISE = ("analytics-placeholder", "font-family")


def load_corpus() -> Any:
    spec = importlib.util.spec_from_file_location(
        "extraction_corpus", CORPUS_DIR / "__init__.py", submodule_search_locations=[str(CORPUS_DIR)]
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CORPUS_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["extraction_corpus"] = module
    spec.loader.exec_module(module)
    return module


corpus = load_corpus()


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


@dataclass
class Arm:
    name: str
    scope: str  # "pdf" or "office"
    run: Callable[[Path], str]
    note: str = ""


def _pdfium_arm() -> Arm:
    from dd_agents.extraction import pdf_engine

    def run(path: Path) -> str:
        return "\n".join(pdf_engine.extract_pages(path))

    return Arm("pdfium", "pdf", run, "dd_agents.extraction.pdf_engine.extract_pages")


def _pdf_inspector_arms() -> list[Arm]:
    import pdf_inspector

    def plain(path: Path) -> str:
        result = pdf_inspector.extract_text(str(path))
        return str(result) if result is not None else ""

    def markdown(path: Path) -> str:
        result = pdf_inspector.process_pdf(str(path))
        return str(result.markdown or "")

    return [
        Arm("pdf_inspector (extract_text)", "pdf", plain, "pdf_inspector.extract_text"),
        Arm("pdf_inspector (markdown)", "pdf", markdown, "pdf_inspector.process_pdf(...).markdown"),
    ]


def _pdftotext_arm() -> Arm:
    def run(path: Path) -> str:
        proc = subprocess.run(  # noqa: S603
            ["pdftotext", str(path), "-"],  # noqa: S607
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[:120] or f"exit {proc.returncode}")
        return proc.stdout.decode("utf-8", "replace")

    # Fail fast when the binary is missing.
    subprocess.run(["pdftotext", "-v"], capture_output=True, check=False)  # noqa: S603, S607
    return Arm("pdftotext", "pdf", run, "pdftotext FILE -")


def _markitdown_arm() -> Arm:
    from dd_agents.extraction import office_convert

    cls = office_convert._load_markitdown()
    converter = cls()

    def run(path: Path) -> str:
        return str(converter.convert(str(path)).text_content)

    return Arm("markitdown", "office", run, "MarkItDown().convert")


def _fallback_arm() -> Arm:
    from dd_agents.extraction import office_convert

    def run(path: Path) -> str:
        func = office_convert._FALLBACKS.get(path.suffix.lower())
        if func is None:
            raise ValueError(f"no built-in converter for {path.suffix}")
        return str(func(path))

    return Arm("builtin_fallback", "office", run, "office_convert._FALLBACKS")


def _anydoc_arm() -> Arm:
    import anydoc

    def run(path: Path) -> str:
        return str(anydoc.to_markdown(str(path)))

    return Arm("anydoc", "office", run, "anydoc.to_markdown")


def build_arms() -> tuple[list[Arm], dict[str, str]]:
    arms: list[Arm] = []
    skipped: dict[str, str] = {}

    def add(name: str, factory: Callable[[], Arm | list[Arm]]) -> None:
        try:
            made = factory()
        except Exception as exc:  # optional arm: any import or setup problem means skip
            skipped[name] = f"{type(exc).__name__}: {exc}"
            return
        arms.extend(made if isinstance(made, list) else [made])

    add("pdfium", _pdfium_arm)
    add("pdf_inspector", _pdf_inspector_arms)
    add("pdftotext", _pdftotext_arm)
    add("markitdown", _markitdown_arm)
    add("builtin_fallback", _fallback_arm)
    add("anydoc", _anydoc_arm)
    return arms, skipped


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class FileResult:
    name: str
    ok: bool
    seconds: float | None = None
    error: str = ""
    chars: int = 0
    phrases_found: int = 0
    phrases_total: int = 0
    cells_found: int = 0
    cells_total: int = 0
    numeric_found: int = 0
    numeric_total: int = 0
    order_ok: bool | None = None
    tracked_inserted: tuple[int, int] | None = None
    tracked_deleted: tuple[int, int] | None = None
    noise_leaked: bool | None = None


def expected_phrases(entry: Any) -> list[str]:
    """Phrases the arm can recover without OCR."""
    if entry.kind == "pdf":
        out: list[str] = []
        for kind, phrases in zip(entry.page_kinds, entry.page_key_phrases or (), strict=False):
            if kind == "text":
                out.extend(phrases)
        return out
    return list(entry.key_phrases)


def number_forms(value: float) -> list[str]:
    forms = {f"{value:.0f}", f"{value:,.0f}", f"{value:.2f}", f"{value:,.2f}", f"{value:g}"}
    return [corpus.normalize(f) for f in forms]


def in_order(text: str, phrases: tuple[str, ...]) -> bool:
    flat = corpus.normalize(text)
    last = -1
    for phrase in phrases:
        pos = flat.find(corpus.normalize(phrase))
        if pos < 0 or pos < last:
            return False
        last = pos
    return True


def score(entry: Any, text: str) -> dict[str, Any]:
    flat = corpus.normalize(text)
    out: dict[str, Any] = {"chars": len(text)}
    phrases = expected_phrases(entry)
    out["phrases_total"] = len(phrases)
    out["phrases_found"] = sum(corpus.normalize(p) in flat for p in phrases)
    # A scanned PDF has no text layer, so its table cells cannot be recovered without OCR.
    cells = entry.flat_table_cells if entry.has_text_layer else ()
    out["cells_total"] = len(cells)
    out["cells_found"] = sum(corpus.normalize(c) in flat for c in cells)
    out["numeric_total"] = len(entry.numeric_cells)
    out["numeric_found"] = sum(any(f in flat for f in number_forms(n)) for n in entry.numeric_cells)
    if entry.reading_order:
        out["order_ok"] = in_order(text, entry.reading_order)
    if entry.tracked_changes is not None:
        ins, dele = entry.tracked_changes.inserted, entry.tracked_changes.deleted
        out["tracked_inserted"] = (sum(corpus.normalize(p) in flat for p in ins), len(ins))
        out["tracked_deleted"] = (sum(corpus.normalize(p) in flat for p in dele), len(dele))
    if entry.name == "office_terms_en.html":
        out["noise_leaked"] = any(n in text for n in HTML_NOISE)
    return out


def run_arm(arm: Arm, entries: list[Any], repeats: int) -> list[FileResult]:
    # One warm-up call on a file the arm can read, so import and model start-up are not timed.
    for entry in entries:
        if entry.expected_failure is None and entry.damage is None:
            with contextlib.suppress(Exception):
                arm.run(entry.path)
            break
    results: list[FileResult] = []
    for entry in entries:
        times: list[float] = []
        text = ""
        error = ""
        for _ in range(repeats):
            start = time.perf_counter()
            try:
                text = arm.run(entry.path)
            except Exception as exc:  # noqa: BLE001
                message = (str(exc).splitlines() or [""])[0].replace(str(entry.path), entry.name)
                error = f"{type(exc).__name__}: {message[:100]}"
                break
            times.append(time.perf_counter() - start)
        if error:
            results.append(FileResult(entry.name, ok=False, error=error))
            continue
        res = FileResult(entry.name, ok=True, seconds=statistics.median(times))
        for key, value in score(entry, text).items():
            setattr(res, key, value)
        results.append(res)
    return results


def summarize(arm: Arm, entries: list[Any], results: list[FileResult]) -> dict[str, Any]:
    by_name = {e.name: e for e in entries}
    readable = [r for r in results if by_name[r.name].expected_failure is None]
    expected_fail = [r for r in results if by_name[r.name].expected_failure is not None]
    hard_failures = [r for r in readable if not r.ok]
    scored = [r for r in readable if r.ok]

    def ratio(found: str, total: str, rows: list[FileResult]) -> float | None:
        denominator = sum(getattr(r, total) for r in rows)
        return None if denominator == 0 else sum(getattr(r, found) for r in rows) / denominator

    order_rows = [r for r in scored if r.order_ok is not None]
    times = [r.seconds for r in scored if r.seconds is not None]
    # Recall over text PDFs split by language.
    by_language: dict[str, float | None] = {}
    for lang in sorted(corpus.LANGUAGES):
        rows = [r for r in scored if by_name[r.name].language == lang and by_name[r.name].category == "contract_text"]
        by_language[lang] = ratio("phrases_found", "phrases_total", rows)
    tracked = [r for r in scored if r.tracked_inserted is not None and r.tracked_deleted is not None]
    return {
        "arm": arm.name,
        "scope": arm.scope,
        "files": len(entries),
        "readable_files": len(readable),
        "hard_failures": len(hard_failures),
        "hard_failure_files": {r.name: r.error for r in hard_failures},
        "expected_failures_total": len(expected_fail),
        "expected_failures_raised": sum(not r.ok for r in expected_fail),
        "expected_failure_silent": [r.name for r in expected_fail if r.ok],
        "phrase_recall": ratio("phrases_found", "phrases_total", scored),
        "table_cell_recall": ratio("cells_found", "cells_total", scored),
        "numeric_cell_recall": ratio("numeric_found", "numeric_total", scored),
        "reading_order_pass": f"{sum(bool(r.order_ok) for r in order_rows)}/{len(order_rows)}" if order_rows else None,
        "median_seconds_per_file": statistics.median(times) if times else None,
        "mean_seconds_per_file": statistics.fmean(times) if times else None,
        "recall_by_language_text_pdfs": by_language,
        "tracked_inserted_kept": (tracked[0].tracked_inserted if tracked else None),
        "tracked_deleted_kept": (tracked[0].tracked_deleted if tracked else None),
        "html_noise_leaked": next((r.noise_leaked for r in scored if r.noise_leaked is not None), None),
    }


# ---------------------------------------------------------------------------
# pdf_inspector page classification
# ---------------------------------------------------------------------------


@dataclass
class ClassStats:
    correct: int = 0
    total: int = 0
    files: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float | None:
        return None if self.total == 0 else self.correct / self.total


def classification(entries: list[Any]) -> dict[str, Any] | None:
    try:
        import pdf_inspector
    except ImportError:
        return None

    groups = {"mixed_pdf": ClassStats(), "text_scanned_pairs": ClassStats(), "all_readable_pdfs": ClassStats()}
    # process_pdf reports pages_needing_ocr with a different base from classify_pdf. Score it both ways.
    process_zero = ClassStats()
    process_one = ClassStats()
    doc_type_correct = 0
    doc_type_total = 0
    errors: dict[str, str] = {}
    expected_type = {"text": "text_based", "scanned": "scanned", "mixed": "mixed"}
    for entry in entries:
        if entry.kind != "pdf" or entry.expected_failure is not None or entry.damage is not None:
            continue
        truth = [k == "scanned" for k in entry.page_kinds]
        try:
            result = pdf_inspector.classify_pdf(str(entry.path))
            processed = pdf_inspector.process_pdf(str(entry.path))
        except Exception as exc:  # noqa: BLE001
            errors[entry.name] = f"{type(exc).__name__}: {exc}"
            continue
        predicted = set(result.pages_needing_ocr)
        correct = sum((i in predicted) == scanned for i, scanned in enumerate(truth))
        stat_targets = [groups["all_readable_pdfs"]]
        if entry.name == "layout_mixed_en.pdf":
            stat_targets.append(groups["mixed_pdf"])
        if entry.category in ("contract_text", "contract_scanned"):
            stat_targets.append(groups["text_scanned_pairs"])
        for stats in stat_targets:
            stats.correct += correct
            stats.total += len(truth)
            stats.files.append(entry.name)
        pred0 = set(processed.pages_needing_ocr)
        pred1 = {p - 1 for p in processed.pages_needing_ocr}
        process_zero.correct += sum((i in pred0) == scanned for i, scanned in enumerate(truth))
        process_one.correct += sum((i in pred1) == scanned for i, scanned in enumerate(truth))
        process_zero.total += len(truth)
        process_one.total += len(truth)
        kinds = set(entry.page_kinds)
        doc_kind = "mixed" if len(kinds) > 1 else next(iter(kinds))
        doc_type_total += 1
        doc_type_correct += result.pdf_type == expected_type[doc_kind]
    return {
        "classify_pdf_page_accuracy": {k: {"accuracy": v.accuracy, "pages": v.total} for k, v in groups.items()},
        "process_pdf_pages_needing_ocr_read_as_0_based": process_zero.accuracy,
        "process_pdf_pages_needing_ocr_read_as_1_based": process_one.accuracy,
        "document_type_accuracy": None if doc_type_total == 0 else doc_type_correct / doc_type_total,
        "document_type_files": doc_type_total,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def versions() -> dict[str, str]:
    out = {"python": platform.python_version(), "platform": platform.platform()}
    for dist in (
        "pdf-inspector",
        "pypdfium2",
        "pikepdf",
        "markitdown",
        "firecrawl-anydoc",
        "mammoth",
        "beautifulsoup4",
        "markdownify",
        "python-pptx",
        "openpyxl",
    ):
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            out[dist] = "not installed"
    try:
        proc = subprocess.run(["pdftotext", "-v"], capture_output=True, check=False)  # noqa: S603, S607
        first = (proc.stderr or proc.stdout).decode("utf-8", "replace").splitlines()
        out["pdftotext"] = first[0] if first else "unknown"
    except FileNotFoundError:
        out["pdftotext"] = "not installed"
    return out


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summaries = report["arms"]
    pdf_rows = [s for s in summaries if s["scope"] == "pdf"]
    office_rows = [s for s in summaries if s["scope"] == "office"]

    if pdf_rows:
        lines += [
            "### PDF files",
            "",
            "| Arm | Hard failures | Expected failures raised | Phrase recall "
            "| Table-cell recall | Reading order | s/file (median) |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in pdf_rows:
            lines.append(
                f"| {s['arm']} | {s['hard_failures']}/{s['readable_files']} "
                f"| {s['expected_failures_raised']}/{s['expected_failures_total']} "
                f"| {pct(s['phrase_recall'])} | {pct(s['table_cell_recall'])} "
                f"| {s['reading_order_pass'] or 'n/a'} | {seconds(s['median_seconds_per_file'])} |"
            )
        langs = sorted(corpus.LANGUAGES)
        lines += [
            "",
            "Phrase recall on the text PDFs of the contract set, by language:",
            "",
            "| Arm | " + " | ".join(langs) + " |",
            "|---|" + "---|" * len(langs),
        ]
        for s in pdf_rows:
            lines.append(
                f"| {s['arm']} | " + " | ".join(pct(s["recall_by_language_text_pdfs"][lang]) for lang in langs) + " |"
            )
        failures = [(s["arm"], n, e) for s in pdf_rows for n, e in s["hard_failure_files"].items()]
        if failures:
            lines += ["", "Hard failures:", "", "| Arm | File | Error |", "|---|---|---|"]
            lines += [f"| {a} | {n} | {e} |" for a, n, e in failures]
        silent = [(s["arm"], n) for s in pdf_rows for n in s["expected_failure_silent"]]
        if silent:
            lines += ["", "Expected failures that did not raise:", "", "| Arm | File |", "|---|---|"]
            lines += [f"| {a} | {n} |" for a, n in silent]

    cls = report.get("pdf_inspector_classification")
    if cls:
        acc = cls["classify_pdf_page_accuracy"]
        lines += [
            "",
            "### pdf_inspector page classification (text or scanned)",
            "",
            "| Set | Pages | Accuracy |",
            "|---|---|---|",
        ]
        for key, label in (
            ("mixed_pdf", "Mixed PDF (text, scan, text, scan)"),
            ("text_scanned_pairs", "Text and scanned pairs, 7 languages"),
            ("all_readable_pdfs", "All readable PDFs"),
        ):
            lines.append(f"| {label} | {acc[key]['pages']} | {pct(acc[key]['accuracy'])} |")
        lines += [
            "",
            f"Document type (text_based, scanned, mixed) correct on {pct(cls['document_type_accuracy'])} "
            f"of {cls['document_type_files']} files. "
            "`process_pdf().pages_needing_ocr` read as 0-based: "
            f"{pct(cls['process_pdf_pages_needing_ocr_read_as_0_based'])}, "
            f"as 1-based: {pct(cls['process_pdf_pages_needing_ocr_read_as_1_based'])}.",
        ]

    if office_rows:
        lines += [
            "",
            "### Office and HTML files",
            "",
            "| Arm | Hard failures | Phrase recall | Table-cell recall | Numeric-cell recall "
            "| Tracked: inserted / deleted kept | HTML script and style leaked | s/file (median) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in office_rows:
            ins, dele = s["tracked_inserted_kept"], s["tracked_deleted_kept"]
            tracked = "n/a" if ins is None or dele is None else f"{ins[0]}/{ins[1]} / {dele[0]}/{dele[1]}"
            leaked = {None: "n/a", True: "yes", False: "no"}[s["html_noise_leaked"]]
            lines.append(
                f"| {s['arm']} | {s['hard_failures']}/{s['readable_files']} "
                f"| {pct(s['phrase_recall'])} | {pct(s['table_cell_recall'])} | {pct(s['numeric_cell_recall'])} "
                f"| {tracked} | {leaked} | {seconds(s['median_seconds_per_file'])} |"
            )
        failures = [(s["arm"], n, e) for s in office_rows for n, e in s["hard_failure_files"].items()]
        if failures:
            lines += ["", "Hard failures:", "", "| Arm | File | Error |", "|---|---|---|"]
            lines += [f"| {a} | {n} | {e} |" for a, n, e in failures]

    if report["skipped"]:
        lines += ["", "Skipped arms:", ""]
        lines += [f"- {name}: {why}" for name, why in report["skipped"].items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-json", type=Path, help="write the full report as JSON")
    parser.add_argument("--out-md", type=Path, help="write the markdown tables")
    parser.add_argument(
        "--extra-path", type=Path, action="append", default=[], help="add to sys.path (throwaway installs)"
    )
    parser.add_argument("--repeats", type=int, default=3, help="timed calls per file (median is reported)")
    parser.add_argument("--only", action="append", default=[], help="run only arms whose name contains this text")
    args = parser.parse_args(argv)

    for extra in args.extra_path:
        sys.path.insert(0, str(extra))

    arms, skipped = build_arms()
    if args.only:
        arms = [a for a in arms if any(o in a.name for o in args.only)]
    entries = list(corpus.load_ground_truth().values())

    summaries: list[dict[str, Any]] = []
    per_file: dict[str, list[dict[str, Any]]] = {}
    for arm in arms:
        scope_entries = [e for e in entries if (e.kind == "pdf") == (arm.scope == "pdf")]
        results = run_arm(arm, scope_entries, max(1, args.repeats))
        summaries.append(summarize(arm, scope_entries, results))
        per_file[arm.name] = [r.__dict__ for r in results]
        print(f"done: {arm.name} ({len(scope_entries)} files)", file=sys.stderr)

    report: dict[str, Any] = {
        "versions": versions(),
        "corpus_files": len(entries),
        "repeats": max(1, args.repeats),
        "arms": summaries,
        "pdf_inspector_classification": classification(entries)
        if any("pdf_inspector" in a.name for a in arms)
        else None,
        "skipped": skipped,
        "per_file": per_file,
    }
    markdown = render_markdown(report)
    if args.out_json:
        args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
