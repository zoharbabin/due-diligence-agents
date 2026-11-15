"""Tests for content-based file type correction."""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING

import pytest

from dd_agents.extraction.file_type import detect_actual_type

if TYPE_CHECKING:
    from pathlib import Path


def _zip(path: Path, *names: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(name, "x")
    return path


class TestZipOffice:
    @pytest.mark.parametrize(
        ("member", "expected"),
        [("word/document.xml", ".docx"), ("xl/workbook.xml", ".xlsx"), ("ppt/presentation.xml", ".pptx")],
    )
    @pytest.mark.parametrize("claimed", [".docx", ".xlsx", ".pptx", ".pdf", ".txt"])
    def test_ooxml_type_comes_from_contents(self, tmp_path: Path, member: str, expected: str, claimed: str) -> None:
        p = _zip(tmp_path / f"f{claimed}", "[Content_Types].xml", member)
        assert detect_actual_type(p, claimed) == expected

    def test_plain_zip_keeps_extension(self, tmp_path: Path) -> None:
        p = _zip(tmp_path / "a.zip", "readme.txt")
        assert detect_actual_type(p, ".zip") == ".zip"

    @pytest.mark.parametrize("claimed", [".docx", ".xlsx", ".pptx"])
    def test_unrecognised_zip_keeps_ooxml_extension(self, tmp_path: Path, claimed: str) -> None:
        p = _zip(tmp_path / f"a{claimed}", "something/else.xml")
        assert detect_actual_type(p, claimed) == claimed

    def test_truncated_zip_keeps_extension(self, tmp_path: Path) -> None:
        p = tmp_path / "a.xlsx"
        p.write_bytes(b"PK\x03\x04" + b"\x00" * 20)
        assert detect_actual_type(p, ".xlsx") == ".xlsx"


class TestOtherSignatures:
    def test_jpeg_named_pdf(self, tmp_path: Path) -> None:
        p = tmp_path / "scan.pdf"
        p.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert detect_actual_type(p, ".pdf") == ".jpg"

    def test_pdf_without_signature_is_routed_as_image(self, tmp_path: Path) -> None:
        p = tmp_path / "scan.pdf"
        p.write_bytes(b"not a pdf at all, sorry")
        assert detect_actual_type(p, ".pdf") == ".jpg"

    def test_matching_extension_is_unchanged(self, tmp_path: Path) -> None:
        p = tmp_path / "a.pdf"
        p.write_bytes(b"%PDF-1.7\n" + b"x" * 20)
        assert detect_actual_type(p, ".pdf") == ".pdf"

    def test_ole2_keeps_doc_ppt_msg(self, tmp_path: Path) -> None:
        p = tmp_path / "a.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 20)
        assert detect_actual_type(p, ".doc") == ".doc"

    def test_missing_file_keeps_extension(self, tmp_path: Path) -> None:
        assert detect_actual_type(tmp_path / "gone.pdf", ".pdf") == ".pdf"
