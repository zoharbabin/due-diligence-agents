"""``dd-agents extraction`` commands: check OCR language setup on this machine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import click

from dd_agents.extraction.languages import (
    check_language_setup,
    installed_tesseract_languages,
    script_counts,
    script_warnings,
    validate_language_codes,
)


@click.group()
def extraction() -> None:
    """Check document extraction and OCR language support."""


@extraction.command("check")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Deal config to read extraction.ocr_languages from.",
)
@click.option("--languages", help="Comma-separated Tesseract codes, e.g. deu,eng. Overrides the config.")
@click.argument("sample", required=False, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def check(config_path: Path | None, languages: str | None, sample: Path | None) -> None:
    """Check that the OCR language packs you need are installed.

    Reads only: nothing is written to the project. With SAMPLE (a PDF, image or
    text file), extracts it and warns when it contains a script that no
    configured language can read.

    \b
      dd-agents extraction check --languages deu,eng
      dd-agents extraction check --config deal-config.json scan.pdf

    Exit code 1 means a language pack is missing or the sample shows a mismatch.
    """
    backend = "auto"
    requested: list[str]
    if languages:
        raw = [part.strip() for part in languages.split(",") if part.strip()]
    elif config_path is not None:
        from dd_agents.config import ConfigFileNotFoundError, ConfigParseError, ConfigValidationError, load_deal_config

        try:
            cfg = load_deal_config(config_path)
        except (ConfigFileNotFoundError, ConfigParseError, ConfigValidationError) as exc:
            raise click.UsageError(str(exc)) from exc
        raw = list(cfg.extraction.ocr_languages)
        backend = cfg.extraction.ocr_backend
    else:
        raw = ["eng"]
    try:
        requested = validate_language_codes(raw)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    failed = False
    setup = check_language_setup(requested, installed_tesseract_languages())
    click.echo(f"Requested languages: {', '.join(requested)}")
    if setup.installed is None:
        click.echo("Tesseract: not found or not readable. Install it, or use GLM-OCR (reads any script).")
    else:
        click.echo(f"Tesseract packs installed: {', '.join(setup.installed) or 'none'}")
        if setup.missing:
            failed = True
            click.echo(f"Missing: {', '.join(setup.missing)}. Install the packs (e.g. brew install tesseract-lang).")
        else:
            click.echo("All requested language packs are installed.")

    from dd_agents.extraction.ocr_registry import OCRBackendRegistry

    available = OCRBackendRegistry.detect_available()
    click.echo(f"OCR backends detected: {', '.join(available) or 'none'}")
    if any(name.startswith("glm_ocr") for name in available) and backend in ("auto", "glm_ocr"):
        click.echo("GLM-OCR is preferred and reads any script. ocr_languages applies to the Tesseract fallback.")

    if sample is not None:
        failed |= _check_sample(sample, requested, backend)

    raise SystemExit(1 if failed else 0)


def _check_sample(sample: Path, requested: list[str], backend: str) -> bool:
    from dd_agents.extraction.ocr_registry import build_extraction_pipeline
    from dd_agents.extraction.pipeline import ExtractionPipeline

    pipeline = build_extraction_pipeline({"extraction": {"ocr_backend": backend, "ocr_languages": requested}})
    with tempfile.TemporaryDirectory(prefix="dd_extraction_check_") as tmp:
        out_dir = Path(tmp)
        pipeline.extract_single(filepath=sample.resolve(), output_dir=out_dir)
        out_file = out_dir / ExtractionPipeline._safe_text_name(str(sample.resolve()))
        text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""

    counts = script_counts(text)
    click.echo(f"\nSample: {sample.name}: {sum(counts.values())} letters extracted")
    for script, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        click.echo(f"  {script}: {count}")
    warnings = script_warnings(text, requested)
    if not text.strip():
        click.echo("No text extracted. Check the language packs, or try a different OCR backend.")
        return True
    for warning in warnings:
        click.echo(f"WARNING: {warning}")
    return bool(warnings)
