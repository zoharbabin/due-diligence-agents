"""Tests for the built-in document conversion fallback."""

from __future__ import annotations

import sys
import zipfile
from typing import TYPE_CHECKING

import pytest

from dd_agents.extraction.office_convert import convert_to_markdown

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def no_markitdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import markitdown`` fail, as it does where onnxruntime is missing."""
    monkeypatch.setitem(sys.modules, "markitdown", None)


def _make_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'  # noqa: E501
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'  # noqa: E501
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Alpha clause</w:t></w:r></w:p><w:p><w:r><w:t>Beta clause</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )


@pytest.mark.usefixtures("no_markitdown")
class TestFallback:
    def test_docx(self, tmp_path: Path) -> None:
        f = tmp_path / "a.docx"
        _make_docx(f)
        text = convert_to_markdown(f)
        assert "Alpha clause" in text
        assert "Beta clause" in text

    def test_pptx(self, tmp_path: Path) -> None:
        from pptx import Presentation

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "Quarterly Plan"  # type: ignore[union-attr]
        f = tmp_path / "a.pptx"
        prs.save(str(f))
        text = convert_to_markdown(f)
        assert "Slide number: 1" in text
        assert "Quarterly Plan" in text

    def test_xlsx(self, tmp_path: Path) -> None:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Terms"
        ws.append(["Name", "Value"])
        ws.append(["Cap", 100])
        f = tmp_path / "a.xlsx"
        wb.save(str(f))
        text = convert_to_markdown(f)
        assert "## Terms" in text
        assert "| Name | Value |" in text
        assert "| Cap | 100 |" in text

    def test_html_drops_scripts(self, tmp_path: Path) -> None:
        f = tmp_path / "a.html"
        f.write_text("<html><script>evil()</script><h1>Title</h1><p>Body text</p></html>")
        text = convert_to_markdown(f)
        assert "# Title" in text
        assert "Body text" in text
        assert "evil" not in text

    def test_unsupported_type_raises_import_error(self, tmp_path: Path) -> None:
        f = tmp_path / "a.doc"
        f.write_bytes(b"x")
        with pytest.raises(ImportError, match="no built-in converter"):
            convert_to_markdown(f)

    def test_pipe_in_cell_is_escaped(self, tmp_path: Path) -> None:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["a|b", "c"])
        f = tmp_path / "p.xlsx"
        wb.save(str(f))
        assert "a\\|b" in convert_to_markdown(f)


def test_prefers_markitdown_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        text_content = "from markitdown"

    class _MarkItDown:
        def convert(self, _path: str) -> _Result:
            return _Result()

    fake = type(sys)("markitdown")
    fake.MarkItDown = _MarkItDown  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    assert convert_to_markdown(f) == "from markitdown"


class TestMagikaStandIn:
    """Without ``magika`` (no onnxruntime wheel), real markitdown still loads."""

    @pytest.fixture()
    def markitdown_without_magika(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib.util

        if importlib.util.find_spec("markitdown") is None:
            pytest.skip("markitdown is not installed")
        for name in [m for m in sys.modules if m == "markitdown" or m.startswith("markitdown.")]:
            monkeypatch.delitem(sys.modules, name)
        monkeypatch.setitem(sys.modules, "magika", None)

    def test_converts_by_extension(self, markitdown_without_magika: None, tmp_path: Path) -> None:
        f = tmp_path / "a.html"
        f.write_text("<h1>Title</h1><p>Body</p>", encoding="utf-8")
        text = convert_to_markdown(f)
        assert "Title" in text
        assert "Body" in text

    def test_stand_in_does_not_leak(self, markitdown_without_magika: None, tmp_path: Path) -> None:
        f = tmp_path / "a.html"
        f.write_text("<p>x</p>", encoding="utf-8")
        convert_to_markdown(f)
        assert sys.modules.get("magika") is None

    def test_repeated_calls_work(self, markitdown_without_magika: None, tmp_path: Path) -> None:
        f = tmp_path / "a.html"
        f.write_text("<p>x</p>", encoding="utf-8")
        assert convert_to_markdown(f) == convert_to_markdown(f)

    def test_unrelated_import_error_still_falls_back(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setitem(sys.modules, "markitdown", None)
        f = tmp_path / "a.html"
        f.write_text("<h1>Fallback</h1>", encoding="utf-8")
        assert "Fallback" in convert_to_markdown(f)


class TestExtensionHint:
    def test_hint_overrides_wrong_filename_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "wrong.docx"
        f.write_text("<h1>Real HTML</h1>", encoding="utf-8")
        assert "Real HTML" in convert_to_markdown(f, extension=".html")

    def test_hint_works_in_fallback(self, no_markitdown: None, tmp_path: Path) -> None:
        f = tmp_path / "wrong.docx"
        f.write_text("<h1>Real HTML</h1>", encoding="utf-8")
        assert "Real HTML" in convert_to_markdown(f, extension=".html")


class TestMisnamedFiles:
    def test_xlsx_named_docx_is_converted_by_content(self, tmp_path: Path) -> None:
        import openpyxl

        from dd_agents.extraction.markitdown import MarkitdownExtractor

        wb = openpyxl.Workbook()
        ws = wb.active
        assert ws is not None
        ws.append(["Item", "Qty"])
        ws.append(["Widget", 7])
        f = tmp_path / "report.docx"
        wb.save(f)

        text, confidence = MarkitdownExtractor().extract(f)
        assert "Widget" in text
        assert confidence > 0
