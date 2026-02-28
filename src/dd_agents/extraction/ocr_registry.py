"""OCR backend auto-detection and selection registry.

Provides runtime discovery of available OCR backends (GLM-OCR via mlx-vlm,
GLM-OCR via Ollama, pytesseract) and config-driven selection.

Configuration
-------------
Set ``extraction.ocr_backend`` in deal-config.json:

- ``"auto"`` (default): detect best available backend
- ``"glm_ocr"``: force GLM-OCR (mlx-vlm or Ollama)
- ``"pytesseract"``: force pytesseract
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dd_agents.extraction.backend import ExtractionBackend

logger = logging.getLogger(__name__)


class OCRBackendRegistry:
    """Auto-detect and select the best available OCR backend."""

    @staticmethod
    def detect_available() -> list[str]:
        """Return names of available OCR backends in preference order.

        Detection order:
        1. glm_ocr (mlx-vlm) — Apple Silicon, fastest
        2. glm_ocr (ollama)   — cross-platform
        3. pytesseract         — widely available
        """
        available: list[str] = []

        # Check mlx-vlm
        try:
            from mlx_vlm import load as _  # noqa: F401

            available.append("glm_ocr_mlx")
        except (ImportError, ModuleNotFoundError):
            pass

        # Check ollama
        try:
            import ollama as _  # noqa: F401

            available.append("glm_ocr_ollama")
        except (ImportError, ModuleNotFoundError):
            pass

        # Check pytesseract
        try:
            import pytesseract as _  # noqa: F401

            available.append("pytesseract")
        except ImportError:
            pass

        return available

    @staticmethod
    def get_backend(preference: str = "auto") -> ExtractionBackend | None:
        """Return the selected OCR backend based on *preference*.

        Parameters
        ----------
        preference:
            One of ``"auto"``, ``"glm_ocr"``, or ``"pytesseract"``.

        Returns
        -------
        ExtractionBackend | None
            The selected backend, or ``None`` if nothing is available.
        """
        if preference == "pytesseract":
            try:
                import pytesseract as _  # noqa: F401

                from dd_agents.extraction.ocr import OCRExtractor

                return OCRExtractor()
            except ImportError:
                logger.warning("pytesseract requested but not installed")
                return None

        if preference in ("glm_ocr", "auto"):
            from dd_agents.extraction.glm_ocr import GlmOcrExtractor

            # Check if any GLM-OCR backend is available
            available = OCRBackendRegistry.detect_available()
            if any(name.startswith("glm_ocr") for name in available):
                return GlmOcrExtractor()
            if preference == "glm_ocr":
                logger.warning("glm_ocr requested but neither mlx-vlm nor ollama is installed")
                if "pytesseract" in available:
                    logger.info("Falling back to pytesseract")
                    from dd_agents.extraction.ocr import OCRExtractor

                    return OCRExtractor()
                return None

        # auto: fall through to pytesseract
        if preference == "auto":
            available = OCRBackendRegistry.detect_available()
            if "pytesseract" in available:
                from dd_agents.extraction.ocr import OCRExtractor

                return OCRExtractor()

        if preference not in ("auto", "glm_ocr", "pytesseract"):
            logger.warning("Unrecognized OCR backend preference: %r (valid: auto, glm_ocr, pytesseract)", preference)
        return None
