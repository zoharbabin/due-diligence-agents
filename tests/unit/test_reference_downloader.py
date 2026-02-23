"""Unit tests for the external reference downloader (Issue #15).

Tests cover URL detection, T&C URL filtering, download caching,
safe filename generation, and error handling.  All HTTP calls are
mocked — no real network access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from dd_agents.extraction.reference_downloader import (
    ReferenceDownloader,
    _url_to_safe_filename,
    detect_urls,
    is_reference_url,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Test detect_urls
# ---------------------------------------------------------------------------


class TestDetectUrls:
    """Tests for the URL detection regex."""

    def test_simple_url(self) -> None:
        text = "See https://example.com/terms for details."
        urls = detect_urls(text)
        assert urls == ["https://example.com/terms"]

    def test_multiple_urls(self) -> None:
        text = "Terms at https://example.com/terms and privacy at https://example.com/privacy-policy"
        urls = detect_urls(text)
        assert len(urls) == 2
        assert "https://example.com/terms" in urls
        assert "https://example.com/privacy-policy" in urls

    def test_deduplication(self) -> None:
        text = "See https://example.com/terms here and also https://example.com/terms there."
        urls = detect_urls(text)
        assert len(urls) == 1

    def test_strips_trailing_punctuation(self) -> None:
        text = "Terms at https://example.com/terms."
        urls = detect_urls(text)
        assert urls == ["https://example.com/terms"]

    def test_http_url(self) -> None:
        text = "See http://example.com/terms for details."
        urls = detect_urls(text)
        assert urls == ["http://example.com/terms"]

    def test_no_urls(self) -> None:
        text = "No URLs in this text at all."
        assert detect_urls(text) == []

    def test_url_in_parentheses(self) -> None:
        text = "Terms available at (https://example.com/terms)"
        urls = detect_urls(text)
        assert urls == ["https://example.com/terms"]

    def test_complex_path(self) -> None:
        text = "See https://vendor.com/legal/terms-and-conditions/v2"
        urls = detect_urls(text)
        assert urls == ["https://vendor.com/legal/terms-and-conditions/v2"]


# ---------------------------------------------------------------------------
# Test is_reference_url
# ---------------------------------------------------------------------------


class TestIsReferenceUrl:
    """Tests for the T&C URL filtering heuristic."""

    def test_terms_url(self) -> None:
        assert is_reference_url("https://example.com/terms") is True

    def test_conditions_url(self) -> None:
        assert is_reference_url("https://example.com/conditions-of-service") is True

    def test_privacy_url(self) -> None:
        assert is_reference_url("https://example.com/privacy-policy") is True

    def test_sla_url(self) -> None:
        assert is_reference_url("https://example.com/sla") is True

    def test_eula_url(self) -> None:
        assert is_reference_url("https://example.com/eula") is True

    def test_legal_url(self) -> None:
        assert is_reference_url("https://example.com/legal/agreement") is True

    def test_dpa_url(self) -> None:
        assert is_reference_url("https://example.com/dpa") is True

    def test_social_media_excluded(self) -> None:
        assert is_reference_url("https://twitter.com/terms") is False

    def test_linkedin_excluded(self) -> None:
        assert is_reference_url("https://linkedin.com/legal/terms") is False

    def test_generic_url_rejected(self) -> None:
        assert is_reference_url("https://example.com/products/widget") is False

    def test_homepage_rejected(self) -> None:
        assert is_reference_url("https://example.com/") is False

    def test_no_path_rejected(self) -> None:
        assert is_reference_url("https://example.com") is False

    def test_acceptable_use_url(self) -> None:
        assert is_reference_url("https://example.com/acceptable-use") is True


# ---------------------------------------------------------------------------
# Test _url_to_safe_filename
# ---------------------------------------------------------------------------


class TestUrlToSafeFilename:
    """Tests for the URL-to-filename conversion."""

    def test_basic_url(self) -> None:
        result = _url_to_safe_filename("https://example.com/terms")
        assert result.startswith("__external__")
        assert result.endswith(".md")
        assert "example" in result
        assert "terms" in result

    def test_long_url_truncated(self) -> None:
        long_url = "https://example.com/" + "a" * 300
        result = _url_to_safe_filename(long_url)
        assert len(result) <= 200  # Reasonable limit

    def test_special_chars_replaced(self) -> None:
        result = _url_to_safe_filename("https://example.com/legal/terms-and-conditions?v=2")
        # Should not contain raw special chars.
        assert "?" not in result
        assert "/" not in result.replace("__external__", "")


# ---------------------------------------------------------------------------
# Test ReferenceDownloader
# ---------------------------------------------------------------------------


class TestReferenceDownloader:
    """Tests for the ReferenceDownloader class."""

    def test_scan_finds_urls(self, tmp_path: Path) -> None:
        """Scanner finds T&C URLs in extracted .md files."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        # Write a fake extracted file with a T&C URL.
        (text_dir / "customer_msa.md").write_text(
            "Contract text.\nExternal terms at https://vendor.com/general-terms-and-conditions/\nEnd of contract."
        )

        downloader = ReferenceDownloader(text_dir=text_dir)
        url_map = downloader._scan_for_urls()

        assert "https://vendor.com/general-terms-and-conditions/" in url_map

    def test_scan_deduplicates_across_files(self, tmp_path: Path) -> None:
        """Same URL in multiple files is downloaded once."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        url = "https://vendor.com/terms"
        (text_dir / "customer_a.md").write_text(f"Terms at {url}")
        (text_dir / "customer_b.md").write_text(f"Also see {url}")

        downloader = ReferenceDownloader(text_dir=text_dir)
        url_map = downloader._scan_for_urls()

        assert url in url_map
        assert len(url_map[url]) == 2  # Referenced from 2 files

    def test_cached_file_not_redownloaded(self, tmp_path: Path) -> None:
        """If output file already exists, download is skipped."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        url = "https://vendor.com/terms"
        safe_name = _url_to_safe_filename(url)
        cached = text_dir / safe_name
        cached.write_text("Previously cached T&C content.")

        downloader = ReferenceDownloader(text_dir=text_dir)
        result = downloader._download_and_extract(url)

        assert result.success is True
        assert result.content_length > 0
        # Original cached content should be preserved.
        assert cached.read_text() == "Previously cached T&C content."

    def test_empty_text_dir(self, tmp_path: Path) -> None:
        """Empty text directory produces no results."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        downloader = ReferenceDownloader(text_dir=text_dir)
        results = downloader.process_all()

        assert results == []

    def test_nonexistent_text_dir(self, tmp_path: Path) -> None:
        """Non-existent text directory produces no results."""
        text_dir = tmp_path / "nonexistent"
        downloader = ReferenceDownloader(text_dir=text_dir)
        results = downloader.process_all()
        assert results == []

    @patch("dd_agents.extraction.reference_downloader._fetch_url")
    @patch("dd_agents.extraction.reference_downloader._extract_text")
    def test_download_and_extract(
        self,
        mock_extract: MagicMock,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Successful download writes extracted text to cache."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        mock_fetch.return_value = b"<html><body>Terms and conditions content here</body></html>"
        mock_extract.return_value = (
            "# External Reference: https://vendor.com/terms\n\n"
            "These are the general terms and conditions that govern the use of our services. "
            "By accessing or using the services, you agree to be bound by these terms."
        )

        downloader = ReferenceDownloader(text_dir=text_dir)
        result = downloader._download_and_extract("https://vendor.com/terms")

        assert result.success is True
        assert result.content_length > 0
        # File should be written to disk.
        output = text_dir / _url_to_safe_filename("https://vendor.com/terms")
        assert output.exists()

    @patch("dd_agents.extraction.reference_downloader._fetch_url")
    def test_download_failure_non_blocking(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Download failures return DownloadResult with success=False."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        mock_fetch.side_effect = TimeoutError("Connection timed out")

        downloader = ReferenceDownloader(text_dir=text_dir)
        result = downloader._download_and_extract("https://vendor.com/terms")

        assert result.success is False
        assert "timed out" in result.error.lower()

    @patch("dd_agents.extraction.reference_downloader._fetch_url")
    @patch("dd_agents.extraction.reference_downloader._extract_text")
    def test_short_extraction_rejected(
        self,
        mock_extract: MagicMock,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Extracted text shorter than 50 chars is rejected."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        mock_fetch.return_value = b"<html><body>Hi</body></html>"
        mock_extract.return_value = "Hi"

        downloader = ReferenceDownloader(text_dir=text_dir)
        result = downloader._download_and_extract("https://vendor.com/terms")

        assert result.success is False
        assert "too short" in result.error.lower()

    @patch("dd_agents.extraction.reference_downloader._fetch_url")
    def test_empty_response_rejected(
        self,
        mock_fetch: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Empty HTTP response returns failure."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        mock_fetch.return_value = b""

        downloader = ReferenceDownloader(text_dir=text_dir)
        result = downloader._download_and_extract("https://vendor.com/terms")

        assert result.success is False

    def test_max_downloads_limit(self, tmp_path: Path) -> None:
        """Only max_downloads URLs are processed."""
        text_dir = tmp_path / "text"
        text_dir.mkdir()

        # Write file with many URLs.
        urls = "\n".join(f"https://vendor{i}.com/terms" for i in range(20))
        (text_dir / "customer.md").write_text(urls)

        downloader = ReferenceDownloader(text_dir=text_dir, max_downloads=3)

        with patch("dd_agents.extraction.reference_downloader._fetch_url") as mock_fetch:
            mock_fetch.side_effect = TimeoutError("skip")
            results = downloader.process_all()

        # Should only attempt max_downloads (3).
        assert len(results) == 3
