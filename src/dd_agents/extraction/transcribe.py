"""Multi-backend audio/video transcription.

Detects installed transcription libraries and selects the best available
backend based on the current OS and user preference.

Backend priority (highest → lowest):

1. **mlx_whisper** — CLI-based, optimized for Apple Silicon (macOS only).
   ``mlx_whisper <file> --model <model> --language English -f json``
2. **whisperx** — Python API, GPU-accelerated, good alignment.
3. **openai-whisper** — Original OpenAI whisper, broadest compatibility.

Override with ``DD_TRANSCRIPTION_BACKEND`` env var (values: ``mlx``,
``whisperx``, ``openai``).  Override with ``DD_TRANSCRIPTION_MODEL``
to set a custom model name for the selected backend.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend enum
# ---------------------------------------------------------------------------


class TranscriptionBackend(Enum):
    """Supported transcription backends."""

    MLX_WHISPER = "mlx"
    WHISPERX = "whisperx"
    OPENAI_WHISPER = "openai"


# Default models per backend.
_DEFAULT_MODELS: dict[TranscriptionBackend, str] = {
    TranscriptionBackend.MLX_WHISPER: "mlx-community/whisper-large-v3-turbo",
    TranscriptionBackend.WHISPERX: "large-v3",
    TranscriptionBackend.OPENAI_WHISPER: "base",
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of a transcription attempt."""

    text: str
    backend: TranscriptionBackend
    model: str
    language: str | None = None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _mlx_whisper_available() -> bool:
    """Check if mlx_whisper CLI is installed and on PATH."""
    return shutil.which("mlx_whisper") is not None


def _whisperx_available() -> bool:
    """Check if whisperx Python package is importable."""
    try:
        import whisperx  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        return False


def _openai_whisper_available() -> bool:
    """Check if openai-whisper Python package is importable."""
    try:
        import whisper  # type: ignore[import-untyped]  # noqa: F401

        return True
    except ImportError:
        return False


def detect_backend() -> TranscriptionBackend | None:
    """Return the best available transcription backend, or None.

    Respects ``DD_TRANSCRIPTION_BACKEND`` env var override.
    """
    override = os.getenv("DD_TRANSCRIPTION_BACKEND", "").strip().lower()
    if override:
        mapping = {
            "mlx": TranscriptionBackend.MLX_WHISPER,
            "mlx_whisper": TranscriptionBackend.MLX_WHISPER,
            "whisperx": TranscriptionBackend.WHISPERX,
            "openai": TranscriptionBackend.OPENAI_WHISPER,
            "openai-whisper": TranscriptionBackend.OPENAI_WHISPER,
        }
        backend = mapping.get(override)
        if backend is None:
            logger.warning("Unknown DD_TRANSCRIPTION_BACKEND=%r, falling back to auto-detect", override)
        else:
            return backend

    # Auto-detect: mlx_whisper preferred on macOS.
    if _is_macos() and _mlx_whisper_available():
        return TranscriptionBackend.MLX_WHISPER

    if _whisperx_available():
        return TranscriptionBackend.WHISPERX

    if _openai_whisper_available():
        return TranscriptionBackend.OPENAI_WHISPER

    return None


def _get_model(backend: TranscriptionBackend) -> str:
    """Return the model to use — env override or default for *backend*."""
    override = os.getenv("DD_TRANSCRIPTION_MODEL", "").strip()
    if override:
        return override
    return _DEFAULT_MODELS[backend]


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _transcribe_mlx(filepath: Path, model: str) -> TranscriptionResult:
    """Transcribe using mlx_whisper CLI.

    Runs:
        mlx_whisper <file> --model <model> --language English -f json

    Output is a JSON file written to a temp directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "mlx_whisper",
            str(filepath),
            "--model",
            model,
            "--language",
            "English",
            "-f",
            "json",
            "--output-dir",
            tmpdir,
        ]
        logger.debug("Running mlx_whisper: %s", " ".join(cmd))
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            msg = f"mlx_whisper exited with code {result.returncode}: {result.stderr.strip()}"
            raise RuntimeError(msg)

        # mlx_whisper writes <stem>.json in the output dir.
        json_files = list(p for p in __import__("pathlib").Path(tmpdir).iterdir() if p.suffix == ".json")
        if not json_files:
            msg = "mlx_whisper produced no JSON output"
            raise RuntimeError(msg)

        transcript_data = json.loads(json_files[0].read_text(encoding="utf-8"))
        text = transcript_data.get("text", "").strip()
        language = transcript_data.get("language")

    return TranscriptionResult(text=text, backend=TranscriptionBackend.MLX_WHISPER, model=model, language=language)


def _transcribe_whisperx(filepath: Path, model: str) -> TranscriptionResult:
    """Transcribe using whisperx Python API."""
    import whisperx  # type: ignore[import-untyped]

    device = "cpu"
    try:
        import torch  # type: ignore[import-untyped]

        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "cpu"  # whisperx MPS support is limited, stay on CPU.
    except ImportError:
        pass

    wx_model = whisperx.load_model(model, device=device)
    audio = whisperx.load_audio(str(filepath))
    result = wx_model.transcribe(audio)

    # whisperx returns segments list.
    segments = result.get("segments", [])
    text = " ".join(seg.get("text", "") for seg in segments).strip()
    language = result.get("language")

    return TranscriptionResult(text=text, backend=TranscriptionBackend.WHISPERX, model=model, language=language)


def _transcribe_openai(filepath: Path, model: str) -> TranscriptionResult:
    """Transcribe using openai-whisper Python API."""
    import whisper  # type: ignore[import-untyped]

    wh_model = whisper.load_model(model)
    result = wh_model.transcribe(str(filepath))
    text = result.get("text", "").strip()
    language = result.get("language")

    return TranscriptionResult(text=text, backend=TranscriptionBackend.OPENAI_WHISPER, model=model, language=language)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_BACKEND_DISPATCH = {
    TranscriptionBackend.MLX_WHISPER: _transcribe_mlx,
    TranscriptionBackend.WHISPERX: _transcribe_whisperx,
    TranscriptionBackend.OPENAI_WHISPER: _transcribe_openai,
}


def transcribe(filepath: Path) -> TranscriptionResult | None:
    """Transcribe *filepath* using the best available backend.

    Returns ``None`` if no transcription backend is installed.
    Raises on transcription failure (caller handles).
    """
    backend = detect_backend()
    if backend is None:
        return None

    model = _get_model(backend)
    logger.info("Transcribing %s with %s (model=%s)", filepath.name, backend.value, model)
    return _BACKEND_DISPATCH[backend](filepath, model)
