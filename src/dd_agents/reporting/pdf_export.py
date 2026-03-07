"""PDF export from HTML report (Issue #151).

Converts the self-contained HTML DD report to a print-optimized PDF
using Playwright (preferred) or WeasyPrint (fallback).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Detect available PDF engines at import time.
PLAYWRIGHT_AVAILABLE = False
WEASYPRINT_AVAILABLE = False

try:
    from playwright.async_api import async_playwright as _async_pw  # type: ignore[import-not-found]  # noqa: F401

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

try:
    from weasyprint import HTML as _WeasyHTML  # type: ignore[import-not-found]  # noqa: F401, N811

    WEASYPRINT_AVAILABLE = True
except ImportError:
    pass


class PDFExportError(Exception):
    """Raised when PDF export fails or no engine is available."""


async def _export_with_playwright(html_path: Path, output_path: Path) -> Path:
    """Export using headless Chromium via Playwright."""
    from playwright.async_api import async_playwright  # type: ignore[import-not-found]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(html_path.as_uri(), wait_until="networkidle")
        await page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={"top": "15mm", "bottom": "15mm", "left": "10mm", "right": "10mm"},
        )
        await browser.close()

    return output_path


async def _export_with_weasyprint(html_path: Path, output_path: Path) -> Path:
    """Export using WeasyPrint (CSS Paged Media)."""
    from weasyprint import HTML  # type: ignore[import-not-found]

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: HTML(filename=str(html_path)).write_pdf(str(output_path)))
    return output_path


async def export_pdf(
    html_path: Path,
    output_path: Path | None = None,
    *,
    engine: str = "auto",
) -> Path:
    """Convert an HTML report to PDF.

    Parameters
    ----------
    html_path:
        Path to the self-contained HTML report file.
    output_path:
        Destination PDF path.  Defaults to same name with ``.pdf`` suffix.
    engine:
        ``"auto"`` (prefer Playwright), ``"playwright"``, or ``"weasyprint"``.

    Returns
    -------
    Path to the generated PDF file.

    Raises
    ------
    PDFExportError
        If the requested engine is unavailable or export fails.
    FileNotFoundError
        If *html_path* does not exist.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"HTML report not found: {html_path}")

    if output_path is None:
        output_path = html_path.with_suffix(".pdf")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    engines: dict[str, Any] = {}
    if PLAYWRIGHT_AVAILABLE:
        engines["playwright"] = _export_with_playwright
    if WEASYPRINT_AVAILABLE:
        engines["weasyprint"] = _export_with_weasyprint

    if engine == "auto":
        if not engines:
            raise PDFExportError(
                "No PDF engine available. Install one of:\n"
                "  pip install playwright && playwright install chromium\n"
                "  pip install weasyprint"
            )
        selected = next(iter(engines.values()))
    elif engine in engines:
        selected = engines[engine]
    else:
        raise PDFExportError(
            f"PDF engine '{engine}' is not available. Available engines: {list(engines.keys()) or ['none']}"
        )

    try:
        result: Path = await selected(html_path, output_path)
        logger.info("PDF exported: %s (%d bytes)", result, result.stat().st_size)
        return result
    except PDFExportError:
        raise
    except Exception as exc:
        raise PDFExportError(f"PDF export failed: {exc}") from exc
