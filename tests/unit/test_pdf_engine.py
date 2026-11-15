"""Tests for the PDFium-backed PDF engine (the only module that talks to PDFium)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

pikepdf = pytest.importorskip("pikepdf")
pytest.importorskip("pypdfium2")

from dd_agents.extraction import pdf_engine  # noqa: E402
from dd_agents.extraction.pdf_engine import PdfEncryptedError, PdfError  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

Item = tuple[float, float, str]  # x, y (from bottom), text


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages: list[list[Item]], *, user_pw: str | None = None, owner_pw: str = "owner") -> Path:
    """Write a small text PDF. Each page is a list of ``(x, y, text)`` runs."""
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)
    )
    for items in pages:
        page = pikepdf.Page(pdf.add_blank_page(page_size=(612, 792)))
        ops = "".join(f"BT /F1 11 Tf {x} {y} Td ({_esc(t)}) Tj ET\n" for x, y, t in items)
        page.obj.Contents = pdf.make_stream(ops.encode("latin-1"))
        page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    if user_pw is not None:
        pdf.save(path, encryption=pikepdf.Encryption(user=user_pw, owner=owner_pw))
    else:
        pdf.save(path)
    return path


def lines(prefix: str, n: int, x: float = 72, top: float = 740, pitch: float = 14) -> list[Item]:
    return [(x, top - i * pitch, f"{prefix} line {i} of the agreement text") for i in range(n)]


class TestExtractPages:
    def test_text_per_page(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("ALPHA", 3), lines("BETA", 3)])
        pages = pdf_engine.extract_pages(f)
        assert len(pages) == 2
        assert "ALPHA line 0" in pages[0]
        assert "BETA line 2" in pages[1]

    def test_normalises_line_endings(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("ALPHA", 3)])
        assert "\r" not in pdf_engine.extract_pages(f)[0]

    def test_numbers_and_punctuation_survive(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [[(72, 700, "Cap: USD 1,250,000.00 per Section 12.3(b).")]])
        assert "USD 1,250,000.00 per Section 12.3(b)." in pdf_engine.extract_pages(f)[0]

    def test_owner_password_only_is_readable(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("OWNERONLY", 2)], user_pw="")
        assert "OWNERONLY line 0" in pdf_engine.extract_pages(f)[0]

    def test_user_password_raises_encrypted(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("SECRET", 2)], user_pw="u-pass")
        with pytest.raises(PdfEncryptedError):
            pdf_engine.extract_pages(f)

    def test_garbage_raises_pdf_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.pdf"
        f.write_bytes(b"%PDF-1.7\n" + b"\x00\x01garbage" * 100)
        with pytest.raises(PdfError):
            pdf_engine.extract_pages(f)

    def test_empty_file_raises_pdf_error(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        with pytest.raises(PdfError):
            pdf_engine.extract_pages(f)

    def test_missing_file_raises_pdf_error(self, tmp_path: Path) -> None:
        with pytest.raises(PdfError):
            pdf_engine.extract_pages(tmp_path / "nope.pdf")

    def test_truncated_file_is_repaired(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines(f"PAGE{i}", 40) for i in range(6)])
        data = f.read_bytes()
        f.write_bytes(data[: int(len(data) * 0.8)])
        pages = pdf_engine.extract_pages(f)
        assert "PAGE0 line 0" in pages[0]

    def test_unrepairable_file_still_raises_pdf_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.pdf"
        f.write_bytes(b"%PDF-1.4\n")
        with pytest.raises(PdfError):
            pdf_engine.extract_pages(f)


class TestProbe:
    def test_text_pdf(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("ALPHA", 8), lines("BETA", 2)])
        probe = pdf_engine.probe(f)
        assert not probe.encrypted
        assert probe.page_count == 2
        assert "ALPHA line 0" in probe.first_page_text
        assert "BETA" not in probe.first_page_text

    def test_encrypted_pdf_is_reported_not_raised(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("SECRET", 2)], user_pw="u-pass")
        probe = pdf_engine.probe(f)
        assert probe.encrypted
        assert probe.page_count == 0
        assert probe.first_page_text == ""

    def test_pdf_without_pages(self, tmp_path: Path) -> None:
        f = tmp_path / "np.pdf"
        pikepdf.new().save(f)
        probe = pdf_engine.probe(f)
        assert probe.page_count == 0

    def test_garbage_raises_pdf_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.pdf"
        f.write_bytes(b"not a pdf")
        with pytest.raises(PdfError):
            pdf_engine.probe(f)


class TestExtractBlocks:
    def test_wrapped_lines_form_one_block(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("PARA", 3)])
        blocks = pdf_engine.extract_blocks(f)
        assert len(blocks) == 1
        assert blocks[0].page == 1
        assert blocks[0].text.count("\n") == 2
        assert "PARA line 0" in blocks[0].text
        assert "PARA line 2" in blocks[0].text

    def test_paragraphs_separated_by_gap_are_separate_blocks(self, tmp_path: Path) -> None:
        items = lines("FIRST", 2, top=740) + lines("SECOND", 2, top=600)
        blocks = pdf_engine.extract_blocks(make_pdf(tmp_path / "a.pdf", [items]))
        assert [b.text.split()[0] for b in blocks] == ["FIRST", "SECOND"]

    def test_table_cells_are_separate_blocks(self, tmp_path: Path) -> None:
        items: list[Item] = []
        for r in range(4):
            y = 700 - r * 20
            items += [(72, y, f"Name{r}"), (250, y, f"{r + 1}00,000.00"), (430, y, "24")]
        blocks = pdf_engine.extract_blocks(make_pdf(tmp_path / "a.pdf", [items]))
        assert len(blocks) == 12
        first_row = sorted((b for b in blocks if abs(b.y0 - blocks[0].y0) < 5), key=lambda b: b.x0)
        assert [b.text for b in first_row] == ["Name0", "100,000.00", "24"]

    def test_bbox_uses_top_left_origin_in_points(self, tmp_path: Path) -> None:
        # Baseline at y=700 from the bottom of a 792pt page -> glyph top near 92 from the top.
        blocks = pdf_engine.extract_blocks(make_pdf(tmp_path / "a.pdf", [[(100, 700, "MARKER text here")]]))
        b = blocks[0]
        assert 98 <= b.x0 <= 102
        assert 80 <= b.y0 <= 95
        assert b.y0 < b.y1 < 105
        assert b.x1 > b.x0 + 50

    def test_page_numbers_are_one_based(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("ONE", 1), lines("TWO", 1)])
        assert [b.page for b in pdf_engine.extract_blocks(f)] == [1, 2]

    def test_blank_pdf_has_no_blocks(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [[]])
        assert pdf_engine.extract_blocks(f) == []


class TestLock:
    def test_concurrent_extraction_is_safe(self, tmp_path: Path) -> None:
        f = make_pdf(tmp_path / "a.pdf", [lines("ALPHA", 5)])
        errors: list[BaseException] = []

        def work() -> None:
            try:
                for _ in range(10):
                    assert "ALPHA line 0" in pdf_engine.extract_pages(f)[0]
                    pdf_engine.probe(f)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_lock_is_shared_with_glm_ocr(self) -> None:
        from dd_agents.extraction import glm_ocr

        assert glm_ocr._pdfium_lock is pdf_engine.PDF_LOCK
