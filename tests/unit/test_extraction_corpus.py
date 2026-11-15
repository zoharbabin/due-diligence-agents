"""Contract tests for the synthetic extraction corpus (tests/fixtures/extraction_corpus).

The corpus is committed. These tests check that the files and ``ground_truth.json``
agree, and that the labels (text layer, scanned, damaged, encrypted) are true when
read with the repo's own PDF engine. They need no builder dependencies.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

CORPUS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "extraction_corpus"
NON_CORPUS_FILES = {"__init__.py", "build.py", "README.md", "ground_truth.json"}
MAX_TOTAL_BYTES = 5 * 1024 * 1024


def _load_corpus() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "extraction_corpus", CORPUS_DIR / "__init__.py", submodule_search_locations=[str(CORPUS_DIR)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["extraction_corpus"] = module
    spec.loader.exec_module(module)
    return module


corpus = _load_corpus()
ENTRIES: dict[str, Any] = corpus.load_ground_truth()
PDFS = {n: e for n, e in ENTRIES.items() if e.kind == "pdf"}
READABLE_PDFS = {n: e for n, e in PDFS.items() if e.expected_failure is None and e.damage != "truncated"}
OFFICE = {n: e for n, e in ENTRIES.items() if e.kind != "pdf"}

pdf_engine = None


def _engine() -> Any:
    pytest.importorskip("pikepdf")
    pytest.importorskip("pypdfium2")
    from dd_agents.extraction import pdf_engine as engine

    return engine


# ---------------------------------------------------------------------------
# Files and ground truth agree
# ---------------------------------------------------------------------------


def test_every_entry_has_a_file() -> None:
    missing = [n for n in ENTRIES if not (CORPUS_DIR / n).is_file()]
    assert missing == []


def test_every_file_has_an_entry() -> None:
    on_disk = {p.name for p in CORPUS_DIR.iterdir() if p.is_file() and not p.name.startswith(".")}
    assert sorted(on_disk - NON_CORPUS_FILES - set(ENTRIES)) == []


def test_corpus_size_and_count() -> None:
    total = sum((CORPUS_DIR / n).stat().st_size for n in ENTRIES)
    assert total < MAX_TOTAL_BYTES
    assert 30 <= len(ENTRIES) <= 50


def test_path_for() -> None:
    name = next(iter(ENTRIES))
    assert corpus.path_for(name) == CORPUS_DIR / name
    with pytest.raises(KeyError):
        corpus.path_for("not_in_corpus.pdf")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_entry_schema(name: str) -> None:
    e = ENTRIES[name]
    assert e.kind in corpus.KINDS
    assert e.language in corpus.LANGUAGES
    assert set(e.page_kinds) <= corpus.PAGE_KINDS
    assert e.expected_failure in (None, *corpus.EXPECTED_FAILURES)
    assert e.key_phrases and all(p.strip() for p in e.key_phrases)
    assert e.purpose.strip()
    assert (
        Path(name).suffix == {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx", "html": ".html"}[e.kind]
    )
    if e.kind == "pdf":
        assert e.page_kinds
        assert e.page_key_phrases is not None and len(e.page_key_phrases) == len(e.page_kinds)
        # has_text_layer is true exactly when at least one page has text
        assert e.has_text_layer == ("text" in e.page_kinds)
    else:
        assert e.page_kinds == ()
        assert e.has_text_layer
    if e.pair is not None:
        assert e.pair in ENTRIES
        if e.damage is None:
            # text and scanned copies point at each other; a damaged copy points at its source
            assert ENTRIES[e.pair].pair == name
        else:
            assert ENTRIES[e.pair].damage is None
    if e.damage == "user_password":
        assert e.expected_failure == "encrypted" and e.password
    if e.expected_failure == "encrypted":
        assert e.password
    for phrase in e.reading_order:
        assert phrase in e.key_phrases


def test_schema_covers_the_planned_corpus() -> None:
    langs = {e.language for e in PDFS.values()}
    assert langs == corpus.LANGUAGES
    for lang in corpus.LANGUAGES:
        assert ENTRIES[f"contract_{lang}_text.pdf"].page_kinds == ("text",)
        assert ENTRIES[f"contract_{lang}_scanned.pdf"].page_kinds == ("scanned",)
        assert ENTRIES[f"contract_{lang}_scanned.pdf"].pair == f"contract_{lang}_text.pdf"
    categories = {e.category for e in ENTRIES.values()}
    assert {
        "table_heavy",
        "two_column",
        "watermarked",
        "signature_stamp",
        "mixed",
        "truncated",
        "owner_password",
        "user_password",
        "office_docx",
        "office_docx_tracked",
        "office_xlsx",
        "office_pptx",
        "office_html",
        "persons",
    } <= categories
    assert {e.kind for e in ENTRIES.values()} == corpus.KINDS


def test_mixed_pdf_labels_each_page() -> None:
    e = ENTRIES["layout_mixed_en.pdf"]
    assert e.page_kinds == ("text", "scanned", "text", "scanned")
    assert e.has_text_layer


def test_person_fixture_has_names_roles_and_birth_dates() -> None:
    people = [p for e in ENTRIES.values() if e.language == "en" for p in e.persons]
    assert len({p.name for p in people}) >= 5
    for p in people:
        assert p.role and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.date_of_birth)


def test_ground_truth_text_is_invented() -> None:
    blob = (CORPUS_DIR / "ground_truth.json").read_text(encoding="utf-8")
    assert "Subject A" in blob
    # no e-mail address or web address that is not on a reserved example domain
    for host in re.findall(r"@([A-Za-z0-9.-]+)", blob):
        assert host.endswith(".example")
    assert "http" not in blob


# ---------------------------------------------------------------------------
# PDF labels are true (read with the repo's PDF engine)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(READABLE_PDFS))
def test_pdf_pages_match_labels(name: str) -> None:
    engine = _engine()
    e = READABLE_PDFS[name]
    pages = engine.extract_pages(e.path)
    assert len(pages) == len(e.page_kinds)
    for number, (text, kind, phrases) in enumerate(zip(pages, e.page_kinds, e.page_key_phrases, strict=True), start=1):
        if kind == "scanned":
            assert text.strip() == "", f"{name} page {number} is labeled scanned but has a text layer"
        else:
            missing = [p for p in phrases if not corpus.phrase_in(text, p)]
            assert missing == [], f"{name} page {number} lost {missing}"


@pytest.mark.parametrize("name", sorted(n for n, e in READABLE_PDFS.items() if "scanned" not in e.page_kinds))
def test_text_pdf_has_all_key_phrases(name: str) -> None:
    engine = _engine()
    text = "\n".join(engine.extract_pages(READABLE_PDFS[name].path))
    assert [p for p in READABLE_PDFS[name].key_phrases if not corpus.phrase_in(text, p)] == []


@pytest.mark.parametrize("name", sorted(n for n, e in READABLE_PDFS.items() if not e.has_text_layer))
def test_scanned_pdf_is_image_only(name: str) -> None:
    engine = _engine()
    pdf_bytes = READABLE_PDFS[name].path.read_bytes()
    assert b"/Image" in pdf_bytes
    assert "".join(engine.extract_pages(READABLE_PDFS[name].path)).strip() == ""


def test_scanned_copy_matches_its_text_pair() -> None:
    for lang in corpus.LANGUAGES:
        text, scan = ENTRIES[f"contract_{lang}_text.pdf"], ENTRIES[f"contract_{lang}_scanned.pdf"]
        assert text.key_phrases == scan.key_phrases


def test_table_cells_are_in_the_table_pdf() -> None:
    engine = _engine()
    e = ENTRIES["layout_table_heavy_en.pdf"]
    text = "\n".join(engine.extract_pages(e.path))
    assert [c for c in e.flat_table_cells if not corpus.phrase_in(text, c)] == []


def test_two_column_reading_order_is_defined() -> None:
    e = ENTRIES["layout_two_column_en.pdf"]
    assert len(e.reading_order) == 6


def test_watermark_text_is_in_the_text_layer() -> None:
    engine = _engine()
    e = ENTRIES["layout_watermarked_en.pdf"]
    assert e.watermark_text
    text = "\n".join(engine.extract_pages(e.path))
    assert e.watermark_text.replace(" ", "") in corpus.normalize(text)


# ---------------------------------------------------------------------------
# Damaged PDFs behave as labeled
# ---------------------------------------------------------------------------


def test_truncated_pdf_opens_only_after_repair() -> None:
    engine = _engine()
    import pypdfium2

    e = ENTRIES["damaged_truncated_en.pdf"]
    with pytest.raises(pypdfium2.PdfiumError):
        pypdfium2.PdfDocument(str(e.path))
    pages = engine.extract_pages(e.path)
    assert len(pages) == len(e.page_kinds)
    recovered = [i for i, phrases in enumerate(e.page_key_phrases) if phrases]
    assert recovered, "ground truth must list at least one recoverable page"
    for i in recovered:
        assert [p for p in e.page_key_phrases[i] if not corpus.phrase_in(pages[i], p)] == []
    assert ENTRIES[e.pair].page_kinds == e.page_kinds
    assert e.path.stat().st_size < ENTRIES[e.pair].path.stat().st_size


def test_owner_password_pdf_opens_without_a_password() -> None:
    engine = _engine()
    e = ENTRIES["damaged_owner_password_en.pdf"]
    assert e.expected_failure is None
    assert b"/Encrypt" in e.path.read_bytes()
    assert engine.probe(e.path).encrypted is False
    text = "\n".join(engine.extract_pages(e.path))
    assert [p for p in e.key_phrases if not corpus.phrase_in(text, p)] == []


def test_user_password_pdf_is_flagged_encrypted() -> None:
    engine = _engine()
    e = ENTRIES["damaged_user_password_en.pdf"]
    assert e.expected_failure == "encrypted"
    assert engine.probe(e.path).encrypted is True
    with pytest.raises(engine.PdfEncryptedError):
        engine.extract_pages(e.path)


def test_user_password_pdf_opens_with_the_listed_password() -> None:
    pikepdf = pytest.importorskip("pikepdf")
    e = ENTRIES["damaged_user_password_en.pdf"]
    with pikepdf.open(e.path, password=e.password) as pdf:
        assert len(pdf.pages) == 1
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(e.path)


# ---------------------------------------------------------------------------
# Office and HTML files (read with the standard library only)
# ---------------------------------------------------------------------------


def _xml_text(path: Path, parts: tuple[str, ...], tags: str) -> str:
    out: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            if name.startswith(parts) and name.endswith(".xml"):
                xml = zf.read(name).decode("utf-8")
                out += [re.sub(r"<[^>]+>", "", m) for m in re.findall(rf"<(?:{tags})[ >][^<]*", xml)]
    return " ".join(t.split(">", 1)[-1] if ">" in t else t for t in out)


def _office_text(path: Path, kind: str) -> str:
    if kind == "docx":
        return _xml_text(path, ("word/document.xml",), "w:t|w:delText")
    if kind == "pptx":
        return _xml_text(path, ("ppt/slides/", "ppt/notesSlides/"), "a:t")
    if kind == "xlsx":
        # Strings are stored inline in the sheets (write-only openpyxl workbook).
        with zipfile.ZipFile(path) as zf:
            sheet_names = " ".join(
                re.findall(r'<sheet [^>]*name="([^"]+)"', zf.read("xl/workbook.xml").decode("utf-8"))
            )
        return sheet_names + " " + _xml_text(path, ("xl/worksheets/", "xl/sharedStrings.xml"), "t")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(OFFICE))
def test_office_file_has_key_phrases_and_cells(name: str) -> None:
    e = OFFICE[name]
    text = _office_text(e.path, e.kind)
    assert [p for p in e.key_phrases if not corpus.phrase_in(text, p)] == []
    if e.kind != "xlsx" or e.table_cells:
        assert [c for c in e.flat_table_cells if not corpus.phrase_in(text, c)] == []


def test_xlsx_numeric_cells_are_stored_as_numbers() -> None:
    e = ENTRIES["office_arr_schedule_en.xlsx"]
    with zipfile.ZipFile(e.path) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    values = {float(v) for v in re.findall(r'<c [^>]*?(?<!t="s")>\s*<v>([^<]+)</v>', sheet)}
    assert all(any(abs(v - n) < 0.005 for v in values) for n in e.numeric_cells)


def test_tracked_changes_are_real_revision_marks() -> None:
    e = ENTRIES["office_tracked_changes_en.docx"]
    assert e.tracked_changes is not None
    with zipfile.ZipFile(e.path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    ins = " ".join(re.findall(r"<w:ins [^>]*>.*?</w:ins>", xml))
    dele = " ".join(re.findall(r"<w:del [^>]*>.*?</w:del>", xml))
    for phrase in e.tracked_changes.inserted:
        assert phrase in re.sub(r"<[^>]+>", "", ins)
    for phrase in e.tracked_changes.deleted:
        assert phrase in re.sub(r"<[^>]+>", "", dele)


def test_html_has_noise_the_extractor_should_drop() -> None:
    text = (CORPUS_DIR / "office_terms_en.html").read_text(encoding="utf-8")
    assert "<script>" in text and "<style>" in text and "<nav>" in text


def test_ground_truth_loader_is_cached_and_typed() -> None:
    assert corpus.load_ground_truth() is corpus.load_ground_truth()
    entry = ENTRIES["people_officers_en.pdf"]
    assert entry.persons[0].name
    assert isinstance(entry.page_kinds, tuple)
