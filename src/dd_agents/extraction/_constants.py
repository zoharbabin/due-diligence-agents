"""Shared constants for the extraction package."""

from __future__ import annotations

# Confidence score for extraction failure (all extractors).
CONFIDENCE_FAILURE: float = 0.0

# Confidence score for a plain-text fallback read.
CONFIDENCE_FALLBACK_READ: float = 0.5

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
