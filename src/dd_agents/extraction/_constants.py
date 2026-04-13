"""Shared constants for the extraction package.

All extraction quality thresholds, confidence scores, and format-specific
settings live here so tuning is centralized and discoverable.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Confidence scores by extraction method (0.0 = failure, 1.0 = perfect)
# ---------------------------------------------------------------------------

CONFIDENCE_FAILURE: float = 0.0
CONFIDENCE_FALLBACK_READ: float = 0.5
CONFIDENCE_OCR: float = 0.6
CONFIDENCE_CLAUDE_VISION: float = 0.65
CONFIDENCE_GLM_OCR: float = 0.8
CONFIDENCE_LAYOUT_PDF: float = 0.85
CONFIDENCE_MARKITDOWN: float = 0.9

IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"})

SPREADSHEET_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls", ".csv", ".tsv"})

PLAINTEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".log",
        ".ini",
        ".cfg",
        ".conf",
    }
)

# Audio and video formats — require transcription (e.g. whisper), not text extraction.
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Audio
        ".mp3",
        ".wav",
        ".flac",
        ".aac",
        ".ogg",
        ".wma",
        ".m4a",
        ".opus",
        # Video
        ".mp4",
        ".avi",
        ".mov",
        ".mkv",
        ".wmv",
        ".webm",
        ".m4v",
        ".flv",
    }
)
