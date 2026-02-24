"""GLM-OCR fallback extractor using the Zhipu AI GLM-OCR vision-language model.

Replaces ``pytesseract`` as the preferred OCR method for scanned/degraded
PDFs and images.  Two deployment backends are tried in order:

1. **mlx-vlm** (Apple Silicon) — fastest, loads the 4-bit quantized model
   locally via Apple's MLX framework.
2. **Ollama** (cross-platform) — uses ``ollama chat`` with the ``glm-ocr``
   model over localhost.

If neither backend is available the extractor returns ``("", 0.0)`` so
the pipeline falls through to the next method (pytesseract).

Optimal configuration (benchmarked on BLUERUSH data room):
    Model: mlx-community/GLM-OCR-4bit (1.25 GB)
    DPI: 150, max image dimension: 720px
    max_tokens: 2048, temperature: 0.0
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Confidence score for GLM-OCR output — higher than pytesseract (0.6)
# because GLM-OCR produces structured Markdown with fewer artifacts.
_CONFIDENCE_GLM_OCR = 0.8
_CONFIDENCE_FAILURE = 0.0

# ── Tuning constants (benchmarked on Apple M3 Max) ───────────────────
MODEL_ID_MLX = "mlx-community/GLM-OCR-4bit"
MODEL_ID_OLLAMA = "glm-ocr"
MAX_TOKENS = 2048
DPI = 150
MAX_IMAGE_DIM = 720
_MAX_PAGES = 100

# Extensions treated as direct images (no PDF-to-image conversion).
_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif"})


# ── Lazy import helpers ──────────────────────────────────────────────


def _import_pdfium() -> Any:
    """Return ``pypdfium2`` module if available, else *None*."""
    try:
        import pypdfium2

        return pypdfium2
    except ImportError:
        return None


def _import_mlx_vlm() -> tuple[Any, Any, Any] | None:
    """Return ``(load, generate, apply_chat_template)`` or *None*."""
    try:
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template

        return load, generate, apply_chat_template
    except (ImportError, ModuleNotFoundError):
        return None


def _import_ollama() -> Any:
    """Return the ``ollama`` module if available, else *None*."""
    try:
        import ollama

        return ollama
    except (ImportError, ModuleNotFoundError):
        return None


# ── PDF → image rendering ────────────────────────────────────────────


def _render_pdf_pages(filepath: Path, work_dir: Path) -> list[Path]:
    """Render PDF pages to PNG images using pypdfium2.

    Returns a list of image paths in *work_dir*.  Images are capped at
    :data:`MAX_IMAGE_DIM` pixels on their longest side (150 DPI base).
    """
    pdfium = _import_pdfium()
    if pdfium is None:
        logger.warning("pypdfium2 is not installed -- cannot render PDF pages for GLM-OCR")
        return []

    try:
        doc = pdfium.PdfDocument(str(filepath))
    except Exception:
        logger.exception("pypdfium2 failed to open %s", filepath)
        return []

    paths: list[Path] = []
    num_pages = min(len(doc), _MAX_PAGES)
    for i in range(num_pages):
        try:
            page = doc[i]
            bitmap = page.render(scale=DPI / 72)
            img = bitmap.to_pil()

            w, h = img.size
            if max(w, h) > MAX_IMAGE_DIM:
                ratio = MAX_IMAGE_DIM / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)))

            out_path = work_dir / f"page_{i + 1:03d}.png"
            img.save(str(out_path), optimize=True)
            paths.append(out_path)
        except Exception:
            logger.warning("Failed to render page %d of %s", i + 1, filepath)

    return paths


def _render_image_for_ocr(filepath: Path, work_dir: Path) -> list[Path]:
    """Prepare a single image file for OCR (resize if needed).

    Returns a one-element list containing the (possibly resized) image
    path, or an empty list on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow is not installed -- cannot load images for GLM-OCR")
        return []

    try:
        img: Any = Image.open(str(filepath))
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIM:
            ratio = MAX_IMAGE_DIM / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)))

        out_path = work_dir / "page_001.png"
        img.save(str(out_path), optimize=True)
        return [out_path]
    except Exception:
        logger.exception("Failed to prepare image %s for GLM-OCR", filepath)
        return []


# ── MLX-VLM backend ─────────────────────────────────────────────────


def _mlx_ocr_pages(image_paths: list[Path]) -> list[str]:
    """Run GLM-OCR on each image via mlx-vlm.  Returns per-page text."""
    imports = _import_mlx_vlm()
    if imports is None:
        return []

    load_fn, generate_fn, apply_chat_template_fn = imports

    model, processor = load_fn(MODEL_ID_MLX)

    results: list[str] = []
    for img_path in image_paths:
        try:
            formatted = apply_chat_template_fn(processor, model.config, "Text Recognition:", num_images=1)
            output = generate_fn(
                model,
                processor,
                formatted,
                image=[str(img_path)],
                max_tokens=MAX_TOKENS,
                temperature=0.0,
                verbose=False,
            )
            text = output if isinstance(output, str) else getattr(output, "text", str(output))
            results.append(text)
        except Exception:
            logger.warning("MLX GLM-OCR failed on %s", img_path)
            results.append("")

    return results


def _assemble_pages(page_texts: list[str]) -> str:
    """Combine per-page OCR results with ``--- Page N ---`` markers."""
    parts: list[str] = []
    for idx, text in enumerate(page_texts):
        if text.strip():
            parts.append(f"--- Page {idx + 1} ---\n{text}")
    return "\n\n".join(parts)


def _try_mlx_extract(filepath: Path) -> tuple[str, float]:
    """Attempt extraction via mlx-vlm.  Returns ``(text, confidence)``."""
    if _import_mlx_vlm() is None:
        logger.debug("mlx-vlm not available -- skipping MLX backend")
        return "", _CONFIDENCE_FAILURE

    work_dir = Path(tempfile.mkdtemp(prefix="dd_glm_mlx_"))
    try:
        suffix = filepath.suffix.lower()
        if suffix == ".pdf":
            image_paths = _render_pdf_pages(filepath, work_dir)
        elif suffix in _IMAGE_EXTENSIONS:
            image_paths = _render_image_for_ocr(filepath, work_dir)
        else:
            return "", _CONFIDENCE_FAILURE

        if not image_paths:
            return "", _CONFIDENCE_FAILURE

        page_texts = _mlx_ocr_pages(image_paths)
        if not page_texts or not any(t.strip() for t in page_texts):
            return "", _CONFIDENCE_FAILURE

        assembled = _assemble_pages(page_texts)
        return assembled, _CONFIDENCE_GLM_OCR
    except Exception:
        logger.exception("MLX GLM-OCR extraction failed for %s", filepath)
        return "", _CONFIDENCE_FAILURE
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Ollama backend ───────────────────────────────────────────────────


def _ollama_ocr_pages(image_paths: list[Path]) -> list[str]:
    """Run GLM-OCR on each image via Ollama.  Returns per-page text."""
    ollama = _import_ollama()
    if ollama is None:
        return []

    results: list[str] = []
    for img_path in image_paths:
        try:
            response = ollama.chat(
                model=MODEL_ID_OLLAMA,
                messages=[
                    {
                        "role": "user",
                        "content": "Text Recognition:",
                        "images": [str(img_path)],
                    }
                ],
            )
            text = response["message"]["content"]
            results.append(text if isinstance(text, str) else str(text))
        except Exception:
            logger.warning("Ollama GLM-OCR failed on %s", img_path)
            results.append("")

    return results


def _try_ollama_extract(filepath: Path) -> tuple[str, float]:
    """Attempt extraction via Ollama.  Returns ``(text, confidence)``."""
    if _import_ollama() is None:
        logger.debug("ollama not available -- skipping Ollama backend")
        return "", _CONFIDENCE_FAILURE

    work_dir = Path(tempfile.mkdtemp(prefix="dd_glm_ollama_"))
    try:
        suffix = filepath.suffix.lower()
        if suffix == ".pdf":
            image_paths = _render_pdf_pages(filepath, work_dir)
        elif suffix in _IMAGE_EXTENSIONS:
            image_paths = _render_image_for_ocr(filepath, work_dir)
        else:
            return "", _CONFIDENCE_FAILURE

        if not image_paths:
            return "", _CONFIDENCE_FAILURE

        page_texts = _ollama_ocr_pages(image_paths)
        if not page_texts or not any(t.strip() for t in page_texts):
            return "", _CONFIDENCE_FAILURE

        assembled = _assemble_pages(page_texts)
        return assembled, _CONFIDENCE_GLM_OCR
    except Exception:
        logger.exception("Ollama GLM-OCR extraction failed for %s", filepath)
        return "", _CONFIDENCE_FAILURE
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Public extractor class ───────────────────────────────────────────


class GlmOcrExtractor:
    """Extracts text from scanned PDFs and images using GLM-OCR.

    Tries mlx-vlm first (Apple Silicon, fastest), then Ollama
    (cross-platform).  Returns ``("", 0.0)`` if neither is available.

    Usage::

        extractor = GlmOcrExtractor()
        text, confidence = extractor.extract(Path("scanned_doc.pdf"))
    """

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text from *filepath* using GLM-OCR.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence)``.  Returns ``("", 0.0)`` on
            any failure (missing dependencies, unsupported format, etc.).
        """
        if not filepath.exists():
            return "", _CONFIDENCE_FAILURE

        suffix = filepath.suffix.lower()
        if suffix != ".pdf" and suffix not in _IMAGE_EXTENSIONS:
            logger.debug("GLM-OCR does not support extension %s", suffix)
            return "", _CONFIDENCE_FAILURE

        # Backend 1: mlx-vlm (Apple Silicon)
        text, conf = _try_mlx_extract(filepath)
        if text.strip():
            return text, conf

        # Backend 2: Ollama (cross-platform)
        text, conf = _try_ollama_extract(filepath)
        if text.strip():
            return text, conf

        return "", _CONFIDENCE_FAILURE
