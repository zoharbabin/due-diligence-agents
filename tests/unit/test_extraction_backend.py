"""Tests for dd_agents.extraction.backend — protocol and chain.

Covers:
    - ExtractionBackend protocol satisfaction for all three extractors
    - ExtractionChain ordering (first successful backend wins)
    - ExtractionChain failure collection and logging
    - ExtractionChain return tuple (text, confidence, backend_name)
    - Backward compatibility of existing extractor constructors
    - Protocol runtime check via isinstance
    - Empty chain returns failure tuple
    - All backends skipped (unsupported extension) returns failure tuple
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from dd_agents.extraction.backend import ExtractionBackend, ExtractionChain
from dd_agents.extraction.glm_ocr import GlmOcrExtractor
from dd_agents.extraction.markitdown import MarkitdownExtractor
from dd_agents.extraction.ocr import OCRExtractor

if TYPE_CHECKING:
    import pytest

# ======================================================================
# Helpers — mock backends for chain tests
# ======================================================================


class _SuccessBackend:
    """Mock backend that always succeeds."""

    def __init__(self, name: str, extensions: frozenset[str], text: str, confidence: float) -> None:
        self._name = name
        self._extensions = extensions
        self._text = text
        self._confidence = confidence

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_extensions(self) -> frozenset[str]:
        return self._extensions

    def extract(self, filepath: Path) -> tuple[str, float]:
        return self._text, self._confidence


class _FailBackend:
    """Mock backend that always raises."""

    def __init__(self, name: str, extensions: frozenset[str]) -> None:
        self._name = name
        self._extensions = extensions

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_extensions(self) -> frozenset[str]:
        return self._extensions

    def extract(self, filepath: Path) -> tuple[str, float]:
        raise RuntimeError(f"{self._name} extraction failed")


class _EmptyBackend:
    """Mock backend that returns empty text with zero confidence."""

    def __init__(self, name: str, extensions: frozenset[str]) -> None:
        self._name = name
        self._extensions = extensions

    @property
    def name(self) -> str:
        return self._name

    @property
    def supported_extensions(self) -> frozenset[str]:
        return self._extensions

    def extract(self, filepath: Path) -> tuple[str, float]:
        return "", 0.0


# ======================================================================
# Test: Protocol satisfaction
# ======================================================================


class TestExtractionBackendProtocol:
    """All three concrete extractors satisfy the ExtractionBackend protocol."""

    def test_markitdown_satisfies_protocol(self) -> None:
        """MarkitdownExtractor is recognized as an ExtractionBackend."""
        extractor = MarkitdownExtractor()
        assert isinstance(extractor, ExtractionBackend)

    def test_ocr_satisfies_protocol(self) -> None:
        """OCRExtractor is recognized as an ExtractionBackend."""
        extractor = OCRExtractor()
        assert isinstance(extractor, ExtractionBackend)

    def test_glm_ocr_satisfies_protocol(self) -> None:
        """GlmOcrExtractor is recognized as an ExtractionBackend."""
        extractor = GlmOcrExtractor()
        assert isinstance(extractor, ExtractionBackend)

    def test_mock_backend_satisfies_protocol(self) -> None:
        """A structurally conforming mock also satisfies the protocol."""
        backend = _SuccessBackend("mock", frozenset({".pdf"}), "text", 0.9)
        assert isinstance(backend, ExtractionBackend)

    def test_plain_object_does_not_satisfy_protocol(self) -> None:
        """An arbitrary object without the required members fails the check."""
        assert not isinstance(object(), ExtractionBackend)
        assert not isinstance("a string", ExtractionBackend)


# ======================================================================
# Test: Backward compatibility — constructors still work
# ======================================================================


class TestBackwardCompatibility:
    """Existing extractor constructors work without arguments."""

    def test_markitdown_constructor(self) -> None:
        ext = MarkitdownExtractor()
        assert ext.name == "markitdown"
        assert isinstance(ext.supported_extensions, frozenset)
        assert ".pdf" in ext.supported_extensions

    def test_ocr_constructor(self) -> None:
        ext = OCRExtractor()
        assert ext.name == "pytesseract"
        assert isinstance(ext.supported_extensions, frozenset)
        assert ".pdf" in ext.supported_extensions

    def test_glm_ocr_constructor(self) -> None:
        ext = GlmOcrExtractor()
        assert ext.name == "glm_ocr"
        assert isinstance(ext.supported_extensions, frozenset)
        assert ".pdf" in ext.supported_extensions


# ======================================================================
# Test: ExtractionChain ordering
# ======================================================================


class TestExtractionChainOrdering:
    """ExtractionChain tries backends in declared order, first success wins."""

    def test_first_backend_wins(self) -> None:
        """When multiple backends support the extension, the first one's result is returned."""
        b1 = _SuccessBackend("backend_1", frozenset({".pdf"}), "text from b1", 0.9)
        b2 = _SuccessBackend("backend_2", frozenset({".pdf"}), "text from b2", 0.8)
        chain = ExtractionChain([b1, b2])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        text, confidence, name = chain.extract(filepath)
        assert text == "text from b1"
        assert confidence == 0.9
        assert name == "backend_1"

    def test_fallback_to_second_on_failure(self) -> None:
        """If the first backend raises, the chain falls through to the next one."""
        b1 = _FailBackend("fail_backend", frozenset({".pdf"}))
        b2 = _SuccessBackend("fallback_backend", frozenset({".pdf"}), "fallback text", 0.7)
        chain = ExtractionChain([b1, b2])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        text, confidence, name = chain.extract(filepath)
        assert text == "fallback text"
        assert confidence == 0.7
        assert name == "fallback_backend"

    def test_fallback_skips_empty_result(self) -> None:
        """A backend returning empty text is treated as failure; chain continues."""
        b1 = _EmptyBackend("empty_backend", frozenset({".pdf"}))
        b2 = _SuccessBackend("good_backend", frozenset({".pdf"}), "real content", 0.85)
        chain = ExtractionChain([b1, b2])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        text, confidence, name = chain.extract(filepath)
        assert text == "real content"
        assert confidence == 0.85
        assert name == "good_backend"


# ======================================================================
# Test: Failure collection
# ======================================================================


class TestExtractionChainFailureCollection:
    """Failed backends are tracked and logged."""

    def test_all_failures_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """When all backends fail with exceptions, a warning is logged listing each."""
        b1 = _FailBackend("backend_a", frozenset({".pdf"}))
        b2 = _FailBackend("backend_b", frozenset({".pdf"}))
        chain = ExtractionChain([b1, b2])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        with caplog.at_level("WARNING", logger="dd_agents.extraction.backend"):
            text, confidence, name = chain.extract(filepath)

        assert text == ""
        assert confidence == 0.0
        assert name == ""
        # Both backend names should appear in the warning log
        assert any("backend_a" in record.message and "backend_b" in record.message for record in caplog.records)


# ======================================================================
# Test: Return tuple shape
# ======================================================================


class TestExtractionChainReturnTuple:
    """ExtractionChain.extract always returns (str, float, str)."""

    def test_success_returns_three_tuple(self) -> None:
        b = _SuccessBackend("test_be", frozenset({".docx"}), "extracted content", 0.95)
        chain = ExtractionChain([b])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".docx"

        result = chain.extract(filepath)
        assert isinstance(result, tuple)
        assert len(result) == 3
        text, confidence, backend_name = result
        assert isinstance(text, str)
        assert isinstance(confidence, float)
        assert isinstance(backend_name, str)
        assert text == "extracted content"
        assert confidence == 0.95
        assert backend_name == "test_be"

    def test_failure_returns_three_tuple(self) -> None:
        b = _FailBackend("broken", frozenset({".pdf"}))
        chain = ExtractionChain([b])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        result = chain.extract(filepath)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result == ("", 0.0, "")


# ======================================================================
# Test: Empty chain
# ======================================================================


class TestExtractionChainEmpty:
    """An empty chain returns the failure tuple on extract."""

    def test_empty_chain_returns_failure(self) -> None:
        chain = ExtractionChain([])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".pdf"

        text, confidence, name = chain.extract(filepath)
        assert text == ""
        assert confidence == 0.0
        assert name == ""


# ======================================================================
# Test: All backends skipped (unsupported extension)
# ======================================================================


class TestExtractionChainSkipped:
    """When no backend supports the file extension, all are skipped."""

    def test_unsupported_extension_returns_failure(self) -> None:
        """Backends only supporting .pdf are skipped for a .xyz file."""
        b1 = _SuccessBackend("pdf_only", frozenset({".pdf"}), "pdf text", 0.9)
        b2 = _SuccessBackend("also_pdf", frozenset({".pdf", ".docx"}), "docx text", 0.85)
        chain = ExtractionChain([b1, b2])

        filepath = MagicMock(spec=Path)
        filepath.suffix = ".xyz"

        text, confidence, name = chain.extract(filepath)
        assert text == ""
        assert confidence == 0.0
        assert name == ""

    def test_extension_matching_is_case_insensitive(self) -> None:
        """The chain lowercases the suffix before matching."""
        b = _SuccessBackend("case_test", frozenset({".pdf"}), "found it", 0.9)
        chain = ExtractionChain([b])

        filepath = MagicMock(spec=Path)
        # Path.suffix returns as-is; the chain calls .lower() on it
        filepath.suffix = ".PDF"

        text, confidence, name = chain.extract(filepath)
        assert text == "found it"
        assert confidence == 0.9
        assert name == "case_test"
