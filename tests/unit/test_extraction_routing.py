"""Tests for extraction pipeline routing — suffix correction and media handling.

Tests that magic-byte-corrected suffixes are threaded through to the
extraction methods, and that media files are routed to the media
extractor instead of markitdown.
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING
from unittest.mock import patch

from dd_agents.extraction._constants import MEDIA_EXTENSIONS
from dd_agents.extraction.pipeline import ExtractionPipeline

if TYPE_CHECKING:
    from pathlib import Path


# ===================================================================
# Helpers
# ===================================================================


def _make_pipeline(tmp_path: Path) -> ExtractionPipeline:
    """Create a minimal ExtractionPipeline and ensure test directories exist."""
    (tmp_path / "data_room").mkdir(exist_ok=True)
    (tmp_path / "output").mkdir(exist_ok=True)
    return ExtractionPipeline()


# OLE2 magic bytes — Binary compound document (xls, doc, ppt).
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# ZIP magic bytes — Used by xlsx, docx, pptx.
_ZIP_MAGIC = b"PK\x03\x04"


# ===================================================================
# Suffix passthrough to _extract_spreadsheet
# ===================================================================


class TestSpreadsheetSuffixPassthrough:
    """Verify that magic-byte-corrected suffixes reach _extract_spreadsheet."""

    def test_xls_content_with_xlsx_extension_routes_to_xlrd(self, tmp_path: Path) -> None:
        """A file named .xlsx but with OLE2 content should use xlrd, not openpyxl."""
        pipeline = _make_pipeline(tmp_path)

        # Create a fake .xlsx file with OLE2 magic bytes (it's really .xls).
        data_room = tmp_path / "data_room"
        fake_xlsx = data_room / "file.xlsx"
        # Write OLE2 header + padding so xlrd won't crash during the test.
        fake_xlsx.write_bytes(_OLE2_MAGIC + b"\x00" * 504)

        out_dir = tmp_path / "output"

        # Patch _read_xls to verify it gets called (not _read_xlsx).
        with (
            patch.object(pipeline, "_read_xls", return_value=("sheet data", 0.85)) as mock_xls,
            patch.object(pipeline, "_read_xlsx") as mock_xlsx,
        ):
            pipeline.extract_single(fake_xlsx, out_dir)

        # xlrd path should be called, NOT openpyxl.
        mock_xls.assert_called_once_with(fake_xlsx)
        mock_xlsx.assert_not_called()

    def test_real_xlsx_still_uses_openpyxl(self, tmp_path: Path) -> None:
        """A real .xlsx file (ZIP content) should still use openpyxl."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        real_xlsx = data_room / "file.xlsx"
        # Write ZIP magic + padding.
        real_xlsx.write_bytes(_ZIP_MAGIC + b"\x00" * 508)

        out_dir = tmp_path / "output"

        with (
            patch.object(pipeline, "_read_xlsx", return_value=("sheet data", 0.9)) as mock_xlsx,
            patch.object(pipeline, "_read_xls") as mock_xls,
        ):
            pipeline.extract_single(real_xlsx, out_dir)

        mock_xlsx.assert_called_once_with(real_xlsx)
        mock_xls.assert_not_called()

    def test_xls_extension_uses_xlrd_directly(self, tmp_path: Path) -> None:
        """A file with .xls extension and OLE2 content goes straight to xlrd."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        xls_file = data_room / "file.xls"
        xls_file.write_bytes(_OLE2_MAGIC + b"\x00" * 504)

        out_dir = tmp_path / "output"

        with patch.object(pipeline, "_read_xls", return_value=("data", 0.85)) as mock_xls:
            pipeline.extract_single(xls_file, out_dir)

        mock_xls.assert_called_once_with(xls_file)


# ===================================================================
# Password-protected spreadsheet detection
# ===================================================================


class TestPasswordProtectedSpreadsheet:
    """Verify that password-protected OLE2 spreadsheets are detected early."""

    def test_encrypted_ole2_detected(self, tmp_path: Path) -> None:
        """An OLE2 file with EncryptionInfo marker should be flagged as encrypted."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        xls_file = data_room / "protected.xls"
        # Write OLE2 header + EncryptionInfo marker (UTF-16LE encoded).
        content = _OLE2_MAGIC + b"\x00" * 200
        # Insert the UTF-16LE encoded "Encrypt" marker.
        marker = b"E\x00n\x00c\x00r\x00y\x00p\x00t"
        content += marker + b"\x00" * (512 - len(content) - len(marker))
        xls_file.write_bytes(content)

        out_dir = tmp_path / "output"
        result = pipeline.extract_single(xls_file, out_dir)

        assert result.method == "encrypted"
        assert result.confidence == 0.0
        assert "Password-protected" in result.failure_reasons[0]

    def test_encrypted_placeholder_content(self, tmp_path: Path) -> None:
        """Placeholder should mention password protection."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        xls_file = data_room / "protected.xls"
        content = _OLE2_MAGIC + b"\x00" * 200
        marker = b"E\x00n\x00c\x00r\x00y\x00p\x00t"
        content += marker + b"\x00" * (512 - len(content) - len(marker))
        xls_file.write_bytes(content)

        out_dir = tmp_path / "output"
        pipeline.extract_single(xls_file, out_dir)

        out_files = list(out_dir.glob("*.md"))
        assert len(out_files) == 1
        text = out_files[0].read_text()
        assert "PASSWORD-PROTECTED" in text
        assert "password" in text.lower()

    def test_encrypted_skips_xlrd_and_markitdown(self, tmp_path: Path) -> None:
        """Password-protected files should NOT attempt xlrd or markitdown."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        xls_file = data_room / "protected.xls"
        content = _OLE2_MAGIC + b"\x00" * 200
        marker = b"E\x00n\x00c\x00r\x00y\x00p\x00t"
        content += marker + b"\x00" * (512 - len(content) - len(marker))
        xls_file.write_bytes(content)

        out_dir = tmp_path / "output"

        with (
            patch.object(pipeline, "_read_xls") as mock_xls,
            patch.object(pipeline._markitdown, "extract") as mock_md,
        ):
            pipeline.extract_single(xls_file, out_dir)

        mock_xls.assert_not_called()
        mock_md.assert_not_called()

    def test_unencrypted_ole2_still_uses_xlrd(self, tmp_path: Path) -> None:
        """A normal (non-encrypted) OLE2 .xls should still go through xlrd."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        xls_file = data_room / "normal.xls"
        # OLE2 header without any encryption markers.
        xls_file.write_bytes(_OLE2_MAGIC + b"\x00" * 504)

        out_dir = tmp_path / "output"

        with patch.object(pipeline, "_read_xls", return_value=("data", 0.85)) as mock_xls:
            pipeline.extract_single(xls_file, out_dir)

        mock_xls.assert_called_once()

    def test_xlsx_named_as_xls_encrypted(self, tmp_path: Path) -> None:
        """A .xlsx file with OLE2+encryption content should be flagged."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        # Named .xlsx but has OLE2 bytes (password-protected old format).
        xlsx_file = data_room / "protected.xlsx"
        content = _OLE2_MAGIC + b"\x00" * 200
        marker = b"EncryptedPackage"
        content += marker + b"\x00" * (512 - len(content) - len(marker))
        xlsx_file.write_bytes(content)

        out_dir = tmp_path / "output"
        result = pipeline.extract_single(xlsx_file, out_dir)

        # Magic byte correction: .xlsx → .xls (OLE2), then encryption detected.
        assert result.method == "encrypted"


# ===================================================================
# Media file routing
# ===================================================================


class TestMediaFileRouting:
    """Verify that media files are routed to _extract_media, not _extract_generic."""

    def test_mp4_routes_to_extract_media(self, tmp_path: Path) -> None:
        """An .mp4 file should call _extract_media, not _extract_generic."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        mp4_file = data_room / "meeting.mp4"
        mp4_file.write_bytes(b"\x00" * 100)

        out_dir = tmp_path / "output"

        with (
            patch.object(pipeline, "_extract_media", wraps=pipeline._extract_media) as mock_media,
            patch.object(pipeline, "_extract_generic") as mock_generic,
        ):
            pipeline.extract_single(mp4_file, out_dir)

        mock_media.assert_called_once()
        mock_generic.assert_not_called()

    def test_mp3_routes_to_extract_media(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        mp3_file = data_room / "recording.mp3"
        mp3_file.write_bytes(b"\xff\xfb" + b"\x00" * 98)

        out_dir = tmp_path / "output"

        with (
            patch.object(pipeline, "_extract_media", wraps=pipeline._extract_media) as mock_media,
            patch.object(pipeline, "_extract_generic") as mock_generic,
        ):
            pipeline.extract_single(mp3_file, out_dir)

        mock_media.assert_called_once()
        mock_generic.assert_not_called()

    def test_media_without_whisper_writes_placeholder(self, tmp_path: Path) -> None:
        """Without whisper installed, media extraction writes a placeholder."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        mp4_file = data_room / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)

        out_dir = tmp_path / "output"
        result = pipeline.extract_single(mp4_file, out_dir)

        assert result.method == "media_placeholder"
        assert result.confidence < 0.5
        assert "media_placeholder" in result.fallback_chain

    def test_media_placeholder_content(self, tmp_path: Path) -> None:
        """The placeholder file should identify the media type."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        mp4_file = data_room / "call.mp4"
        mp4_file.write_bytes(b"\x00" * 100)

        out_dir = tmp_path / "output"
        pipeline.extract_single(mp4_file, out_dir)

        # Find the output file.
        out_files = list(out_dir.glob("*.md"))
        assert len(out_files) == 1
        content = out_files[0].read_text()
        assert "MEDIA FILE" in content
        assert ".mp4" in content

    def test_media_never_tries_markitdown(self, tmp_path: Path) -> None:
        """Media files must never be passed to markitdown."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        wav_file = data_room / "audio.wav"
        wav_file.write_bytes(b"RIFF" + b"\x00" * 96)

        out_dir = tmp_path / "output"

        with patch.object(pipeline._markitdown, "extract") as mock_md:
            pipeline.extract_single(wav_file, out_dir)

        mock_md.assert_not_called()

    def test_docx_still_routes_to_generic(self, tmp_path: Path) -> None:
        """Non-media binary files (.docx) should still use _extract_generic."""
        pipeline = _make_pipeline(tmp_path)

        data_room = tmp_path / "data_room"
        docx_file = data_room / "contract.docx"
        docx_file.write_bytes(_ZIP_MAGIC + b"\x00" * 508)

        out_dir = tmp_path / "output"

        with (
            patch.object(pipeline, "_extract_generic", wraps=pipeline._extract_generic) as mock_gen,
            patch.object(pipeline, "_extract_media") as mock_media,
        ):
            pipeline.extract_single(docx_file, out_dir)

        mock_gen.assert_called_once()
        mock_media.assert_not_called()


# ===================================================================
# Quality gates on the generic (Office/other) chain
# ===================================================================


def _minimal_docx_bytes(text: str) -> bytes:
    """Build a small but valid .docx from raw parts (no python-docx dependency)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buf.getvalue()


class TestGenericChainQualityGates:
    """Binary garbage must fail closed on the generic chain, like the PDF chain."""

    def test_truncated_docx_fails_closed(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        full = _minimal_docx_bytes("Synthetic clause text. " * 40)
        docx_file = tmp_path / "data_room" / "truncated.docx"
        docx_file.write_bytes(full[: len(full) // 2])
        out_dir = tmp_path / "output"

        entry = pipeline.extract_single(docx_file, out_dir)

        assert entry.method == "failed"
        assert entry.bytes_extracted == 0
        assert not any(out_dir.glob("*.md")) and not any(out_dir.glob("*.txt"))

    def test_binary_garbage_with_office_extension_fails_closed(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        out_dir = tmp_path / "output"
        for name in ("garbage.docx", "garbage.rtf"):
            f = tmp_path / "data_room" / name
            f.write_bytes(_ZIP_MAGIC + bytes(range(256)) * 20)

            entry = pipeline.extract_single(f, out_dir)

            assert entry.method == "failed", name
            assert entry.bytes_extracted == 0, name

    def test_failure_reasons_are_recorded(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        f = tmp_path / "data_room" / "garbage.docx"
        f.write_bytes(_ZIP_MAGIC + bytes(range(256)) * 20)

        entry = pipeline.extract_single(f, tmp_path / "output")

        assert entry.fallback_chain[:2] == ["markitdown", "direct_read"]
        assert entry.failure_reasons

    def test_control_char_corruption_fails_closed(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        f = tmp_path / "data_room" / "corrupt.docx"
        # Printable text with ~5% ESC bytes: passes readability, fails the control-char gate.
        f.write_text(("Synthetic agreement text for Subject A. " * 2 + "\x1b" * 4) * 30)

        entry = pipeline.extract_single(f, tmp_path / "output")

        assert entry.method == "failed"

    def test_valid_docx_still_extracts(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        docx_file = tmp_path / "data_room" / "valid.docx"
        docx_file.write_bytes(_minimal_docx_bytes("Synthetic termination clause for Subject A."))

        entry = pipeline.extract_single(docx_file, tmp_path / "output")

        assert entry.method != "failed"
        assert entry.bytes_extracted > 0

    def test_readable_text_with_unknown_extension_still_extracts(self, tmp_path: Path) -> None:
        pipeline = _make_pipeline(tmp_path)
        f = tmp_path / "data_room" / "notes.unknownext"
        f.write_text("This is a plain text note about a synthetic agreement between parties. " * 5)

        entry = pipeline.extract_single(f, tmp_path / "output")

        assert entry.method != "failed"
        assert entry.bytes_extracted > 0


# ===================================================================
# Media extensions constant
# ===================================================================


class TestMediaExtensions:
    """Verify the MEDIA_EXTENSIONS constant."""

    def test_common_video_formats(self) -> None:
        for ext in (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm"):
            assert ext in MEDIA_EXTENSIONS, f"{ext} missing from MEDIA_EXTENSIONS"

    def test_common_audio_formats(self) -> None:
        for ext in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"):
            assert ext in MEDIA_EXTENSIONS, f"{ext} missing from MEDIA_EXTENSIONS"

    def test_no_overlap_with_image_extensions(self) -> None:
        from dd_agents.extraction._constants import IMAGE_EXTENSIONS

        overlap = MEDIA_EXTENSIONS & IMAGE_EXTENSIONS
        assert not overlap, f"Media/image overlap: {overlap}"

    def test_supported_extensions_includes_media(self) -> None:
        from dd_agents.utils.constants import SUPPORTED_EXTENSIONS

        assert ".mp4" in SUPPORTED_EXTENSIONS
        assert ".mp3" in SUPPORTED_EXTENSIONS
