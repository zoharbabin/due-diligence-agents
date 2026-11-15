"""Per-page OCR routing for mixed PDFs (Issues #272, #263).

A PDF with some text pages and some scanned pages used to come back with the
scanned pages silently missing. These tests pin the fix, using the synthetic
corpus file ``layout_mixed_en.pdf`` (pages 1 and 3 text, pages 2 and 4 scanned).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from dd_agents.extraction import glm_ocr, pdf_pages
from dd_agents.extraction.glm_ocr import GlmOcrExtractor
from dd_agents.extraction.ocr import OCRExtractor
from dd_agents.extraction.pdf_pages import collapse_repeats
from dd_agents.extraction.pipeline import ExtractionPipeline

CORPUS = Path(__file__).resolve().parent.parent / "fixtures" / "extraction_corpus"
MIXED = CORPUS / "layout_mixed_en.pdf"
TEXT_ONLY = CORPUS / "contract_en_text.pdf"
PAGE2 = "PART B COMMERCIAL TERMS fee of USD 1,250,000.00 payable in forty-five (45) days"
PAGE4 = "PART D SIGNATURES Alexandra Testwell Farid Mockingbird"


class FakeOcr:
    """Stands in for OCRExtractor and GlmOcrExtractor page OCR."""

    def __init__(self, pages: dict[int, str]) -> None:
        self.pages = pages
        self.calls: list[list[int]] = []

    def extract_pages(self, filepath: Path, pages: list[int]) -> dict[int, str]:
        self.calls.append(list(pages))
        return {n: t for n, t in self.pages.items() if n in pages}

    def extract(self, filepath: Path) -> tuple[str, float]:
        return "", 0.0


def _extract(pipeline: ExtractionPipeline, path: Path, tmp: Path) -> tuple[Any, str]:
    entry = pipeline.extract_single(path.resolve(), tmp)
    out = tmp / ExtractionPipeline._safe_text_name(str(path.resolve()))
    return entry, out.read_text(encoding="utf-8") if out.exists() else ""


class TestPageSelection:
    def test_empty_and_tiny_pages_need_ocr(self) -> None:
        pages = ["A real page of text with plenty of words in it.", "", "x" * 30, "  \n ", "p. 3"]
        assert pdf_pages.pages_from_text(pages) == [2, 4, 5]

    def test_all_text_pages(self) -> None:
        assert pdf_pages.pages_from_text(["a" * 100, "b" * 100]) == []

    def test_inspector_wins_when_it_answers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pdf_pages, "_inspector_pages", lambda _p: [3])
        assert pdf_pages.pages_needing_ocr(MIXED, ["a" * 100, "", "b" * 100]) == [3]

    def test_falls_back_to_text_rule_when_inspector_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pdf_pages, "_inspector_pages", lambda _p: None)
        assert pdf_pages.pages_needing_ocr(MIXED, ["a" * 100, "", "b" * 100]) == [2]

    def test_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pdf_pages, "_inspector_pages", lambda _p: None)
        pages = [""] * (pdf_pages.MAX_OCR_PAGES + 10)
        assert len(pdf_pages.pages_needing_ocr(MIXED, pages)) == pdf_pages.MAX_OCR_PAGES

    def test_real_inspector_on_mixed_file(self) -> None:
        pytest.importorskip("pdf_inspector")
        assert pdf_pages._inspector_pages(MIXED) == [2, 4]

    def test_inspector_missing_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "pdf_inspector", None)
        assert pdf_pages._inspector_pages(MIXED) is None


@pytest.fixture(params=["with_inspector", "without_inspector"])
def inspector_mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run pipeline tests with and without the optional pdf-inspector classifier."""
    if request.param == "without_inspector":
        monkeypatch.setitem(sys.modules, "pdf_inspector", None)
    else:
        pytest.importorskip("pdf_inspector")
    return str(request.param)


@pytest.mark.usefixtures("inspector_mode")
class TestPipeline:
    def test_scanned_pages_are_filled_in_order(self, tmp_path: Path) -> None:
        ocr = FakeOcr({2: PAGE2, 4: PAGE4})
        entry, text = _extract(ExtractionPipeline(ocr=ocr), MIXED, tmp_path)  # type: ignore[arg-type]
        assert ocr.calls == [[2, 4]]
        assert text.index("--- Page 1 ---") < text.index(PAGE2) < text.index("--- Page 3 ---") < text.index(PAGE4)
        assert "--- Page 2 ---" in text
        assert "ocr_pages" in " ".join(entry.fallback_chain)

    def test_glm_is_tried_before_tesseract(self, tmp_path: Path) -> None:
        glm = FakeOcr({2: PAGE2})
        tess = FakeOcr({4: PAGE4})
        pipeline = ExtractionPipeline(ocr=tess, glm_ocr=glm)  # type: ignore[arg-type]
        _, text = _extract(pipeline, MIXED, tmp_path)
        assert glm.calls == [[2, 4]]
        assert tess.calls == [[4]]
        assert PAGE2 in text
        assert PAGE4 in text

    def test_missing_ocr_is_reported_not_silent(self, tmp_path: Path) -> None:
        entry, text = _extract(ExtractionPipeline(ocr=FakeOcr({})), MIXED, tmp_path)  # type: ignore[arg-type]
        assert PAGE2 not in text
        joined = " ".join(entry.failure_reasons)
        assert "pages 2, 4" in joined
        assert "incomplete" in joined

    def test_text_pdf_never_calls_ocr(self, tmp_path: Path) -> None:
        ocr = FakeOcr({})
        _extract(ExtractionPipeline(ocr=ocr), TEXT_ONLY, tmp_path)  # type: ignore[arg-type]
        assert ocr.calls == []


LOOP_LINE = "Synthetic test document. All names, amounts and dates are invented."


class TestCollapseRepeats:
    def test_looping_output_is_trimmed_to_first_copy(self) -> None:
        text, looped = collapse_repeats(f"{PAGE2}\n" + (f"{LOOP_LINE}\n" * 50))
        assert looped is True
        assert text.count(LOOP_LINE) == 1
        assert PAGE2 in text

    def test_repeated_block_is_trimmed(self) -> None:
        block = "Section 2.1 The Customer shall pay USD 1,250,000.00 per year.\nSection 2.2 Invoices are due soon.\n"
        text, looped = collapse_repeats(block * 20)
        assert looped is True
        assert text.count("Section 2.1") == 1
        assert text.count("Section 2.2") == 1

    def test_normal_text_is_untouched(self) -> None:
        original = f"{PAGE2}\n{LOOP_LINE}\n{LOOP_LINE}\nN/A\nN/A\nN/A\nN/A\nN/A\n"
        text, looped = collapse_repeats(original)
        assert looped is False
        assert text == original

    def test_short_lines_never_count_as_a_loop(self) -> None:
        original = "Yes\n" * 30
        assert collapse_repeats(original) == (original, False)


@pytest.mark.usefixtures("inspector_mode")
class TestLoopingOcr:
    def test_loop_is_trimmed_and_reported(self, tmp_path: Path) -> None:
        looping = f"{PAGE2}\n" + f"{LOOP_LINE}\n" * 40
        entry, text = _extract(ExtractionPipeline(ocr=FakeOcr({2: looping, 4: PAGE4})), MIXED, tmp_path)  # type: ignore[arg-type]
        assert PAGE2 in text
        assert text.count(LOOP_LINE) <= 4  # one per text page at most, none from the loop
        joined = " ".join(entry.failure_reasons)
        assert "page 2" in joined
        assert "repeated itself" in joined


class TestGlmPages:
    def test_renders_and_reads_only_requested_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []

        def fake_ocr(paths: list[Path]) -> list[str]:
            seen.append([p.name for p in paths])
            return [f"text of {p.stem}" for p in paths]

        monkeypatch.setattr(glm_ocr, "_import_ollama", lambda: object())
        monkeypatch.setattr(glm_ocr, "_ollama_ocr_pages", fake_ocr)
        out = GlmOcrExtractor().extract_pages(MIXED, [2, 4])
        assert seen == [["page_002.png", "page_004.png"]]
        assert out == {2: "text of page_002", 4: "text of page_004"}

    def test_ignores_pages_beyond_the_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(glm_ocr, "_import_ollama", lambda: object())
        monkeypatch.setattr(glm_ocr, "_ollama_ocr_pages", lambda paths: ["t"] * len(paths))
        assert set(GlmOcrExtractor().extract_pages(MIXED, [2, 99])) == {2}

    def test_non_pdf_returns_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert GlmOcrExtractor().extract_pages(f, [1]) == {}

    def test_no_backend_returns_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(glm_ocr, "_import_ollama", lambda: None)
        monkeypatch.setattr(GlmOcrExtractor, "_has_mlx", lambda self: False)
        assert GlmOcrExtractor().extract_pages(MIXED, [2]) == {}


class TestTesseractPages:
    def test_reads_requested_pages_with_languages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        langs: list[str] = []
        fake = types.ModuleType("pytesseract")

        def image_to_string(img: object, lang: str) -> str:
            langs.append(lang)
            return f"ocr {img}"

        fake.image_to_string = image_to_string  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pytesseract", fake)
        monkeypatch.setattr(OCRExtractor, "_page_image", staticmethod(lambda _p, n, _d: f"img{n}"))
        out = OCRExtractor(languages=["deu", "eng"]).extract_pages(MIXED, [2, 4])
        assert out == {2: "ocr img2", 4: "ocr img4"}
        assert langs == ["deu+eng", "deu+eng"]

    def test_missing_pytesseract_returns_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "pytesseract", None)
        assert OCRExtractor().extract_pages(MIXED, [2]) == {}
