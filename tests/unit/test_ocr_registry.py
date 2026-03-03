"""Unit tests for dd_agents.extraction.ocr_registry.OCRBackendRegistry.

Covers:
- detect_available returns a list of strings
- get_backend with "auto" preference
- get_backend with explicit "pytesseract" preference
- get_backend with explicit "glm_ocr" preference
- get_backend with "auto" when nothing available returns None
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dd_agents.extraction.ocr_registry import OCRBackendRegistry


class TestDetectAvailable:
    """Tests for OCRBackendRegistry.detect_available."""

    def test_returns_list_of_strings(self) -> None:
        """detect_available must always return a list of strings."""
        result = OCRBackendRegistry.detect_available()
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    def test_detect_all_backends_present(self) -> None:
        """When all optional packages are importable, all backends appear."""
        with (
            patch.dict("sys.modules", {"mlx_vlm": __import__("types")}),
            patch("builtins.__import__", side_effect=_make_import_allowing({"mlx_vlm", "ollama", "pytesseract"})),
        ):
            result = OCRBackendRegistry.detect_available()

        assert "glm_ocr_mlx" in result
        assert "glm_ocr_ollama" in result
        assert "pytesseract" in result

    def test_detect_none_available(self) -> None:
        """When no OCR packages are installed, return an empty list."""
        with patch("builtins.__import__", side_effect=_make_import_blocking({"mlx_vlm", "ollama", "pytesseract"})):
            result = OCRBackendRegistry.detect_available()

        assert result == []


class TestGetBackend:
    """Tests for OCRBackendRegistry.get_backend."""

    def test_auto_returns_none_when_nothing_available(self) -> None:
        """get_backend('auto') returns None when no OCR package is installed."""
        with patch.object(OCRBackendRegistry, "detect_available", return_value=[]):
            result = OCRBackendRegistry.get_backend("auto")

        assert result is None

    def test_auto_returns_backend_when_pytesseract_available(self) -> None:
        """get_backend('auto') falls through to pytesseract when no GLM-OCR is available."""
        mock_extractor = MagicMock()
        mock_ocr_module = MagicMock()
        mock_ocr_module.OCRExtractor.return_value = mock_extractor

        with (
            patch.object(OCRBackendRegistry, "detect_available", return_value=["pytesseract"]),
            patch.dict("sys.modules", {"dd_agents.extraction.ocr": mock_ocr_module}),
        ):
            result = OCRBackendRegistry.get_backend("auto")

        assert result is mock_extractor

    def test_pytesseract_preference_returns_none_when_missing(self) -> None:
        """get_backend('pytesseract') returns None when pytesseract is not installed."""
        with patch("builtins.__import__", side_effect=_make_import_blocking({"pytesseract"})):
            result = OCRBackendRegistry.get_backend("pytesseract")

        assert result is None

    def test_glm_ocr_preference_returns_backend_when_mlx_available(self) -> None:
        """get_backend('glm_ocr') returns GlmOcrExtractor when mlx-vlm is available."""
        mock_extractor = MagicMock()
        mock_glm_module = MagicMock()
        mock_glm_module.GlmOcrExtractor.return_value = mock_extractor

        with (
            patch.object(OCRBackendRegistry, "detect_available", return_value=["glm_ocr_mlx"]),
            patch.dict("sys.modules", {"dd_agents.extraction.glm_ocr": mock_glm_module}),
        ):
            result = OCRBackendRegistry.get_backend("glm_ocr")

        assert result is mock_extractor

    def test_glm_ocr_preference_falls_back_to_pytesseract(self) -> None:
        """get_backend('glm_ocr') falls back to pytesseract when GLM-OCR is unavailable."""
        mock_extractor = MagicMock()
        mock_ocr_module = MagicMock()
        mock_ocr_module.OCRExtractor.return_value = mock_extractor

        with (
            patch.object(OCRBackendRegistry, "detect_available", return_value=["pytesseract"]),
            patch.dict("sys.modules", {"dd_agents.extraction.ocr": mock_ocr_module}),
        ):
            result = OCRBackendRegistry.get_backend("glm_ocr")

        assert result is mock_extractor

    def test_glm_ocr_preference_returns_none_when_nothing_available(self) -> None:
        """get_backend('glm_ocr') returns None when neither GLM-OCR nor pytesseract is installed."""
        with patch.object(OCRBackendRegistry, "detect_available", return_value=[]):
            result = OCRBackendRegistry.get_backend("glm_ocr")

        assert result is None


# ---------------------------------------------------------------------------
# Helpers for controlling imports in tests
# ---------------------------------------------------------------------------

_real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[union-attr]


def _make_import_blocking(blocked: set[str]):  # type: ignore[no-untyped-def]
    """Return an __import__ replacement that raises ImportError for *blocked* modules."""

    def _import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        top_level = name.split(".")[0]
        if top_level in blocked:
            raise ImportError(f"Mocked: {name} not installed")
        return _real_import(name, *args, **kwargs)

    return _import


def _make_import_allowing(allowed: set[str]):  # type: ignore[no-untyped-def]
    """Return an __import__ replacement that fakes success for *allowed* modules.

    For allowed modules, returns a dummy module object.  For everything else,
    delegates to the real import.
    """
    import types

    def _import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        top_level = name.split(".")[0]
        if top_level in allowed:
            mod = types.ModuleType(name)
            if name == "mlx_vlm":
                mod.load = lambda *a, **kw: None  # type: ignore[attr-defined]
            return mod
        return _real_import(name, *args, **kwargs)

    return _import
