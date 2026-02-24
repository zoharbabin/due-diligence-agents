"""Tests for the dd_agents.extraction.glm_ocr module.

Covers:
    - GlmOcrExtractor: extract on PDF and image files
    - Graceful fallback when mlx-vlm is not installed
    - Graceful fallback when Ollama is not available
    - Page marker formatting (``--- Page N ---``)
    - Image resize logic (720px cap)
    - max_tokens / temperature / DPI configuration
    - Integration with ExtractionPipeline as fallback step
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from dd_agents.extraction.glm_ocr import GlmOcrExtractor

# ======================================================================
# Helpers
# ======================================================================


def _fake_pdfium_document(num_pages: int = 3, page_width: int = 612, page_height: int = 792) -> MagicMock:
    """Create a mock pypdfium2.PdfDocument with *num_pages* pages."""
    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=num_pages)

    pages = []
    for _ in range(num_pages):
        page = MagicMock()
        bitmap = MagicMock()
        img = MagicMock()
        img.size = (page_width, page_height)
        img.resize = MagicMock(return_value=img)
        bitmap.to_pil.return_value = img
        page.render.return_value = bitmap
        pages.append(page)

    doc.__getitem__ = MagicMock(side_effect=lambda idx: pages[idx])
    return doc


# ======================================================================
# GlmOcrExtractor — unit tests
# ======================================================================


class TestGlmOcrExtractor:
    """Tests for GlmOcrExtractor."""

    def test_extract_returns_tuple(self) -> None:
        """extract() returns (str, float) tuple."""
        extractor = GlmOcrExtractor()
        result = extractor.extract(Path("/nonexistent/file.pdf"))
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)

    def test_extract_nonexistent_file(self) -> None:
        """Non-existent file returns empty string with 0.0 confidence."""
        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(Path("/nonexistent/file.pdf"))
        assert text == ""
        assert conf == 0.0

    def test_extract_unsupported_extension(self, tmp_path: Path) -> None:
        """Unsupported file extensions return empty output."""
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake xlsx content")

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(f)
        assert text == ""
        assert conf == 0.0

    @patch("dd_agents.extraction.glm_ocr._try_mlx_extract")
    def test_extract_pdf_via_mlx(self, mock_mlx: MagicMock, tmp_path: Path) -> None:
        """PDF extraction via mlx-vlm returns page-marked text."""
        src = tmp_path / "contract.pdf"
        src.write_bytes(b"%PDF-1.4 fake content")

        page_texts = [
            "THIS AGREEMENT is made on the Effective Date.",
            "1. Definitions. Channel Partner means BlueRush.",
            "2. Territory. The Territory shall be worldwide.",
        ]
        mock_mlx.return_value = (
            "\n\n".join(f"--- Page {i + 1} ---\n{t}" for i, t in enumerate(page_texts)),
            0.8,
        )

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(src)

        assert "--- Page 1 ---" in text
        assert "--- Page 2 ---" in text
        assert "--- Page 3 ---" in text
        assert "THIS AGREEMENT" in text
        assert "Definitions" in text
        assert conf == 0.8

    @patch("dd_agents.extraction.glm_ocr._try_mlx_extract", return_value=("", 0.0))
    @patch("dd_agents.extraction.glm_ocr._try_ollama_extract")
    def test_extract_pdf_falls_back_to_ollama(
        self, mock_ollama: MagicMock, mock_mlx: MagicMock, tmp_path: Path
    ) -> None:
        """When mlx-vlm fails, Ollama is tried as fallback."""
        src = tmp_path / "contract.pdf"
        src.write_bytes(b"%PDF-1.4 fake content")

        mock_ollama.return_value = (
            "--- Page 1 ---\nOllama extracted text.",
            0.8,
        )

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(src)

        mock_mlx.assert_called_once()
        mock_ollama.assert_called_once()
        assert "Ollama extracted text" in text
        assert conf == 0.8

    @patch("dd_agents.extraction.glm_ocr._try_mlx_extract", return_value=("", 0.0))
    @patch("dd_agents.extraction.glm_ocr._try_ollama_extract", return_value=("", 0.0))
    def test_extract_both_backends_fail(self, mock_ollama: MagicMock, mock_mlx: MagicMock, tmp_path: Path) -> None:
        """When both backends fail, returns empty with 0.0 confidence."""
        src = tmp_path / "contract.pdf"
        src.write_bytes(b"%PDF-1.4 fake content")

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(src)

        assert text == ""
        assert conf == 0.0

    @patch("dd_agents.extraction.glm_ocr._try_mlx_extract")
    def test_extract_image_file(self, mock_mlx: MagicMock, tmp_path: Path) -> None:
        """Direct image files are processed as single-page documents."""
        src = tmp_path / "scan.png"
        src.write_bytes(b"\x89PNG fake image data")

        mock_mlx.return_value = (
            "--- Page 1 ---\nScanned text from image.",
            0.8,
        )

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(src)

        assert "--- Page 1 ---" in text
        assert "Scanned text" in text
        assert conf == 0.8

    @patch("dd_agents.extraction.glm_ocr._try_mlx_extract")
    def test_extract_tiff_image(self, mock_mlx: MagicMock, tmp_path: Path) -> None:
        """TIFF images are supported."""
        src = tmp_path / "scan.tiff"
        src.write_bytes(b"II\x2a\x00 fake tiff")

        mock_mlx.return_value = ("--- Page 1 ---\nTIFF text.", 0.8)

        extractor = GlmOcrExtractor()
        text, conf = extractor.extract(src)
        assert conf == 0.8

    def test_confidence_score_value(self) -> None:
        """Confidence constants are within Pydantic's [0.0, 1.0] range."""
        from dd_agents.extraction.glm_ocr import _CONFIDENCE_FAILURE, _CONFIDENCE_GLM_OCR

        assert 0.0 <= _CONFIDENCE_GLM_OCR <= 1.0
        assert _CONFIDENCE_FAILURE == 0.0
        # GLM-OCR should be higher than pytesseract (0.6)
        assert _CONFIDENCE_GLM_OCR > 0.6


# ======================================================================
# MLX backend — _try_mlx_extract
# ======================================================================


class TestMlxBackend:
    """Tests for the mlx-vlm extraction backend."""

    def test_mlx_unavailable_returns_empty(self, tmp_path: Path) -> None:
        """When mlx_vlm is not installed, returns empty gracefully."""
        from dd_agents.extraction.glm_ocr import _try_mlx_extract

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        with patch.dict("sys.modules", {"mlx_vlm": None}):
            text, conf = _try_mlx_extract(src)

        assert text == ""
        assert conf == 0.0

    @patch("dd_agents.extraction.glm_ocr._mlx_ocr_pages")
    @patch("dd_agents.extraction.glm_ocr._render_pdf_pages")
    @patch("dd_agents.extraction.glm_ocr._import_mlx_vlm", return_value=(MagicMock(), MagicMock(), MagicMock()))
    def test_mlx_pdf_with_page_markers(
        self, mock_import: MagicMock, mock_render: MagicMock, mock_ocr: MagicMock, tmp_path: Path
    ) -> None:
        """MLX extraction produces correct page markers for PDFs."""
        from dd_agents.extraction.glm_ocr import _try_mlx_extract

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        mock_render.return_value = [
            tmp_path / "p1.png",
            tmp_path / "p2.png",
        ]
        mock_ocr.return_value = ["Page one text.", "Page two text."]

        text, conf = _try_mlx_extract(src)

        assert "--- Page 1 ---" in text
        assert "--- Page 2 ---" in text
        assert "Page one text." in text
        assert "Page two text." in text
        assert conf > 0.0

    @patch("dd_agents.extraction.glm_ocr._mlx_ocr_pages")
    @patch("dd_agents.extraction.glm_ocr._render_pdf_pages")
    @patch("dd_agents.extraction.glm_ocr._import_mlx_vlm", return_value=(MagicMock(), MagicMock(), MagicMock()))
    def test_mlx_empty_pages_skipped(
        self, mock_import: MagicMock, mock_render: MagicMock, mock_ocr: MagicMock, tmp_path: Path
    ) -> None:
        """Pages with empty OCR output are still included with markers."""
        from dd_agents.extraction.glm_ocr import _try_mlx_extract

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        mock_render.return_value = [tmp_path / "p1.png", tmp_path / "p2.png"]
        mock_ocr.return_value = ["Real text here.", ""]

        text, conf = _try_mlx_extract(src)

        # Only non-empty pages contribute
        assert "--- Page 1 ---" in text
        assert "Real text here." in text
        assert conf > 0.0


# ======================================================================
# Ollama backend — _try_ollama_extract
# ======================================================================


class TestOllamaBackend:
    """Tests for the Ollama extraction backend."""

    def test_ollama_unavailable_returns_empty(self, tmp_path: Path) -> None:
        """When ollama is not installed, returns empty gracefully."""
        from dd_agents.extraction.glm_ocr import _try_ollama_extract

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        with patch.dict("sys.modules", {"ollama": None}):
            text, conf = _try_ollama_extract(src)

        assert text == ""
        assert conf == 0.0


# ======================================================================
# PDF rendering — _render_pdf_pages
# ======================================================================


class TestRenderPdfPages:
    """Tests for PDF-to-image rendering logic."""

    def test_render_creates_temp_images(self, tmp_path: Path) -> None:
        """_render_pdf_pages produces image paths in a temp directory."""
        from dd_agents.extraction.glm_ocr import _render_pdf_pages

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        mock_doc = _fake_pdfium_document(num_pages=3)

        with patch("dd_agents.extraction.glm_ocr._import_pdfium") as mock_import:
            mock_import.return_value = MagicMock(PdfDocument=MagicMock(return_value=mock_doc))
            paths = _render_pdf_pages(src, tmp_path)

        assert len(paths) == 3
        for p in paths:
            assert p.suffix == ".png"

    def test_render_caps_image_dimension(self, tmp_path: Path) -> None:
        """Images exceeding MAX_IMAGE_DIM are resized."""
        from dd_agents.extraction.glm_ocr import MAX_IMAGE_DIM, _render_pdf_pages

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Create a mock doc with an oversized page (2000x3000)
        mock_doc = _fake_pdfium_document(num_pages=1, page_width=2000, page_height=3000)

        with patch("dd_agents.extraction.glm_ocr._import_pdfium") as mock_import:
            mock_import.return_value = MagicMock(PdfDocument=MagicMock(return_value=mock_doc))
            _render_pdf_pages(src, tmp_path)

        # The mock page's image.resize should have been called since 3000 > MAX_IMAGE_DIM
        page = mock_doc[0]
        img = page.render().to_pil()
        img.resize.assert_called_once()
        # Verify the resize target respects the cap
        call_args = img.resize.call_args[0][0]
        assert max(call_args) <= MAX_IMAGE_DIM

    def test_render_no_resize_when_small(self, tmp_path: Path) -> None:
        """Images within MAX_IMAGE_DIM are not resized."""
        from dd_agents.extraction.glm_ocr import _render_pdf_pages

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        # Page within limits
        mock_doc = _fake_pdfium_document(num_pages=1, page_width=500, page_height=600)

        with patch("dd_agents.extraction.glm_ocr._import_pdfium") as mock_import:
            mock_import.return_value = MagicMock(PdfDocument=MagicMock(return_value=mock_doc))
            _render_pdf_pages(src, tmp_path)

        page = mock_doc[0]
        img = page.render().to_pil()
        img.resize.assert_not_called()

    def test_render_pdfium_unavailable(self, tmp_path: Path) -> None:
        """When pypdfium2 is not installed, returns empty list."""
        from dd_agents.extraction.glm_ocr import _render_pdf_pages

        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        with patch("dd_agents.extraction.glm_ocr._import_pdfium", return_value=None):
            paths = _render_pdf_pages(src, tmp_path)

        assert paths == []


# ======================================================================
# Pipeline integration
# ======================================================================


class TestPipelineIntegration:
    """Tests for GlmOcrExtractor within ExtractionPipeline."""

    def test_pipeline_uses_glm_ocr_before_pytesseract(self, tmp_path: Path) -> None:
        """When injected, GLM-OCR runs as step 4 before pytesseract (step 5)."""
        from dd_agents.extraction.ocr import OCRExtractor
        from dd_agents.extraction.pipeline import ExtractionPipeline

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        glm_text = "--- Page 1 ---\nGLM-OCR extracted the scanned contract text successfully. " * 10

        glm_extractor = GlmOcrExtractor()
        ocr_extractor = OCRExtractor()
        pipeline = ExtractionPipeline(glm_ocr=glm_extractor, ocr=ocr_extractor)

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=""),
            patch.object(pipeline, "_run_pdftotext", return_value=""),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(glm_extractor, "extract", return_value=(glm_text, 0.8)),
            patch.object(ocr_extractor, "extract") as mock_pytesseract,
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_glm_ocr"
        assert entry.confidence == 0.8
        assert "glm_ocr" in entry.fallback_chain
        # pytesseract should NOT have been called
        mock_pytesseract.assert_not_called()

    def test_pipeline_falls_through_to_pytesseract(self, tmp_path: Path) -> None:
        """When GLM-OCR fails, pipeline continues to pytesseract."""
        from dd_agents.extraction.ocr import OCRExtractor
        from dd_agents.extraction.pipeline import ExtractionPipeline

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        ocr_text = "pytesseract extracted text from scanned document. " * 20

        glm_extractor = GlmOcrExtractor()
        ocr_extractor = OCRExtractor()
        pipeline = ExtractionPipeline(glm_ocr=glm_extractor, ocr=ocr_extractor)

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=""),
            patch.object(pipeline, "_run_pdftotext", return_value=""),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(glm_extractor, "extract", return_value=("", 0.0)),
            patch.object(ocr_extractor, "extract", return_value=(ocr_text, 0.6)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.6
        assert "glm_ocr" in entry.fallback_chain
        assert "ocr" in entry.fallback_chain

    def test_pipeline_works_without_glm_ocr(self, tmp_path: Path) -> None:
        """Pipeline without GLM-OCR injected skips directly to pytesseract."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scanned.pdf"
        src.write_bytes(b"%PDF-1.4 fake")

        ocr_text = "pytesseract fallback text. " * 20

        pipeline = ExtractionPipeline()  # No glm_ocr injected

        with (
            patch.object(pipeline, "_run_pymupdf", return_value=""),
            patch.object(pipeline, "_run_pdftotext", return_value=""),
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(pipeline._ocr, "extract", return_value=(ocr_text, 0.6)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_ocr"
        assert entry.confidence == 0.6
        # glm_ocr should NOT appear in the chain
        assert "glm_ocr" not in entry.fallback_chain

    def test_pipeline_image_uses_glm_ocr(self, tmp_path: Path) -> None:
        """GLM-OCR is also used for image files when injected."""
        from dd_agents.extraction.pipeline import ExtractionPipeline

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        src = tmp_path / "scan.png"
        src.write_bytes(b"\x89PNG fake image data here enough bytes")

        glm_text = "--- Page 1 ---\nGLM-OCR image text extraction. " * 10

        glm_extractor = GlmOcrExtractor()
        pipeline = ExtractionPipeline(glm_ocr=glm_extractor)

        with (
            patch.object(pipeline._markitdown, "extract", return_value=("", 0.0)),
            patch.object(glm_extractor, "extract", return_value=(glm_text, 0.8)),
        ):
            entry = pipeline.extract_single(src, output_dir)

        assert entry.method == "fallback_glm_ocr"
        assert entry.confidence == 0.8
