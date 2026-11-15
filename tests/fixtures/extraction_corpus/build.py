"""Deterministic generator for the synthetic extraction corpus.

Writes the corpus files and ``ground_truth.json`` next to this script. The
generated files are committed, so CI and normal test runs never run this
script. Re-run it only to change the corpus, then commit the new files.

All text is invented: "Subject A", fake amounts, fake dates and fictional
people. No real companies, people or financials.

Builder-only dependencies (NOT in pyproject.toml, install ad hoc)::

    uv venv /tmp/ddbuild --python 3.13
    uv pip install --python /tmp/ddbuild/bin/python \\
        reportlab python-docx python-pptx openpyxl pikepdf pypdfium2 pillow fonttools
    /tmp/ddbuild/bin/python tests/fixtures/extraction_corpus/build.py

Fonts are SIL OFL 1.1 (Noto Sans, Noto Sans JP/SC/KR variable TTFs from the
google/fonts repository). They are downloaded once into ``--fonts-dir``,
checked against the pinned SHA-256 below, cut down to the glyphs the corpus
needs, fixed at weight 400 or 700, and embedded as subsets. System fonts are
never used.

Determinism: reportlab runs with ``invariant=1``, Office files get fixed
properties and a normalised zip, and the password PDFs use RC4-128 (qpdf
cannot make AES output repeatable). Run the script twice and compare the
printed SHA-256 column to check.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pikepdf
import pypdfium2 as pdfium
from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as RLTTFont
from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Fonts (SIL OFL 1.1)
# ---------------------------------------------------------------------------

_FONT_BASE = "https://raw." + "githubusercontent.com/google/fonts/main/ofl/"
FONT_SOURCES: dict[str, tuple[str, str]] = {
    "latin": (
        "notosans/NotoSans[wdth,wght].ttf",
        "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
    ),
    "ja": (
        "notosansjp/NotoSansJP[wght].ttf",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
    ),
    "zh": (
        "notosanssc/NotoSansSC[wght].ttf",
        "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da",
    ),
    "ko": (
        "notosanskr/NotoSansKR[wght].ttf",
        "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252",
    ),
}
LANG_FONT = {"en": "latin", "de": "latin", "fr": "latin", "es": "latin", "ja": "ja", "zh": "zh", "ko": "ko"}

FIXED_DT = datetime.datetime(2026, 3, 14, 12, 0, 0)
ZIP_DT = (2026, 3, 14, 12, 0, 0)
SCAN_DPI = 200
FOOTER = "Synthetic test document. All names, amounts and dates are invented."
USER_PASSWORD = "dd-corpus-user-pw"
OWNER_PASSWORD = "dd-corpus-owner-pw"
UNRECOVERABLE_FRACTION = 0.6

# ---------------------------------------------------------------------------
# Invented text
# ---------------------------------------------------------------------------

# Each language: title, body lines, key phrases (exact substrings of the lines).
LANG_DOCS: dict[str, dict[str, Any]] = {
    "en": {
        "title": "MASTER SERVICES AGREEMENT",
        "lines": [
            "This Agreement is made on 14 March 2026 between Subject A Ltd (the Supplier) and Subject B Holdings"
            " (the Customer).",
            "Section 2.1 Fees. The Customer shall pay the Supplier USD 1,250,000.00 per year.",
            "Section 4.2 Change of Control. Either party may terminate this Agreement on thirty (30) days written"
            " notice.",
            "Section 7.3 Liability. The total liability of the Supplier is capped at USD 3,500,000.00.",
            "Section 9.1 Term. This Agreement starts on 1 April 2026 and ends on 31 March 2029.",
            "Section 11 Governing law. This Agreement is governed by the laws of Subject Land.",
        ],
        "phrases": [
            "MASTER SERVICES AGREEMENT",
            "14 March 2026",
            "Subject A Ltd",
            "Subject B Holdings",
            "Section 2.1",
            "USD 1,250,000.00",
            "Section 4.2",
            "thirty (30) days",
            "Section 7.3",
            "USD 3,500,000.00",
            "Section 9.1",
            "31 March 2029",
            "Section 11",
        ],
    },
    "de": {
        "title": "RAHMENDIENSTLEISTUNGSVERTRAG",
        "lines": [
            "Dieser Vertrag wird am 14. März 2026 zwischen der Subject A GmbH (Auftragnehmer) und der Subject B"
            " Holding (Auftraggeber) geschlossen.",
            "§ 2.1 Vergütung. Der Auftraggeber zahlt dem Auftragnehmer 1.250.000,00 EUR pro Jahr.",
            "§ 4.2 Kontrollwechsel. Jede Partei kann den Vertrag mit einer Frist von dreißig (30) Tagen kündigen.",
            "§ 7.3 Haftung. Die Gesamthaftung des Auftragnehmers ist auf 3.500.000,00 EUR begrenzt.",
            "§ 9.1 Laufzeit. Der Vertrag beginnt am 1. April 2026 und endet am 31. März 2029.",
            "§ 11 Anwendbares Recht. Es gilt das Recht von Subject Land. Gerichtsstand ist Musterstadt.",
        ],
        "phrases": [
            "RAHMENDIENSTLEISTUNGSVERTRAG",
            "14. März 2026",
            "Subject A GmbH",
            "Subject B Holding",
            "§ 2.1",
            "1.250.000,00 EUR",
            "§ 4.2",
            "dreißig (30) Tagen",
            "§ 7.3",
            "3.500.000,00 EUR",
            "§ 9.1",
            "31. März 2029",
            "§ 11",
        ],
    },
    "fr": {
        "title": "CONTRAT-CADRE DE SERVICES",
        "lines": [
            "Le présent contrat est conclu le 14 mars 2026 entre Subject A SAS (le Prestataire) et Subject B"
            " Holding (le Client).",
            "Article 2.1 Honoraires. Le Client verse au Prestataire 1 250 000,00 EUR par an.",
            "Article 4.2 Changement de contrôle. Chaque partie peut résilier le contrat avec un préavis de trente"
            " (30) jours.",
            "Article 7.3 Responsabilité. La responsabilité totale du Prestataire est plafonnée à 3 500 000,00 EUR.",
            "Article 9.1 Durée. Le contrat débute le 1er avril 2026 et prend fin le 31 mars 2029.",
            "Article 11 Droit applicable. Le contrat est soumis au droit de Subject Land. Les tribunaux de"
            " Villeexemple sont compétents.",
        ],
        "phrases": [
            "CONTRAT-CADRE DE SERVICES",
            "14 mars 2026",
            "Subject A SAS",
            "Subject B Holding",
            "Article 2.1",
            "1 250 000,00 EUR",
            "Article 4.2",
            "trente (30) jours",
            "Article 7.3",
            "3 500 000,00 EUR",
            "Article 9.1",
            "31 mars 2029",
            "Article 11",
        ],
    },
    "es": {
        "title": "CONTRATO MARCO DE SERVICIOS",
        "lines": [
            "Este contrato se celebra el 14 de marzo de 2026 entre Subject A S.L. (el Proveedor) y Subject B Holding"
            " (el Cliente).",
            "Cláusula 2.1 Honorarios. El Cliente pagará al Proveedor 1.250.000,00 EUR al año.",
            "Cláusula 4.2 Cambio de control. Cualquiera de las partes puede resolver el contrato con treinta (30)"
            " días de preaviso.",
            "Cláusula 7.3 Responsabilidad. La responsabilidad total del Proveedor se limita a 3.500.000,00 EUR.",
            "Cláusula 9.1 Vigencia. El contrato comienza el 1 de abril de 2026 y termina el 31 de marzo de 2029.",
            "Cláusula 11 Ley aplicable. Se aplica la ley de Subject Land. Los tribunales de Ciudadejemplo son"
            " competentes.",
        ],
        "phrases": [
            "CONTRATO MARCO DE SERVICIOS",
            "14 de marzo de 2026",
            "Subject A S.L.",
            "Subject B Holding",
            "Cláusula 2.1",
            "1.250.000,00 EUR",
            "Cláusula 4.2",
            "treinta (30) días",
            "Cláusula 7.3",
            "3.500.000,00 EUR",
            "Cláusula 9.1",
            "31 de marzo de 2029",
            "Cláusula 11",
        ],
    },
    "ja": {
        "title": "業務委託基本契約書",
        "lines": [
            "本契約は、2026年3月14日、Subject A株式会社（以下「受託者」）と"
            "Subject Bホールディングス（以下「委託者」）との間で締結される。",
            "第2.1条（報酬）委託者は受託者に対し、年額125,000,000円を支払う。",
            "第4.2条（支配権の変更）各当事者は、30日前の書面通知により本契約を解除できる。",
            "第7.3条（責任）受託者の責任総額は350,000,000円を上限とする。",
            "第9.1条（期間）本契約は2026年4月1日に開始し、2029年3月31日に終了する。",
            "第11条（準拠法）本契約はサブジェクト国の法律に準拠する。",
        ],
        "phrases": [
            "業務委託基本契約書",
            "2026年3月14日",
            "Subject A株式会社",
            "Subject Bホールディングス",
            "第2.1条",
            "125,000,000円",
            "第4.2条",
            "30日前の書面通知",
            "第7.3条",
            "350,000,000円",
            "第9.1条",
            "2029年3月31日",
            "第11条",
        ],
    },
    "zh": {
        "title": "服务框架协议",
        "lines": [
            "本协议于2026年3月14日由Subject A有限公司（以下简称服务方）与Subject B控股公司（以下简称客户方）签订。",
            "第2.1条 费用。客户方每年向服务方支付人民币1,250,000.00元。",
            "第4.2条 控制权变更。任何一方可提前30日书面通知终止本协议。",
            "第7.3条 责任。服务方的责任总额以人民币3,500,000.00元为限。",
            "第9.1条 期限。本协议自2026年4月1日起生效，至2029年3月31日终止。",
            "第11条 适用法律。本协议适用主题国法律。",
        ],
        "phrases": [
            "服务框架协议",
            "2026年3月14日",
            "Subject A有限公司",
            "Subject B控股公司",
            "第2.1条",
            "人民币1,250,000.00元",
            "第4.2条",
            "提前30日书面通知",
            "第7.3条",
            "人民币3,500,000.00元",
            "第9.1条",
            "2029年3月31日",
            "第11条",
        ],
    },
    "ko": {
        "title": "서비스 기본 계약서",
        "lines": [
            "본 계약은 2026년 3월 14일 Subject A 주식회사(이하 수급인)와 "
            "Subject B 홀딩스(이하 도급인) 사이에 체결된다.",
            "제2.1조 (대금) 도급인은 수급인에게 연 125,000,000원을 지급한다.",
            "제4.2조 (지배권 변경) 각 당사자는 30일 전 서면 통지로 계약을 해지할 수 있다.",
            "제7.3조 (책임) 수급인의 총 책임은 350,000,000원을 한도로 한다.",
            "제9.1조 (기간) 본 계약은 2026년 4월 1일에 시작하여 2029년 3월 31일에 종료한다.",
            "제11조 (준거법) 본 계약은 서브젝트국 법률에 따른다.",
        ],
        "phrases": [
            "서비스 기본 계약서",
            "2026년 3월 14일",
            "Subject A 주식회사",
            "Subject B 홀딩스",
            "제2.1조",
            "125,000,000원",
            "제4.2조",
            "30일 전 서면 통지",
            "제7.3조",
            "350,000,000원",
            "제9.1조",
            "2029년 3월 31일",
            "제11조",
        ],
    },
}

# Fictional officers. Names are placeholders on purpose.
PERSONS: list[dict[str, str]] = [
    {
        "name": "Alexandra Testwell",
        "role": "Chief Executive Officer",
        "date_of_birth": "1968-02-11",
        "dob_text": "11 February 1968",
        "appointed": "1 June 2019",
    },
    {
        "name": "Benjamin Samplestein",
        "role": "Chief Financial Officer",
        "date_of_birth": "1974-09-23",
        "dob_text": "23 September 1974",
        "appointed": "15 January 2020",
    },
    {
        "name": "Chandra Placeholder",
        "role": "Non-Executive Director",
        "date_of_birth": "1961-07-05",
        "dob_text": "5 July 1961",
        "appointed": "3 March 2018",
    },
    {
        "name": "Dmitri Notareal",
        "role": "Director",
        "date_of_birth": "1979-11-30",
        "dob_text": "30 November 1979",
        "appointed": "12 August 2021",
    },
    {
        "name": "Elena Fictiva-Example",
        "role": "Company Secretary",
        "date_of_birth": "1985-04-17",
        "dob_text": "17 April 1985",
        "appointed": "1 October 2022",
    },
    {
        "name": "Farid Mockingbird",
        "role": "Chair of the Board",
        "date_of_birth": "1957-01-08",
        "dob_text": "8 January 1957",
        "appointed": "20 May 2017",
    },
]

# Customer register: (customer, contract id, ARR, renewal date, change-of-control clause).
CUSTOMERS: list[tuple[str, str, Decimal, str, str]] = [
    ("Subject C Ltd", "C-0001", Decimal("1240500.00"), "2027-01-14", "Yes"),
    ("Subject D GmbH", "C-0002", Decimal("486200.75"), "2026-09-30", "No"),
    ("Subject E SAS", "C-0003", Decimal("902340.10"), "2028-06-30", "Yes"),
    ("Subject F S.L.", "C-0004", Decimal("317890.00"), "2026-12-31", "No"),
    ("Subject G Corp", "C-0005", Decimal("58120.40"), "2027-03-31", "No"),
    ("Subject H KK", "C-0006", Decimal("214075.25"), "2029-02-28", "Yes"),
]
CUSTOMER_HEADER = ["Customer", "Contract", "ARR (USD)", "Renewal", "CoC clause"]


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def customer_rows() -> list[list[str]]:
    rows = [CUSTOMER_HEADER]
    rows += [[name, cid, money(arr), renewal, coc] for name, cid, arr, renewal, coc in CUSTOMERS]
    total = sum((c[2] for c in CUSTOMERS), Decimal("0"))
    rows.append(["Total", "", money(total), "", ""])
    return rows


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

FontSet = tuple[str, str]  # (regular, bold) reportlab font names


def ensure_font(key: str, fonts_dir: Path) -> Path:
    rel, digest = FONT_SOURCES[key]
    target = fonts_dir / Path(rel).name
    if not target.exists():
        fonts_dir.mkdir(parents=True, exist_ok=True)
        url = _FONT_BASE + urllib.parse.quote(rel, safe="/")
        print(f"downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
            target.write_bytes(resp.read())
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"{target} has SHA-256 {actual}, expected {digest}. Delete it and retry.")
    return target


def _glyph_text(key: str) -> str:
    """Characters to keep for one font."""
    chars = {chr(c) for c in range(0x20, 0x7F)}
    if key == "latin":
        chars |= {chr(c) for c in range(0xA0, 0x250)} | set("–—‘’“”•…€№·×")
        return "".join(sorted(chars))
    for lang, font_key in LANG_FONT.items():
        if font_key == key:
            doc = LANG_DOCS[lang]
            chars |= set(doc["title"]) | set("".join(doc["lines"]))
    return "".join(sorted(chars))


def prepare_fonts(fonts_dir: Path, work: Path) -> dict[str, FontSet]:
    """Subset each font and register regular and bold instances with reportlab."""
    sets: dict[str, FontSet] = {}
    for key in FONT_SOURCES:
        src = ensure_font(key, fonts_dir)
        names = []
        for weight in (400, 700):
            font = TTFont(src, recalcTimestamp=False)
            axes = {"wght": float(weight)}
            if key == "latin":
                axes["wdth"] = 100.0
            # Instance first: subsetting a variable font first drops the variation data.
            font = instancer.instantiateVariableFont(font, axes, inplace=True)
            options = subset.Options()
            options.layout_features = []
            options.notdef_outline = True
            options.name_IDs = [1, 2, 3, 4, 6]
            subsetter = subset.Subsetter(options)
            subsetter.populate(text=_glyph_text(key))
            subsetter.subset(font)
            out = work / f"{key}-{weight}.ttf"
            font.save(out)
            name = f"Corpus-{key}-{weight}"
            pdfmetrics.registerFont(RLTTFont(name, str(out)))
            names.append(name)
        sets[key] = (names[0], names[1])
    return sets


# ---------------------------------------------------------------------------
# PDF drawing
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN = 56.0

Op = tuple[Any, ...]


def wrap_text(text: str, font: str, size: float, width: float) -> list[str]:
    """Break *text* into lines. Break at spaces when possible, else at any character (CJK)."""
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            cur = trial
            continue
        cut = cur.rfind(" ")
        if cut > 0 and ch != " ":
            lines.append(cur[:cut])
            cur = cur[cut + 1 :] + ch
        else:
            lines.append(cur)
            cur = ch.lstrip()
    if cur:
        lines.append(cur)
    return lines


def _table(
    c: Canvas, rows: list[list[str]], cols: list[tuple[float, str]], fonts: FontSet, x: float, y: float
) -> float:
    regular, bold = fonts
    row_h = 20.0
    for r, row in enumerate(rows):
        top = y - r * row_h
        header = r == 0
        total = r == len(rows) - 1 and row[0] == "Total"
        if header:
            c.setFillGray(0.9)
            c.rect(x, top - row_h, sum(w for w, _ in cols), row_h, stroke=0, fill=1)
            c.setFillGray(0)
        cx = x
        for (w, align), text in zip(cols, row, strict=True):
            c.rect(cx, top - row_h, w, row_h, stroke=1, fill=0)
            font = bold if header or total else regular
            if pdfmetrics.stringWidth(text, font, 10) > w - 8:
                raise ValueError(f"cell {text!r} does not fit in {w}pt")
            c.setFont(font, 10)
            if align == "r":
                c.drawRightString(cx + w - 4, top - 14, text)
            else:
                c.drawString(cx + 4, top - 14, text)
            cx += w
    return y - len(rows) * row_h - 10


def _stamp(c: Canvas, lines: list[str], signer: str, fonts: FontSet, x: float, y: float) -> float:
    regular, bold = fonts
    width, height = 300.0, 24 + 13 * len(lines) + 26
    c.setFillColorRGB(1.0, 0.98, 0.85)
    c.setStrokeColorRGB(0.6, 0.5, 0.1)
    c.rect(x, y - height, width, height, stroke=1, fill=1)
    c.setFillGray(0)
    c.setStrokeGray(0)
    cy = y - 16
    c.setFont(bold, 9)
    c.drawString(x + 8, cy, lines[0])
    cy -= 22
    c.setFont(bold, 15)
    c.drawString(x + 8, cy, signer)
    c.setFont(regular, 8)
    for line in lines[1:]:
        cy -= 13
        c.drawString(x + 8, cy, line)
    return y - height - 12


def _run_ops(c: Canvas, ops: list[Op], fonts: FontSet, x: float, width: float, y: float) -> float:
    regular, bold = fonts
    for op in ops:
        kind = op[0]
        if kind == "title":
            c.setFont(bold, 16)
            for line in wrap_text(op[1], bold, 16, width):
                y -= 20
                c.drawString(x, y, line)
            y -= 10
        elif kind == "h":
            c.setFont(bold, 12)
            for line in wrap_text(op[1], bold, 12, width):
                y -= 17
                c.drawString(x, y, line)
            y -= 4
        elif kind == "p":
            c.setFont(regular, 11)
            for line in wrap_text(op[1], regular, 11, width):
                y -= 15
                c.drawString(x, y, line)
            y -= 7
        elif kind == "gap":
            y -= op[1]
        elif kind == "table":
            y = _table(c, op[1], op[2], fonts, x, y)
        elif kind == "stamp":
            y = _stamp(c, op[1], op[2], fonts, x, y)
        elif kind == "cols":
            gutter = 24.0
            col_w = (width - gutter) / 2
            ends = [_run_ops(c, col, fonts, x + i * (col_w + gutter), col_w, y) for i, col in enumerate(op[1])]
            y = min(ends)
        elif kind == "footer":
            c.setFont(regular, 8)
            c.setFillGray(0.35)
            c.drawString(x, 32, op[1])
            c.setFillGray(0)
        else:
            raise ValueError(f"unknown op {kind!r}")
    return y


def _draw_page(c: Canvas, ops: list[Op], fonts: FontSet, watermark: str | None) -> None:
    if watermark:
        c.saveState()
        c.setFillGray(0.82)
        c.setFont(fonts[1], 64)
        c.translate(PAGE_W / 2, PAGE_H / 2)
        c.rotate(45)
        c.drawCentredString(0, 0, watermark)
        c.restoreState()
    _run_ops(c, ops, fonts, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - MARGIN)
    c.showPage()


def _canvas(buf: io.BytesIO, title: str) -> Canvas:
    c = Canvas(buf, pagesize=A4, invariant=1, pageCompression=1)
    c.setTitle(title)
    c.setAuthor("dd-agents synthetic corpus")
    c.setSubject("Invented test data")
    return c


def _jpeg(img: Any) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70)
    return out.getvalue()


def build_pdf(
    title: str,
    pages: list[list[Op]],
    fonts: FontSet,
    *,
    scanned: frozenset[int] = frozenset(),
    watermark: str | None = None,
) -> bytes:
    """Draw *pages* as a text PDF. Pages in *scanned* become image-only (rendered, no text layer)."""
    from reportlab.lib.utils import ImageReader

    text_buf = io.BytesIO()
    c = _canvas(text_buf, title)
    for ops in pages:
        _draw_page(c, ops, fonts, watermark)
    c.save()
    if not scanned:
        return text_buf.getvalue()

    images: dict[int, bytes] = {}
    doc = pdfium.PdfDocument(text_buf.getvalue())
    try:
        for index in sorted(scanned):
            bitmap = doc[index].render(scale=SCAN_DPI / 72, grayscale=True)
            images[index] = _jpeg(bitmap.to_pil().convert("L"))
    finally:
        doc.close()

    buf = io.BytesIO()
    c = _canvas(buf, title)
    for index, ops in enumerate(pages):
        if index in scanned:
            c.drawImage(ImageReader(io.BytesIO(images[index])), 0, 0, width=PAGE_W, height=PAGE_H)
            c.showPage()
        else:
            _draw_page(c, ops, fonts, watermark)
    c.save()
    return buf.getvalue()


def contract_page(lang: str) -> list[Op]:
    doc = LANG_DOCS[lang]
    ops: list[Op] = [("title", doc["title"])]
    ops += [("p", line) for line in doc["lines"]]
    ops.append(("footer", FOOTER))
    return ops


# ---------------------------------------------------------------------------
# Damage helpers
# ---------------------------------------------------------------------------


def encrypt_pdf(data: bytes, user: str, owner: str, *, restrict: bool) -> bytes:
    allow = pikepdf.Permissions(extract=False, print_lowres=False, print_highres=False) if restrict else None
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = io.BytesIO()
        enc = pikepdf.Encryption(
            user=user, owner=owner, R=3, aes=False, metadata=False, **({"allow": allow} if allow else {})
        )
        pdf.save(out, encryption=enc, static_id=True)
    return out.getvalue()


def repaired_pages(data: bytes) -> list[str]:
    """Text per page after the same repair the extraction engine uses (qpdf rewrite, then PDFium)."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        out = io.BytesIO()
        pdf.save(out)
    doc = pdfium.PdfDocument(out.getvalue())
    try:
        texts = []
        for page in doc:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        return texts
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Office helpers
# ---------------------------------------------------------------------------


def normalize_zip(data: bytes) -> bytes:
    """Rewrite a zip with fixed timestamps and attributes so the bytes repeat."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=ZIP_DT)
            clone.compress_type = zipfile.ZIP_DEFLATED
            clone.external_attr = 0o600 << 16
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                # openpyxl stamps "modified" with the current time when it saves.
                content = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>2026-03-14T12:00:00Z", content)
            dst.writestr(clone, content)
    return out.getvalue()


def _set_core(props: Any, title: str) -> None:
    props.author = "dd-agents synthetic corpus"
    props.title = title
    props.created = FIXED_DT
    props.modified = FIXED_DT
    props.last_modified_by = "dd-agents synthetic corpus"


def build_docx_contract() -> tuple[bytes, list[list[str]]]:
    from docx import Document

    doc = Document()
    _set_core(doc.core_properties, "Master Services Agreement (synthetic)")
    en = LANG_DOCS["en"]
    doc.add_heading(en["title"], level=1)
    for line in en["lines"]:
        doc.add_paragraph(line)
    doc.add_heading("Schedule 1 Fee Table", level=2)
    rows = [
        ["Service", "Unit", "Fee (USD)"],
        ["Platform licence", "per year", "1,250,000.00"],
        ["Premium support", "per year", "180,000.00"],
        ["Onboarding", "one-off", "45,500.50"],
    ]
    table = doc.add_table(rows=len(rows), cols=3)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for ci, text in enumerate(row):
            table.cell(r, ci).text = text
    doc.add_paragraph(FOOTER)
    buf = io.BytesIO()
    doc.save(buf)
    return normalize_zip(buf.getvalue()), rows


def build_docx_tracked() -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def tracked(kind: str, rev_id: int, text: str) -> Any:
        wrapper = OxmlElement(f"w:{kind}")
        wrapper.set(qn("w:id"), str(rev_id))
        wrapper.set(qn("w:author"), "Reviewer Example")
        wrapper.set(qn("w:date"), "2026-03-10T09:00:00Z")
        run = OxmlElement("w:r")
        node = OxmlElement("w:delText" if kind == "del" else "w:t")
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = text
        run.append(node)
        wrapper.append(run)
        return wrapper

    doc = Document()
    _set_core(doc.core_properties, "Amendment with tracked changes (synthetic)")
    doc.add_heading("AMENDMENT NO. 1", level=1)
    doc.add_paragraph(
        "This Amendment to the agreement of 14 March 2026 is made between Subject A Ltd and Subject B Holdings."
    )
    p = doc.add_paragraph("Section 4.2 The notice period is ")
    p._p.append(tracked("del", 1, "sixty (60)"))
    p._p.append(tracked("ins", 2, "thirty (30)"))
    p.add_run(" days.")
    p2 = doc.add_paragraph("Section 7.3 The liability cap is ")
    p2._p.append(tracked("del", 3, "USD 2,000,000.00"))
    p2._p.append(tracked("ins", 4, "USD 3,500,000.00"))
    p2.add_run(".")
    doc.add_paragraph("All other terms remain unchanged.")
    buf = io.BytesIO()
    doc.save(buf)
    return normalize_zip(buf.getvalue())


def build_docx_ja() -> bytes:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Pt

    doc = Document()
    _set_core(doc.core_properties, "Master Services Agreement, Japanese (synthetic)")
    style = doc.styles["Normal"]
    style.font.name = "Noto Sans JP"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans JP")
    ja = LANG_DOCS["ja"]
    doc.add_heading(ja["title"], level=1)
    for line in ja["lines"]:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return normalize_zip(buf.getvalue())


def build_docx_persons() -> bytes:
    from docx import Document

    doc = Document()
    _set_core(doc.core_properties, "Register of officers and directors (synthetic)")
    doc.add_heading("REGISTER OF OFFICERS AND DIRECTORS", level=1)
    doc.add_paragraph("Subject A Ltd, as at 14 March 2026. All persons named are fictional.")
    rows = person_rows()
    table = doc.add_table(rows=len(rows), cols=4)
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for ci, text in enumerate(row):
            table.cell(r, ci).text = text
    buf = io.BytesIO()
    doc.save(buf)
    return normalize_zip(buf.getvalue())


def person_rows() -> list[list[str]]:
    rows = [["Name", "Role", "Date of birth", "Appointed"]]
    rows += [[p["name"], p["role"], p["dob_text"], p["appointed"]] for p in PERSONS]
    return rows


XLSX_ROWS = [(name, cid, float(arr), renewal, coc) for name, cid, arr, renewal, coc in CUSTOMERS]


def build_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.properties.creator = "dd-agents synthetic corpus"
    wb.properties.created = FIXED_DT
    wb.properties.modified = FIXED_DT
    wb.properties.lastModifiedBy = "dd-agents synthetic corpus"
    ws = wb.active
    ws.title = "ARR Schedule"
    ws["A1"] = "ARR Schedule for Subject A Ltd (synthetic)"
    ws.merge_cells("A1:E1")
    for ci, head in enumerate(CUSTOMER_HEADER, start=1):
        ws.cell(row=3, column=ci, value=head)
    for ri, row in enumerate(XLSX_ROWS, start=4):
        for ci, value in enumerate(row, start=1):
            cell = ws.cell(row=ri, column=ci, value=value)
            if ci == 3:
                cell.number_format = "#,##0.00"
    total_row = 4 + len(XLSX_ROWS)
    ws.cell(row=total_row, column=1, value="Total")
    ws.cell(row=total_row, column=3, value=float(sum(c[2] for c in CUSTOMERS))).number_format = "#,##0.00"
    notes = wb.create_sheet("Notes")
    notes["A1"] = "Subject C Ltd has a change of control clause (Section 4.2)."
    notes["A2"] = "Subject H KK renews on 2029-02-28."
    buf = io.BytesIO()
    wb.save(buf)
    return normalize_zip(buf.getvalue())


PPTX_TABLE = [
    ["Metric", "Q1 2026", "Q4 2025"],
    ["Revenue (USD)", "4,120,000.00", "3,890,000.00"],
    ["Churn", "2.1%", "2.4%"],
    ["Headcount", "148", "141"],
]


def build_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    _set_core(prs.core_properties, "Board update (synthetic)")
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Board Update Q1 2026"
    s1.placeholders[1].text = "Subject A Ltd, prepared 14 March 2026"
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Key contract terms"
    body = s2.placeholders[1].text_frame
    body.text = "Annual fee USD 1,250,000.00"
    body.add_paragraph().text = "Change of control: Section 4.2, thirty (30) days notice"
    body.add_paragraph().text = "Liability cap USD 3,500,000.00"
    s2.notes_slide.notes_text_frame.text = "Speaker note: the term ends on 31 March 2029."
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "Financial summary"
    shape = s3.shapes.add_table(len(PPTX_TABLE), 3, Inches(0.8), Inches(2.0), Inches(8.4), Inches(2.0))
    for r, row in enumerate(PPTX_TABLE):
        for ci, text in enumerate(row):
            shape.table.cell(r, ci).text = text
    buf = io.BytesIO()
    prs.save(buf)
    return normalize_zip(buf.getvalue())


HTML_TABLE = [
    ["Plan", "Seats", "Monthly fee (USD)"],
    ["Standard", "50", "12,500.00"],
    ["Premium", "200", "48,000.00"],
    ["Enterprise", "1000", "210,750.25"],
]


def build_html() -> str:
    rows = "".join(
        "<tr>" + "".join(f"<{'th' if r == 0 else 'td'}>{cell}</{'th' if r == 0 else 'td'}>" for cell in row) + "</tr>\n"
        for r, row in enumerate(HTML_TABLE)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Terms of Service for Subject A Ltd (synthetic)</title>
<style>body {{ font-family: sans-serif; }} .hidden {{ display: none; }}</style>
<script>var tracker = "analytics-placeholder";</script>
</head>
<body>
<nav><a href="#fees">Fees</a> <a href="#term">Term</a></nav>
<h1>Terms of Service</h1>
<p>These terms are effective on 14 March 2026 and bind Subject A Ltd and the Customer.</p>
<h2 id="fees">1. Fees</h2>
<p>Section 1.1 The Customer pays the plan fee shown below each month.</p>
<table>
{rows}</table>
<h2 id="term">2. Term and termination</h2>
<p>Section 2.1 Either party may terminate on thirty (30) days written notice.</p>
<p>Section 2.2 Subject A Ltd may suspend the service after a change of control of the Customer.</p>
<footer>{FOOTER}</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def entry(
    *,
    kind: str,
    category: str,
    language: str,
    has_text_layer: bool,
    page_kinds: list[str],
    key_phrases: list[str],
    purpose: str,
    page_key_phrases: list[list[str]] | None = None,
    table_cells: list[list[str]] | None = None,
    numeric_cells: list[float] | None = None,
    reading_order: list[str] | None = None,
    persons: list[dict[str, str]] | None = None,
    tracked_changes: dict[str, list[str]] | None = None,
    watermark_text: str | None = None,
    expected_failure: str | None = None,
    damage: str | None = None,
    password: str | None = None,
    pair: str | None = None,
) -> dict[str, Any]:
    if page_key_phrases is None and kind == "pdf":
        page_key_phrases = [list(key_phrases)] if len(page_kinds) == 1 else None
    return {
        "kind": kind,
        "category": category,
        "language": language,
        "has_text_layer": has_text_layer,
        "page_kinds": page_kinds,
        "key_phrases": key_phrases,
        "page_key_phrases": page_key_phrases,
        "table_cells": table_cells or [],
        "numeric_cells": numeric_cells or [],
        "reading_order": reading_order or [],
        "persons": persons or [],
        "tracked_changes": tracked_changes,
        "watermark_text": watermark_text,
        "expected_failure": expected_failure,
        "damage": damage,
        "password": password,
        "pair": pair,
        "purpose": purpose,
    }


def build_corpus(out: Path, fonts_dir: Path) -> dict[str, dict[str, Any]]:
    files: dict[str, bytes] = {}
    gt: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="ddcorpus-fonts-") as tmp:
        font_sets = prepare_fonts(fonts_dir, Path(tmp))

        def fonts_for(lang: str) -> FontSet:
            return font_sets[LANG_FONT[lang]]

        en_fonts = fonts_for("en")

        # --- Languages: text layer and scanned pair -----------------------------------
        for lang in LANG_DOCS:
            phrases = LANG_DOCS[lang]["phrases"]
            text_name = f"contract_{lang}_text.pdf"
            scan_name = f"contract_{lang}_scanned.pdf"
            page = contract_page(lang)
            title = f"Contract {lang} (synthetic)"
            files[text_name] = build_pdf(title, [page], fonts_for(lang))
            files[scan_name] = build_pdf(title, [page], fonts_for(lang), scanned=frozenset({0}))
            gt[text_name] = entry(
                kind="pdf",
                category="contract_text",
                language=lang,
                has_text_layer=True,
                page_kinds=["text"],
                key_phrases=phrases,
                pair=scan_name,
                purpose=f"Text-layer contract page in {lang}. Baseline for per-language text extraction.",
            )
            gt[scan_name] = entry(
                kind="pdf",
                category="contract_scanned",
                language=lang,
                has_text_layer=False,
                page_kinds=["scanned"],
                key_phrases=phrases,
                pair=text_name,
                purpose=f"Same content as {text_name}, image only ({SCAN_DPI} dpi, no text layer). Needs OCR.",
            )

        # --- English layout PDFs -----------------------------------------------------
        rows = customer_rows()
        cols = [(130.0, "l"), (70.0, "l"), (100.0, "r"), (85.0, "l"), (80.0, "l")]
        table_page: list[Op] = [
            ("title", "Schedule 1 Customer Contract Register"),
            ("p", "Prepared for Subject A Ltd on 14 March 2026. Annual recurring revenue (ARR) per contract."),
            ("table", rows, cols),
            ("p", "CoC clause means the contract has a change of control right (Section 4.2)."),
            ("footer", FOOTER),
        ]
        table_phrases = [
            "Schedule 1 Customer Contract Register",
            "Prepared for Subject A Ltd on 14 March 2026",
            "CoC clause means the contract has a change of control right",
        ]
        files["layout_table_heavy_en.pdf"] = build_pdf("Table heavy (synthetic)", [table_page], en_fonts)
        gt["layout_table_heavy_en.pdf"] = entry(
            kind="pdf",
            category="table_heavy",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=table_phrases,
            table_cells=rows,
            pair="layout_table_heavy_en_scanned.pdf",
            purpose="Ruled financial table. Exact amounts and dates must survive extraction.",
        )
        files["layout_table_heavy_en_scanned.pdf"] = build_pdf(
            "Table heavy scanned (synthetic)", [table_page], en_fonts, scanned=frozenset({0})
        )
        gt["layout_table_heavy_en_scanned.pdf"] = entry(
            kind="pdf",
            category="table_heavy_scanned",
            language="en",
            has_text_layer=False,
            page_kinds=["scanned"],
            key_phrases=table_phrases,
            table_cells=rows,
            pair="layout_table_heavy_en.pdf",
            purpose="Image-only copy of the table page. OCR must read amounts exactly.",
        )

        col_a = [
            ("h", "Commercial"),
            ("p", "Revenue grew 18% in the first quarter of 2026."),
            ("p", "Subject C Ltd renewed for USD 1,240,500.00."),
            ("p", "Two customers have change of control rights under Section 4.2."),
        ]
        col_b = [
            ("h", "Legal"),
            ("p", "The liability cap is USD 3,500,000.00 under Section 7.3."),
            ("p", "No litigation is pending against Subject A Ltd."),
            ("p", "The data processing addendum was signed on 2 February 2026."),
        ]
        order = [op[1] for op in col_a[1:]] + [op[1] for op in col_b[1:]]
        files["layout_two_column_en.pdf"] = build_pdf(
            "Two column (synthetic)",
            [[("title", "BOARD SUMMARY"), ("cols", [col_a, col_b]), ("footer", FOOTER)]],
            en_fonts,
        )
        gt["layout_two_column_en.pdf"] = entry(
            kind="pdf",
            category="two_column",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=["BOARD SUMMARY", *order],
            reading_order=order,
            purpose="Two text columns. Column A must be read fully before column B.",
        )

        watermark = "CONFIDENTIAL DRAFT"
        files["layout_watermarked_en.pdf"] = build_pdf(
            "Watermarked (synthetic)", [contract_page("en")], en_fonts, watermark=watermark
        )
        gt["layout_watermarked_en.pdf"] = entry(
            kind="pdf",
            category="watermarked",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=LANG_DOCS["en"]["phrases"],
            watermark_text=watermark,
            purpose="Contract page with a large diagonal text watermark. Body text must not be lost or mixed up.",
        )

        stamp_lines = [
            "DocuSigned by:",
            "Envelope ID: 7F3A0000-FAKE-4000-8000-000000000001",
            "Signer ID: SYNTH-0001",
            "Signed on 2026-03-14 10:22:05 UTC",
            "IP address 192.0.2.10",
        ]
        sig_phrases = [
            "SIGNATURE PAGE",
            "IN WITNESS WHEREOF the parties have signed this Agreement on 14 March 2026.",
            "For Subject A Ltd",
            "Envelope ID: 7F3A0000-FAKE-4000-8000-000000000001",
            "Alexandra Testwell",
            "Signed on 2026-03-14 10:22:05 UTC",
            "Name: Alexandra Testwell, Chief Executive Officer",
        ]
        files["layout_signature_stamp_en.pdf"] = build_pdf(
            "Signature stamp (synthetic)",
            [
                [
                    ("title", "SIGNATURE PAGE"),
                    ("p", "IN WITNESS WHEREOF the parties have signed this Agreement on 14 March 2026."),
                    ("gap", 8),
                    ("h", "For Subject A Ltd"),
                    ("stamp", stamp_lines, "Alexandra Testwell"),
                    ("p", "Name: Alexandra Testwell, Chief Executive Officer"),
                    ("gap", 14),
                    ("h", "For Subject B Holdings"),
                    ("p", "Signature: ______________________"),
                    ("p", "Name: Farid Mockingbird, Chair of the Board"),
                    ("footer", FOOTER),
                ]
            ],
            en_fonts,
        )
        gt["layout_signature_stamp_en.pdf"] = entry(
            kind="pdf",
            category="signature_stamp",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=sig_phrases,
            purpose=(
                "DocuSign-style stamp box with envelope ID, signer name and timestamp, plus a blank signature line."
            ),
        )

        # Mixed: pages 1 and 3 have text, pages 2 and 4 are images.
        mixed_pages: list[tuple[list[Op], list[str]]] = [
            (
                [
                    ("title", "SERVICES AGREEMENT PART A"),
                    ("p", "This Agreement is made on 14 March 2026 between Subject A Ltd and Subject B Holdings."),
                    ("p", "Section 1.1 The Supplier provides the Services listed in Schedule 1."),
                    ("footer", FOOTER),
                ],
                ["SERVICES AGREEMENT PART A", "14 March 2026", "Subject A Ltd", "Section 1.1"],
            ),
            (
                [
                    ("title", "PART B COMMERCIAL TERMS"),
                    ("p", "Section 2.1 The Customer shall pay USD 1,250,000.00 per year."),
                    ("p", "Section 2.2 Invoices are due within forty-five (45) days."),
                    ("footer", FOOTER),
                ],
                ["PART B COMMERCIAL TERMS", "USD 1,250,000.00", "forty-five (45) days"],
            ),
            (
                [
                    ("title", "PART C RISK"),
                    ("p", "Section 7.3 The liability cap is USD 3,500,000.00."),
                    ("p", "Section 4.2 A change of control gives a right to terminate on thirty (30) days notice."),
                    ("footer", FOOTER),
                ],
                ["PART C RISK", "USD 3,500,000.00", "thirty (30) days notice"],
            ),
            (
                [
                    ("title", "PART D SIGNATURES"),
                    ("p", "Signed for Subject A Ltd by Alexandra Testwell on 14 March 2026."),
                    ("p", "Signed for Subject B Holdings by Farid Mockingbird on 14 March 2026."),
                    ("footer", FOOTER),
                ],
                ["PART D SIGNATURES", "Alexandra Testwell", "Farid Mockingbird"],
            ),
        ]
        mixed_kinds = ["text", "scanned", "text", "scanned"]
        files["layout_mixed_en.pdf"] = build_pdf(
            "Mixed text and scanned (synthetic)",
            [ops for ops, _ in mixed_pages],
            en_fonts,
            scanned=frozenset(i for i, k in enumerate(mixed_kinds) if k == "scanned"),
        )
        mixed_phrases = [ph for _, phs in mixed_pages for ph in phs]
        gt["layout_mixed_en.pdf"] = entry(
            kind="pdf",
            category="mixed",
            language="en",
            has_text_layer=True,
            page_kinds=mixed_kinds,
            key_phrases=mixed_phrases,
            page_key_phrases=[phs for _, phs in mixed_pages],
            purpose="Four pages: text, scanned, text, scanned. Per-page classification and OCR routing.",
        )

        long_pages = [
            (
                "Section 1 Definitions",
                [
                    "1.1 Affiliate means any entity controlled by Subject A Ltd.",
                    "1.2 Effective Date means 14 March 2026.",
                    "1.3 Services means the hosted analytics services listed in Schedule 1.",
                ],
                ["1.2 Effective Date means 14 March 2026", "hosted analytics services listed in Schedule 1"],
            ),
            (
                "Section 2 Fees",
                [
                    "2.1 The annual fee is USD 1,250,000.00, invoiced quarterly.",
                    "2.2 Late payments accrue interest at 1.5% per month.",
                    "2.3 All fees exclude taxes.",
                ],
                ["annual fee is USD 1,250,000.00", "interest at 1.5% per month"],
            ),
            (
                "Section 3 Term and renewal",
                [
                    "3.1 The initial term ends on 31 March 2029.",
                    "3.2 The term renews for one (1) year unless a party gives ninety (90) days notice.",
                    "3.3 Renewal fees may rise by up to 5%.",
                ],
                ["initial term ends on 31 March 2029", "ninety (90) days notice"],
            ),
            (
                "Section 4 Change of control",
                [
                    "4.1 Subject B Holdings must tell the Supplier about any change of control.",
                    "4.2 The Supplier may terminate on thirty (30) days notice after a change of control.",
                    "4.3 Consent is not needed for internal reorganisations.",
                ],
                ["must tell the Supplier about any change of control", "terminate on thirty (30) days notice"],
            ),
            (
                "Section 5 Liability",
                [
                    "5.1 The liability cap is USD 3,500,000.00 in total.",
                    "5.2 Neither party is liable for indirect loss.",
                    "5.3 Data breach claims are capped at USD 7,000,000.00.",
                ],
                ["liability cap is USD 3,500,000.00", "capped at USD 7,000,000.00"],
            ),
            (
                "Section 6 General",
                [
                    "6.1 This Agreement is governed by the laws of Subject Land.",
                    "6.2 Notices must be sent to legal@subject-a.example.",
                    "6.3 Both parties signed this Agreement on 14 March 2026.",
                ],
                ["governed by the laws of Subject Land", "legal@subject-a.example"],
            ),
        ]
        long_ops = [
            [
                ("title", f"MASTER SERVICES AGREEMENT Page {i} of {len(long_pages)}"),
                ("h", head),
                *[("p", para) for para in paras],
                ("footer", FOOTER),
            ]
            for i, (head, paras, _) in enumerate(long_pages, start=1)
        ]
        long_pdf = build_pdf("Long contract (synthetic)", long_ops, en_fonts)
        long_phrases = [ph for _, _, phs in long_pages for ph in phs]
        files["layout_long_en.pdf"] = long_pdf
        gt["layout_long_en.pdf"] = entry(
            kind="pdf",
            category="long",
            language="en",
            has_text_layer=True,
            page_kinds=["text"] * len(long_pages),
            key_phrases=long_phrases,
            page_key_phrases=[phs for _, _, phs in long_pages],
            purpose="Six text pages with numbered clauses. Page order and clause numbers must survive.",
        )

        # --- Damaged PDFs ------------------------------------------------------------
        # Repairable: the tail is cut off (xref and end marker lost) but the trailer survives.
        # Drop bytes until the last page is gone, so the file is visibly incomplete.
        cut = b""
        kept: list[list[str]] = []
        for drop in range(50, len(long_pdf) // 2, 50):
            cut = long_pdf[:-drop]
            try:
                recovered = repaired_pages(cut)
            except pikepdf.PdfError:
                continue
            norm = ["".join(t.split()) for t in recovered]
            kept = []
            for i, (_, _, phs) in enumerate(long_pages):
                ok = i < len(norm) and all("".join(ph.split()) in norm[i] for ph in phs)
                kept.append(list(phs) if ok else [])
            if not kept[-1]:
                break
        if not kept or not kept[0] or kept[-1]:
            raise SystemExit("could not build a partly recoverable truncated PDF")
        files["damaged_truncated_en.pdf"] = cut
        gt["damaged_truncated_en.pdf"] = entry(
            kind="pdf",
            category="truncated",
            language="en",
            has_text_layer=True,
            page_kinds=["text"] * len(long_pages),
            key_phrases=[ph for phs in kept for ph in phs],
            page_key_phrases=kept,
            damage="truncated",
            pair="layout_long_en.pdf",
            purpose=(
                "layout_long_en.pdf with the tail cut off. PDFium cannot open it; qpdf repair can. "
                "Key phrases are for the pages that survive repair."
            ),
        )
        # Unrecoverable: cut in the middle. Trailer and page tree are gone.
        broken = long_pdf[: int(len(long_pdf) * UNRECOVERABLE_FRACTION)]
        try:
            repaired_pages(broken)
        except pikepdf.PdfError:
            pass
        else:
            raise SystemExit("the unrecoverable PDF was repaired; adjust UNRECOVERABLE_FRACTION")
        files["damaged_truncated_unrecoverable_en.pdf"] = broken
        gt["damaged_truncated_unrecoverable_en.pdf"] = entry(
            kind="pdf",
            category="truncated_unrecoverable",
            language="en",
            has_text_layer=True,
            page_kinds=["text"] * len(long_pages),
            key_phrases=long_phrases,
            page_key_phrases=[phs for _, _, phs in long_pages],
            expected_failure="unreadable",
            damage="truncated",
            pair="layout_long_en.pdf",
            purpose="First 60% of layout_long_en.pdf. Trailer and page tree are lost. No extractor can read it.",
        )
        base = files["contract_en_text.pdf"]
        files["damaged_owner_password_en.pdf"] = encrypt_pdf(base, "", OWNER_PASSWORD, restrict=True)
        gt["damaged_owner_password_en.pdf"] = entry(
            kind="pdf",
            category="owner_password",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=LANG_DOCS["en"]["phrases"],
            damage="owner_password",
            pair="contract_en_text.pdf",
            purpose="Empty user password, owner password set, copy and print restricted. Must open and extract.",
        )
        files["damaged_user_password_en.pdf"] = encrypt_pdf(base, USER_PASSWORD, OWNER_PASSWORD, restrict=False)
        gt["damaged_user_password_en.pdf"] = entry(
            kind="pdf",
            category="user_password",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=LANG_DOCS["en"]["phrases"],
            expected_failure="encrypted",
            damage="user_password",
            password=USER_PASSWORD,
            pair="contract_en_text.pdf",
            purpose="Needs the password in the password field. Without it the extractor must report encrypted.",
        )

        # --- Persons -----------------------------------------------------------------
        prow = person_rows()
        person_phrases = ["REGISTER OF OFFICERS AND DIRECTORS", "Subject A Ltd, as at 14 March 2026"]
        for p in PERSONS:
            person_phrases += [p["name"], p["role"], p["dob_text"]]
        files["people_officers_en.pdf"] = build_pdf(
            "Officers (synthetic)",
            [
                [
                    ("title", "REGISTER OF OFFICERS AND DIRECTORS"),
                    ("p", "Subject A Ltd, as at 14 March 2026. All persons named are fictional."),
                    (
                        "table",
                        prow,
                        [(130.0, "l"), (140.0, "l"), (110.0, "l"), (85.0, "l")],
                    ),
                    ("footer", FOOTER),
                ]
            ],
            en_fonts,
        )
        gt["people_officers_en.pdf"] = entry(
            kind="pdf",
            category="persons",
            language="en",
            has_text_layer=True,
            page_kinds=["text"],
            key_phrases=person_phrases,
            table_cells=prow,
            persons=[{k: p[k] for k in ("name", "role", "date_of_birth", "appointed")} for p in PERSONS],
            purpose="Fictional officers and directors with roles and dates of birth. For screening tests.",
        )
        files["people_officers_en.docx"] = build_docx_persons()
        gt["people_officers_en.docx"] = entry(
            kind="docx",
            category="persons",
            language="en",
            has_text_layer=True,
            page_kinds=[],
            key_phrases=person_phrases[:2] + [x for p in PERSONS for x in (p["name"], p["role"], p["dob_text"])],
            table_cells=prow,
            persons=[{k: p[k] for k in ("name", "role", "date_of_birth", "appointed")} for p in PERSONS],
            purpose="Same fictional officers as people_officers_en.pdf, as a Word table.",
        )

    # --- Office and HTML -------------------------------------------------------------
    docx_bytes, fee_rows = build_docx_contract()
    files["office_contract_en.docx"] = docx_bytes
    gt["office_contract_en.docx"] = entry(
        kind="docx",
        category="office_docx",
        language="en",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=LANG_DOCS["en"]["phrases"],
        table_cells=fee_rows,
        purpose="Word contract with headings and a fee table.",
    )
    files["office_tracked_changes_en.docx"] = build_docx_tracked()
    gt["office_tracked_changes_en.docx"] = entry(
        kind="docx",
        category="office_docx_tracked",
        language="en",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=[
            "AMENDMENT NO. 1",
            "This Amendment to the agreement of 14 March 2026 is made between Subject A Ltd and Subject B Holdings.",
            "Section 4.2 The notice period is",
            "Section 7.3 The liability cap is",
            "All other terms remain unchanged.",
        ],
        tracked_changes={
            "inserted": ["thirty (30)", "USD 3,500,000.00"],
            "deleted": ["sixty (60)", "USD 2,000,000.00"],
        },
        purpose="Word amendment with tracked insertions and deletions. Records what a reviewer would see.",
    )
    files["office_contract_ja.docx"] = build_docx_ja()
    gt["office_contract_ja.docx"] = entry(
        kind="docx",
        category="office_docx",
        language="ja",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=LANG_DOCS["ja"]["phrases"],
        purpose="Japanese Word contract. CJK in the Office path.",
    )
    files["office_arr_schedule_en.xlsx"] = build_xlsx()
    gt["office_arr_schedule_en.xlsx"] = entry(
        kind="xlsx",
        category="office_xlsx",
        language="en",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=[
            "ARR Schedule for Subject A Ltd (synthetic)",
            "Notes",
            "Subject C Ltd has a change of control clause (Section 4.2).",
            "Subject H KK renews on 2029-02-28.",
        ],
        table_cells=[[str(c) for c in CUSTOMER_HEADER]] + [[r[0], r[1], r[3], r[4]] for r in XLSX_ROWS],
        numeric_cells=[r[2] for r in XLSX_ROWS] + [float(sum(c[2] for c in CUSTOMERS))],
        purpose="Two sheets, merged title cell, numeric cells with a number format. Numbers are checked by value.",
    )
    files["office_board_deck_en.pptx"] = build_pptx()
    gt["office_board_deck_en.pptx"] = entry(
        kind="pptx",
        category="office_pptx",
        language="en",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=[
            "Board Update Q1 2026",
            "Subject A Ltd, prepared 14 March 2026",
            "Annual fee USD 1,250,000.00",
            "Change of control: Section 4.2, thirty (30) days notice",
            "Liability cap USD 3,500,000.00",
            "Speaker note: the term ends on 31 March 2029.",
        ],
        table_cells=PPTX_TABLE,
        purpose="Three slides: title, bullets with speaker notes, table.",
    )
    files["office_terms_en.html"] = build_html().encode("utf-8")
    gt["office_terms_en.html"] = entry(
        kind="html",
        category="office_html",
        language="en",
        has_text_layer=True,
        page_kinds=[],
        key_phrases=[
            "Terms of Service",
            "These terms are effective on 14 March 2026 and bind Subject A Ltd and the Customer.",
            "Section 1.1 The Customer pays the plan fee shown below each month.",
            "Section 2.1 Either party may terminate on thirty (30) days written notice.",
            "Section 2.2 Subject A Ltd may suspend the service after a change of control of the Customer.",
        ],
        table_cells=HTML_TABLE,
        purpose="HTML page with style and script blocks, navigation, a table and a footer.",
    )

    for name, data in files.items():
        (out / name).write_bytes(data)
    return gt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--out", type=Path, default=HERE, help="output directory (default: next to this script)")
    parser.add_argument(
        "--fonts-dir",
        type=Path,
        default=Path.home() / ".cache" / "dd-agents" / "extraction-corpus-fonts",
        help="where the OFL font files are cached",
    )
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    gt = build_corpus(out, args.fonts_dir)
    payload = {
        "schema_version": 1,
        "note": "All content is invented. Names, companies, amounts and dates are placeholders.",
        "files": dict(sorted(gt.items())),
    }
    (out / "ground_truth.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )

    total = 0
    for name in sorted(gt):
        data = (out / name).read_bytes()
        total += len(data)
        print(f"{hashlib.sha256(data).hexdigest()[:16]}  {len(data):>8}  {name}")
    print(f"{len(gt)} files, {total / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
