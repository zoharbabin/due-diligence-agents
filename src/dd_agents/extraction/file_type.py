"""Content-based file type correction for data-room files.

Data rooms contain files with the wrong extension (a JPEG saved as ``.pdf``,
an ``.xlsx`` named ``.docx``). :func:`detect_actual_type` reads the first
bytes (and the member names of ZIP files) and returns the extension the
content really has. It replaces the content sniffing ``markitdown`` would
otherwise get from ``magika``, so it works the same on every Python version.
"""

from __future__ import annotations

import logging
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# (signature, offset, canonical extension).
_MAGIC_MAP: tuple[tuple[bytes, int, str], ...] = (
    (b"%PDF-", 0, ".pdf"),
    (b"\x89PNG\r\n\x1a\n", 0, ".png"),
    (b"\xff\xd8\xff", 0, ".jpg"),  # JPEG (covers JFIF and Exif)
    (b"GIF87a", 0, ".gif"),
    (b"GIF89a", 0, ".gif"),
    (b"BM", 0, ".bmp"),
    (b"II\x2a\x00", 0, ".tiff"),  # TIFF little-endian
    (b"MM\x00\x2a", 0, ".tiff"),  # TIFF big-endian
    (b"RIFF", 0, ".webp"),  # RIFF container, refined below
    (b"PK\x03\x04", 0, ".docx"),  # ZIP, refined below
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, ".xls"),  # OLE2 (xls/doc/ppt)
)

# Top-level folder inside an OOXML package -> extension.
_OOXML_FOLDERS: tuple[tuple[str, str], ...] = (("word/", ".docx"), ("xl/", ".xlsx"), ("ppt/", ".pptx"))


def _ooxml_type(filepath: Path) -> str | None:
    """Return ``.docx``/``.xlsx``/``.pptx`` from ZIP member names, or ``None``."""
    try:
        with zipfile.ZipFile(filepath) as z:
            names = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    for folder, ext in _OOXML_FOLDERS:
        if any(n.startswith(folder) for n in names):
            return ext
    return None


def detect_actual_type(filepath: Path, extension: str) -> str:
    """Return the extension the content of *filepath* really has.

    Returns *extension* unchanged when the content matches it, when the type
    cannot be told apart from it, or when the file cannot be read. Only
    formats where mismatches are common in data rooms are checked.
    """
    try:
        with filepath.open("rb") as fh:
            header = fh.read(16)
    except OSError:
        return extension

    if len(header) < 4:
        return extension

    matched = False
    for magic, offset, detected in _MAGIC_MAP:
        if header[offset : offset + len(magic)] != magic:
            continue
        matched = True
        if detected == ".docx":
            # ZIP: tell docx/xlsx/pptx apart by their contents. A plain
            # .zip, or a ZIP we cannot classify, keeps its extension.
            if extension == ".zip":
                return extension
            return _ooxml_type(filepath) or extension

        if detected == extension:
            return extension

        # OLE2: .doc/.xls/.ppt/.msg share one signature.
        if detected == ".xls" and extension in (".doc", ".ppt", ".xls", ".msg"):
            return extension

        # RIFF is a container. Only WebP counts (not AVI, WAV).
        if detected == ".webp":
            if len(header) >= 12 and header[8:12] == b"WEBP":
                return detected
            return extension

        return detected

    # A ".pdf" without the PDF signature is almost always a scanned image
    # saved with the wrong extension. Route it to image extraction.
    if extension == ".pdf" and not matched:
        logger.info("File %s has .pdf extension but no PDF magic bytes, routing as image", filepath.name)
        return ".jpg"

    return extension
