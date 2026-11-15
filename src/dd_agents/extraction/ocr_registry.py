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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dd_agents.extraction.backend import ExtractionBackend
    from dd_agents.extraction.pipeline import ExtractionPipeline

logger = logging.getLogger(__name__)


def _ocr_preference_from_config(deal_config: Any) -> str:
    """Extract ``extraction.ocr_backend`` from a raw-dict or typed deal config.

    Returns ``"auto"`` when unset or unreadable.
    """
    if isinstance(deal_config, dict):
        extraction_cfg = deal_config.get("extraction", {})
        if isinstance(extraction_cfg, dict):
            value = extraction_cfg.get("ocr_backend", "auto")
            return str(value) if value else "auto"
        return "auto"
    extraction = getattr(deal_config, "extraction", None)
    return str(getattr(extraction, "ocr_backend", "auto") or "auto")


def _ocr_languages_from_config(deal_config: Any) -> list[str]:
    """Extract ``extraction.ocr_languages`` (default ``["eng"]``). Raises ``ValueError`` on bad codes."""
    from dd_agents.extraction.languages import validate_language_codes

    if isinstance(deal_config, dict):
        extraction_cfg = deal_config.get("extraction", {})
        value = extraction_cfg.get("ocr_languages") if isinstance(extraction_cfg, dict) else None
    else:
        value = getattr(getattr(deal_config, "extraction", None), "ocr_languages", None)
    return validate_language_codes(value or ["eng"])


def _office_backend_from_config(deal_config: Any) -> str:
    """Extract ``extraction.office_backend`` (default ``"markitdown"``). Raises ``ValueError`` on unknown values."""
    from dd_agents.models.config import ExtractionConfig

    if isinstance(deal_config, dict):
        extraction_cfg = deal_config.get("extraction", {})
        value = extraction_cfg.get("office_backend") if isinstance(extraction_cfg, dict) else None
    else:
        value = getattr(getattr(deal_config, "extraction", None), "office_backend", None)
    if not value:
        return "markitdown"
    return str(ExtractionConfig(office_backend=value).office_backend)


def build_extraction_pipeline(deal_config: Any = None) -> ExtractionPipeline:
    """Build an ``ExtractionPipeline`` with the config-selected OCR backend.

    The ONE seam for OCR-backend selection: reads ``extraction.ocr_backend``
    from the deal config (raw dict or typed), resolves it through
    :meth:`OCRBackendRegistry.get_backend`, and wires a GLM-OCR backend into the
    pipeline only when one is actually available — otherwise the pipeline relies
    on its pytesseract path, which uses ``extraction.ocr_languages``. Both the orchestrator and the standalone
    search command call this so OCR selection can never drift between them.
    """
    from dd_agents.extraction.glm_ocr import GlmOcrExtractor
    from dd_agents.extraction.ocr import OCRExtractor
    from dd_agents.extraction.pipeline import ExtractionPipeline

    preference = _ocr_preference_from_config(deal_config)
    backend = OCRBackendRegistry.get_backend(preference)
    return ExtractionPipeline(
        ocr=OCRExtractor(languages=_ocr_languages_from_config(deal_config)),
        glm_ocr=backend if isinstance(backend, GlmOcrExtractor) else None,
        office_backend=_office_backend_from_config(deal_config),
    )


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
