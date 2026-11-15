"""OCR fallback extractor using ``pytesseract``.

Used when the primary ``markitdown`` extraction returns insufficient
text (e.g. scanned PDFs, photographed documents).  Stages work in a
temporary directory to avoid polluting the data room.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dd_agents.extraction._constants import CONFIDENCE_FAILURE, IMAGE_EXTENSIONS
from dd_agents.extraction._constants import CONFIDENCE_OCR as _CONFIDENCE_OCR
from dd_agents.extraction.languages import validate_language_codes

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Per-page timeout in seconds (configurable externally if needed).
OCR_PAGE_TIMEOUT = 30


_OCR_EXTENSIONS: frozenset[str] = frozenset({".pdf"} | IMAGE_EXTENSIONS)


class OCRExtractor:
    """Extracts text via Tesseract OCR (``pytesseract``).

    Handles both image files directly and PDFs (by converting pages
    to images with ``pdf2image`` first).

    If ``pytesseract`` is not installed the extractor gracefully
    returns empty output rather than raising.

    Usage::

        extractor = OCRExtractor()
        text, confidence = extractor.extract(Path("scanned_doc.pdf"))
    """

    def __init__(self, languages: Sequence[str] = ("eng",)) -> None:
        self._languages = validate_language_codes(languages)

    @property
    def lang(self) -> str:
        """Tesseract ``lang`` argument, e.g. ``deu+eng``."""
        return "+".join(self._languages)

    @property
    def name(self) -> str:
        return "pytesseract"

    @property
    def supported_extensions(self) -> frozenset[str]:
        return _OCR_EXTENSIONS

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text from *filepath* using Tesseract OCR.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence)``.  Returns ``("", 0.0)`` on
            any failure (missing dependencies, unreadable file, etc.).
        """
        try:
            import pytesseract
        except ImportError:
            logger.warning(
                "pytesseract is not installed -- OCR fallback unavailable.  Install with: pip install pytesseract"
            )
            return "", CONFIDENCE_FAILURE

        work_dir = Path(tempfile.mkdtemp(prefix="dd_ocr_"))
        try:
            return self._do_extract(filepath, work_dir, pytesseract, self.lang)
        except Exception as exc:
            exc_msg = str(exc).lower()
            if "password" in exc_msg or "encrypted" in exc_msg:
                logger.debug("Skipping password-protected file for OCR: %s", filepath.name)
            else:
                logger.warning("OCR extraction failed for %s: %s", filepath.name, exc)
            return "", CONFIDENCE_FAILURE
        finally:
            # Always clean up the temporary working directory.
            shutil.rmtree(work_dir, ignore_errors=True)

    def extract_pages(self, filepath: Path, pages: Sequence[int]) -> dict[int, str]:
        """OCR only the given 1-based *pages* of a PDF. Returns ``{page: text}`` for pages with text."""
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract is not installed -- page OCR unavailable")
            return {}

        work_dir = Path(tempfile.mkdtemp(prefix="dd_ocr_"))
        out: dict[int, str] = {}
        try:
            for number in pages:
                try:
                    image = self._page_image(filepath, number, work_dir)
                    if image is None:
                        continue
                    text: str = pytesseract.image_to_string(image, lang=self.lang)
                except Exception as exc:
                    logger.warning("OCR failed for page %d of %s: %s", number, filepath.name, exc)
                    continue
                if text.strip():
                    out[number] = text
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        return out

    @staticmethod
    def _page_image(filepath: Path, number: int, work_dir: Path) -> Any:
        """Render one 1-based PDF page with ``pdf2image``. ``None`` if it cannot be rendered."""
        try:
            from pdf2image import convert_from_path
        except ImportError:
            logger.warning("pdf2image is not installed -- cannot render PDF pages for OCR")
            return None
        images = convert_from_path(
            str(filepath), output_folder=str(work_dir), fmt="png", dpi=300, first_page=number, last_page=number
        )
        return images[0] if images else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _do_extract(
        filepath: Path,
        work_dir: Path,
        pytesseract: object,
        lang: str = "eng",
    ) -> tuple[str, float]:
        """Core extraction logic (separated for testability)."""
        suffix = filepath.suffix.lower()

        if suffix == ".pdf":
            images = OCRExtractor._pdf_to_images(filepath, work_dir)
        elif suffix in IMAGE_EXTENSIONS:
            images = OCRExtractor._load_image(filepath)
        else:
            logger.debug("OCR does not support extension %s", suffix)
            return "", CONFIDENCE_FAILURE

        if not images:
            return "", CONFIDENCE_FAILURE

        texts: list[str] = []
        for idx, img in enumerate(images):
            try:
                page_text: str = pytesseract.image_to_string(img, lang=lang)  # type: ignore[attr-defined]
                if page_text.strip():
                    texts.append(f"--- Page {idx + 1} ---\n{page_text}")
            except Exception:
                logger.warning("OCR failed for page %d of %s", idx + 1, filepath)

        if texts:
            return "\n\n".join(texts), _CONFIDENCE_OCR
        return "", CONFIDENCE_FAILURE

    @staticmethod
    def _pdf_to_images(filepath: Path, work_dir: Path) -> list[Any]:
        """Convert PDF pages to PIL images using ``pdf2image``."""
        try:
            from pdf2image import convert_from_path
        except ImportError:
            logger.warning(
                "pdf2image is not installed -- cannot convert PDF for OCR.  Install with: pip install pdf2image"
            )
            return []

        result: list[Any] = convert_from_path(
            str(filepath),
            output_folder=str(work_dir),
            fmt="png",
            dpi=300,
            first_page=1,
            last_page=50,  # Cap at 50 pages for OCR
        )
        return result

    @staticmethod
    def _load_image(filepath: Path) -> list[Any]:
        """Load a single image file as a one-element list."""
        try:
            from PIL import Image
        except ImportError:
            logger.warning("Pillow is not installed -- cannot load images for OCR.  Install with: pip install Pillow")
            return []

        img = Image.open(str(filepath))
        img.load()  # type: ignore[no-untyped-call]  # Force file handle release.
        return [img]
