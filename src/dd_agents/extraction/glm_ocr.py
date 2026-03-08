"""GLM-OCR fallback extractor using the Zhipu AI GLM-OCR vision-language model.

Replaces ``pytesseract`` as the preferred OCR method for scanned/degraded
PDFs and images.  Two deployment backends are tried in order:

1. **mlx-vlm** (Apple Silicon) — fastest, loads the 8-bit quantized model
   locally via Apple's MLX framework.
2. **Ollama** (cross-platform) — uses ``ollama chat`` with the ``glm-ocr``
   model over localhost.

If neither backend is available the extractor returns ``("", 0.0)`` so
the pipeline falls through to the next method (pytesseract).

Optimal configuration (benchmarked on production data room):
    Model: mlx-community/GLM-OCR-8bit (1.5 GB)
    DPI: 200, max image dimension: 1024px
    max_tokens: 2048, temperature: 0.0

Resolution is the dominant quality factor — increasing from 720px to
1024px fixed all 4 benchmark errors (Notwithstanding, retitling, solely,
claims) with only ~2s/page additional cost.  Quantization (4-bit vs 8-bit
vs bf16) had minimal impact on accuracy.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from dd_agents.extraction._constants import CONFIDENCE_FAILURE, IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

# Confidence score for GLM-OCR output — higher than pytesseract (0.6)
# because GLM-OCR produces structured Markdown with fewer artifacts.
_CONFIDENCE_GLM_OCR = 0.8

# ── Tuning constants (benchmarked on Apple M3 Max) ───────────────────
MODEL_ID_MLX = "mlx-community/GLM-OCR-8bit"
MODEL_ID_OLLAMA = "glm-ocr"
MAX_TOKENS = 2048
DPI = 200
MAX_IMAGE_DIM = 1024
_MAX_PAGES = 100


# ── Image helpers ────────────────────────────────────────────────────


def _resize_image(img: Any, max_dim: int = MAX_IMAGE_DIM) -> Any:
    """Resize *img* so its longest side does not exceed *max_dim*.

    Returns the original image unchanged if already within limits.
    """
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        return img.resize((int(w * ratio), int(h * ratio)))
    return img


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
    :data:`MAX_IMAGE_DIM` pixels on their longest side.
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
    try:
        num_pages = min(len(doc), _MAX_PAGES)
        for i in range(num_pages):
            try:
                page = doc[i]
                bitmap = page.render(scale=DPI / 72)
                img = bitmap.to_pil()
                img = _resize_image(img)

                out_path = work_dir / f"page_{i + 1:03d}.png"
                img.save(str(out_path), optimize=True)
                paths.append(out_path)
            except Exception:
                logger.warning("Failed to render page %d of %s", i + 1, filepath)
    finally:
        doc.close()

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
        try:
            img = _resize_image(img)

            out_path = work_dir / "page_001.png"
            img.save(str(out_path), optimize=True)
            return [out_path]
        finally:
            img.close()
    except Exception:
        logger.exception("Failed to prepare image %s for GLM-OCR", filepath)
        return []


def _prepare_images(filepath: Path, work_dir: Path) -> list[Path]:
    """Route *filepath* to the appropriate image renderer.

    PDFs are rendered via :func:`_render_pdf_pages`; recognised image
    extensions via :func:`_render_image_for_ocr`.  Unsupported formats
    return an empty list.
    """
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf_pages(filepath, work_dir)
    if suffix in IMAGE_EXTENSIONS:
        return _render_image_for_ocr(filepath, work_dir)
    return []


# ── Page assembly ────────────────────────────────────────────────────


def _assemble_pages(page_texts: list[str]) -> str:
    """Combine per-page OCR results with ``--- Page N ---`` markers."""
    parts: list[str] = []
    for idx, text in enumerate(page_texts):
        if text.strip():
            parts.append(f"--- Page {idx + 1} ---\n{text}")
    return "\n\n".join(parts)


# ── MLX-VLM backend (per-page OCR, uses cached model) ───────────────


def _mlx_ocr_pages(
    image_paths: list[Path],
    model: Any,
    processor: Any,
    generate_fn: Any,
    apply_chat_template_fn: Any,
) -> list[str]:
    """Run GLM-OCR on each image via mlx-vlm.  Returns per-page text.

    *model* and *processor* are pre-loaded by the caller to avoid
    re-downloading/re-loading on every file.  *generate_fn* and
    *apply_chat_template_fn* are passed in from the caller so that
    ``_import_mlx_vlm`` is called once in ``_try_mlx_extract``.
    """
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


def _try_mlx_extract(filepath: Path, model: Any, processor: Any) -> tuple[str, float]:
    """Attempt extraction via mlx-vlm.  Returns ``(text, confidence)``.

    *model* and *processor* are pre-loaded by the caller.
    """
    imports = _import_mlx_vlm()
    if imports is None:
        return "", CONFIDENCE_FAILURE
    _load_fn, generate_fn, apply_chat_template_fn = imports

    work_dir = Path(tempfile.mkdtemp(prefix="dd_glm_mlx_"))
    try:
        image_paths = _prepare_images(filepath, work_dir)

        if not image_paths:
            return "", CONFIDENCE_FAILURE

        page_texts = _mlx_ocr_pages(image_paths, model, processor, generate_fn, apply_chat_template_fn)
        if not page_texts or not any(t.strip() for t in page_texts):
            return "", CONFIDENCE_FAILURE

        assembled = _assemble_pages(page_texts)
        return assembled, _CONFIDENCE_GLM_OCR
    except Exception:
        logger.exception("MLX GLM-OCR extraction failed for %s", filepath)
        return "", CONFIDENCE_FAILURE
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
        return "", CONFIDENCE_FAILURE

    work_dir = Path(tempfile.mkdtemp(prefix="dd_glm_ollama_"))
    try:
        image_paths = _prepare_images(filepath, work_dir)

        if not image_paths:
            return "", CONFIDENCE_FAILURE

        page_texts = _ollama_ocr_pages(image_paths)
        if not page_texts or not any(t.strip() for t in page_texts):
            return "", CONFIDENCE_FAILURE

        assembled = _assemble_pages(page_texts)
        return assembled, _CONFIDENCE_GLM_OCR
    except Exception:
        logger.exception("Ollama GLM-OCR extraction failed for %s", filepath)
        return "", CONFIDENCE_FAILURE
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Public extractor class ───────────────────────────────────────────


_GLM_OCR_EXTENSIONS: frozenset[str] = frozenset({".pdf"} | IMAGE_EXTENSIONS)


class GlmOcrExtractor:
    """Extracts text from scanned PDFs and images using GLM-OCR.

    Tries mlx-vlm first (Apple Silicon, fastest), then Ollama
    (cross-platform).  Returns ``("", 0.0)`` if neither is available.

    The MLX model is loaded lazily on first use and cached for the
    lifetime of the extractor instance — subsequent files reuse the
    same model without re-downloading or re-loading.

    Thread-safety: all MLX/Metal operations are serialized through
    ``_lock`` because Apple Metal command buffers are not thread-safe.
    Concurrent Metal submissions cause a hard process abort:
    ``[IOGPUMetalCommandBuffer validate]: failed assertion``.

    Usage::

        extractor = GlmOcrExtractor()
        text, confidence = extractor.extract(Path("scanned_doc.pdf"))
    """

    @property
    def name(self) -> str:
        return "glm_ocr"

    @property
    def supported_extensions(self) -> frozenset[str]:
        return _GLM_OCR_EXTENSIONS

    def __init__(self) -> None:
        self._mlx_model: Any = None
        self._mlx_processor: Any = None
        self._mlx_checked = False
        # Serializes MLX model loading and inference — Metal GPU is
        # not thread-safe and concurrent command buffer submissions
        # crash the process.
        self._lock = threading.Lock()

    def _ensure_mlx_model(self) -> bool:
        """Load the MLX model/processor on first call.  Returns *True* if available.

        Must be called while holding ``self._lock``.
        """
        if self._mlx_checked:
            return self._mlx_model is not None

        imports = _import_mlx_vlm()
        if imports is None:
            self._mlx_checked = True
            logger.debug("mlx-vlm not available -- skipping MLX backend")
            return False

        load_fn = imports[0]
        try:
            self._mlx_model, self._mlx_processor = load_fn(MODEL_ID_MLX)
            logger.info("GLM-OCR MLX model loaded: %s", MODEL_ID_MLX)
            return True
        except Exception:
            logger.warning("Failed to load MLX model %s", MODEL_ID_MLX, exc_info=True)
            return False
        finally:
            # Set _mlx_checked AFTER model load completes (or fails) to
            # prevent other threads from seeing checked=True + model=None
            # during the download/load window.
            self._mlx_checked = True

    def extract(self, filepath: Path) -> tuple[str, float]:
        """Extract text from *filepath* using GLM-OCR.

        Returns
        -------
        tuple[str, float]
            ``(extracted_text, confidence)``.  Returns ``("", 0.0)`` on
            any failure (missing dependencies, unsupported format, etc.).
        """
        if not filepath.exists():
            return "", CONFIDENCE_FAILURE

        suffix = filepath.suffix.lower()
        if suffix != ".pdf" and suffix not in IMAGE_EXTENSIONS:
            logger.debug("GLM-OCR does not support extension %s", suffix)
            return "", CONFIDENCE_FAILURE

        # Backend 1: mlx-vlm (Apple Silicon).
        # Lock serializes model loading AND inference — Metal command
        # buffers crash the process if submitted from multiple threads.
        with self._lock:
            if self._ensure_mlx_model():
                text, conf = _try_mlx_extract(filepath, self._mlx_model, self._mlx_processor)
                if text.strip():
                    return text, conf

        # Backend 2: Ollama (HTTP-based, thread-safe without lock).
        text, conf = _try_ollama_extract(filepath)
        if text.strip():
            return text, conf

        return "", CONFIDENCE_FAILURE
