"""Download external T&Cs referenced by URL in extracted documents.

Contracts frequently incorporate external Terms & Conditions by URL
reference (e.g. ``https://vendor.com/general-terms-and-conditions/``).
This module detects those URLs, downloads the content, extracts text
via ``markitdown``, and caches the result in the text index with an
``__external__`` prefix.

**Important**: Downloaded references are stored alongside customer
extractions but are NOT automatically included in any customer's
analysis context.  The search analyzer only reads files listed in
``customer.files`` from the customer registry — never by globbing
the text directory.  External references are available for future
vendor/infrastructure analysis but must be explicitly opted-in.

This step is **non-blocking**: download failures are logged as
warnings but never halt the pipeline.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Regex to detect URLs in extracted markdown text.
_URL_PATTERN = re.compile(r"https?://[^\s\)\]>\"']+")

# Path keywords that indicate a T&C / legal document URL.
_TC_PATH_KEYWORDS: frozenset[str] = frozenset(
    {
        "terms",
        "conditions",
        "tos",
        "terms-of-service",
        "terms_of_service",
        "termsofservice",
        "exhibit",
        "policy",
        "policies",
        "schedule",
        "agreement",
        "privacy",
        "acceptable-use",
        "acceptable_use",
        "acceptableuse",
        "sla",
        "eula",
        "end-user",
        "license",
        "legal",
        "compliance",
        "data-processing",
        "dpa",
        "subprocessor",
    }
)

# Pre-compiled regex from keyword set for faster matching.
_TC_KEYWORD_PATTERN = re.compile("|".join(re.escape(kw) for kw in _TC_PATH_KEYWORDS))

# Maximum content size to download (5 MB).
_MAX_CONTENT_BYTES = 5 * 1024 * 1024

# Default timeout for HTTP requests (seconds).
_DEFAULT_TIMEOUT = 30

# Maximum number of URLs to download per run.
_DEFAULT_MAX_DOWNLOADS = 50

# Default number of parallel download workers.
_DEFAULT_WORKERS = 8


@dataclass
class DownloadResult:
    """Result of downloading and extracting a single external reference."""

    url: str
    success: bool
    output_path: str = ""
    error: str = ""
    content_length: int = 0
    referencing_files: list[str] = field(default_factory=list)


class ReferenceDownloader:
    """Detect and download external T&Cs referenced in extracted text.

    Parameters
    ----------
    text_dir:
        Directory containing extracted ``.md`` text files.
    timeout:
        HTTP request timeout in seconds.
    max_downloads:
        Maximum number of URLs to download per invocation.
    max_content_bytes:
        Maximum response body size to accept.
    workers:
        Number of parallel download threads.
    """

    def __init__(
        self,
        text_dir: Path,
        timeout: int = _DEFAULT_TIMEOUT,
        max_downloads: int = _DEFAULT_MAX_DOWNLOADS,
        max_content_bytes: int = _MAX_CONTENT_BYTES,
        workers: int = _DEFAULT_WORKERS,
    ) -> None:
        self._text_dir = text_dir
        self._timeout = timeout
        self._max_downloads = max_downloads
        self._max_content_bytes = max_content_bytes
        self._workers = workers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_all(self) -> list[DownloadResult]:
        """Scan all ``.md`` files in text_dir, download referenced T&Cs.

        Returns a list of :class:`DownloadResult` for each URL processed.
        """
        # Phase 1: Scan all .md files for URLs.
        url_map = self._scan_for_urls()

        if not url_map:
            logger.info("No external reference URLs found in extracted text.")
            return []

        logger.info(
            "Found %d candidate external reference URLs across %d files.",
            len(url_map),
            sum(len(files) for files in url_map.values()),
        )

        # Phase 2: Download and extract (parallel).
        urls_to_process = list(url_map.items())[: self._max_downloads]
        results: list[DownloadResult] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._workers) as executor:
            future_to_url = {
                executor.submit(self._download_and_extract, url): (url, refs) for url, refs in urls_to_process
            }
            try:
                for future in concurrent.futures.as_completed(future_to_url):
                    url, referencing_files = future_to_url[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        logger.warning("Download thread failed for %s: %s", url, exc)
                        result = DownloadResult(url=url, success=False, error=str(exc))
                    result.referencing_files = referencing_files
                    results.append(result)
            except KeyboardInterrupt:
                logger.warning("Reference download interrupted — cancelling pending downloads")
                for f in future_to_url:
                    f.cancel()
                raise

        succeeded = sum(1 for r in results if r.success)
        failed = len(results) - succeeded
        logger.info(
            "External reference download complete: %d succeeded, %d failed.",
            succeeded,
            failed,
        )

        return results

    # ------------------------------------------------------------------
    # URL detection and filtering
    # ------------------------------------------------------------------

    def _scan_for_urls(self) -> dict[str, list[str]]:
        """Scan .md files and return URL -> list of referencing file names.

        Deduplicates URLs across files: each URL is downloaded once.
        Skips ``__external__*`` files to avoid recursive URL discovery
        from previously downloaded references.
        """
        url_map: dict[str, list[str]] = {}

        if not self._text_dir.exists():
            return url_map

        for md_file in sorted(self._text_dir.glob("*.md")):
            # Skip previously downloaded external references.
            if md_file.name.startswith("__external__"):
                continue

            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            urls = detect_urls(text)
            for url in urls:
                if is_reference_url(url):
                    url_map.setdefault(url, []).append(md_file.name)

        return url_map

    def _download_and_extract(self, url: str) -> DownloadResult:
        """Download a URL and extract text content.

        Uses ``markitdown`` for HTML-to-markdown conversion.
        Falls back to raw text if markitdown fails.
        """
        output_name = _url_to_safe_filename(url)
        output_path = self._text_dir / output_name

        # Check if already cached.
        if output_path.exists() and output_path.stat().st_size > 0:
            logger.debug("External reference already cached: %s", url)
            return DownloadResult(
                url=url,
                success=True,
                output_path=str(output_path),
                content_length=output_path.stat().st_size,
            )

        # Download.
        try:
            raw_bytes = _fetch_url(url, self._timeout, self._max_content_bytes)
        except Exception as exc:
            logger.warning("Failed to download %s: %s", url, exc)
            return DownloadResult(url=url, success=False, error=str(exc))

        if not raw_bytes:
            return DownloadResult(url=url, success=False, error="Empty response")

        # Extract text.
        text = _extract_text(raw_bytes, url)
        if not text or len(text.strip()) < 50:
            return DownloadResult(
                url=url,
                success=False,
                error="Extracted text too short or empty",
            )

        # Write to cache.
        try:
            output_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            return DownloadResult(url=url, success=False, error=f"Write failed: {exc}")

        return DownloadResult(
            url=url,
            success=True,
            output_path=str(output_path),
            content_length=len(text),
        )


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, easy to test)
# ---------------------------------------------------------------------------


def detect_urls(text: str) -> list[str]:
    """Extract unique URLs from text.

    Strips trailing punctuation that is commonly appended to URLs in
    document text (periods, commas, semicolons).
    """
    raw_matches = _URL_PATTERN.findall(text)
    seen: set[str] = set()
    urls: list[str] = []
    for url in raw_matches:
        # Strip trailing punctuation that may have been captured.
        url = url.rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def is_reference_url(url: str) -> bool:
    """Return True if the URL likely points to a T&C or legal document.

    Heuristic: the URL path must contain at least one keyword from
    :data:`_TC_PATH_KEYWORDS`.

    No domain exclusion is applied -- if a URL appears in a legal
    contract and its path matches a legal keyword (``agreement``,
    ``terms``, ``policy``, etc.), it was put there for a reason and
    should be downloaded.  The downstream analyzer controls which
    files are actually included in each customer's analysis context.
    """
    lower = url.lower()

    # Extract the path portion (after the domain).
    path_start = lower.find("/", lower.find("//") + 2)
    if path_start == -1:
        return False

    path = lower[path_start:]
    return _TC_KEYWORD_PATTERN.search(path) is not None


def _url_to_safe_filename(url: str) -> str:
    """Convert a URL to a safe cache filename.

    Format: ``__external__<domain>__<path_slug>.md``
    """
    # Remove scheme.
    clean = re.sub(r"^https?://", "", url)
    # Replace non-alphanumeric with underscore.
    slug = re.sub(r"[^a-zA-Z0-9]", "_", clean)
    # Collapse underscores and trim.
    slug = re.sub(r"_+", "_", slug).strip("_")

    # Ensure filename is not too long.
    if len(slug) > 150:
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        slug = slug[:130] + "_" + digest

    return f"__external__{slug}.md"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block HTTP redirects to prevent SSRF via redirect to internal IPs."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        from dd_agents.net_safety import UnsafeURLError, validate_url

        try:
            validate_url(newurl, allow_http=True)
        except UnsafeURLError as exc:
            raise urllib.error.URLError(f"Redirect blocked by SSRF check: {exc}") from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _fetch_url(url: str, timeout: int, max_bytes: int) -> bytes:
    """Fetch URL content via urllib (stdlib, no new dependencies).

    Raises on network errors, timeouts, and oversized responses.
    Validates the URL against private/reserved IP ranges before fetching.
    Redirect targets are re-validated to prevent SSRF via redirect.
    """
    from dd_agents.net_safety import validate_url

    validate_url(url, allow_http=True)

    opener = urllib.request.build_opener(_NoRedirectHandler)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; dd-agents/0.1; +legal-due-diligence)",
        },
    )
    with opener.open(req, timeout=timeout) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(f"Content too large: {content_length} bytes (max {max_bytes})")

        data: bytes = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"Response exceeded max size ({max_bytes} bytes)")

        return data


def _extract_text(raw_bytes: bytes, url: str) -> str:
    """Extract readable text from downloaded content.

    Tries ``markitdown`` first (handles HTML well), falls back to
    UTF-8 decode.
    """
    # Try markitdown for HTML content.
    tmp_path: str | None = None
    try:
        import tempfile

        from markitdown import MarkItDown

        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        md = MarkItDown()
        result = md.convert(tmp_path)
        if result and result.text_content and len(result.text_content.strip()) >= 50:
            # Prepend source URL as a header.
            return f"# External Reference: {url}\n\n{result.text_content}"
    except Exception:
        logger.debug("markitdown failed for %s, falling back to raw decode", url)
    finally:
        if tmp_path is not None:
            import contextlib
            import os

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    # Fallback: raw UTF-8 decode.
    try:
        text = raw_bytes.decode("utf-8", errors="replace")
        if text.strip():
            return f"# External Reference: {url}\n\n{text}"
    except Exception:
        logger.debug("UTF-8 decode fallback failed for %s", url)

    return ""
