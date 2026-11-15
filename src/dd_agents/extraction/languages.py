"""OCR language configuration and checks (Issue #263).

Tesseract needs one language pack per language. GLM-OCR reads any script and
ignores these codes. Nothing here guesses a document's language: it counts
Unicode scripts in extracted text and says when no configured pack can read a
script that is clearly present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_CODE = re.compile(r"^(script/[A-Za-z_]+|[a-z]{3}(_[A-Za-z0-9]+)*)$")

# A script is reported only when it is at least this share of all letters
# and at least this many letters. Keeps stray foreign words from warning.
_MIN_SCRIPT_SHARE = 0.05
_MIN_SCRIPT_LETTERS = 10

# Script (first word of the Unicode name) -> Tesseract language codes that read it.
SCRIPT_LANGUAGES: dict[str, tuple[str, ...]] = {
    "CYRILLIC": ("bel", "bul", "kaz", "mkd", "rus", "srp", "tgk", "ukr", "uzb_cyrl"),
    "GREEK": ("ell", "grc"),
    "ARABIC": ("ara", "fas", "pus", "snd", "uig", "urd"),
    "HEBREW": ("heb", "yid"),
    "DEVANAGARI": ("hin", "mar", "nep", "san"),
    "BENGALI": ("asm", "ben"),
    "TAMIL": ("tam",),
    "TELUGU": ("tel",),
    "THAI": ("tha",),
    "HANGUL": ("kor", "kor_vert"),
    "HAN": ("chi_sim", "chi_sim_vert", "chi_tra", "chi_tra_vert", "jpn", "jpn_vert"),
    "HIRAGANA": ("jpn", "jpn_vert"),
    "KATAKANA": ("jpn", "jpn_vert"),
    "ARMENIAN": ("hye",),
    "GEORGIAN": ("kat", "kat_old"),
}

# Script (Tesseract "script/<Name>" models) -> Unicode scripts they read.
_SCRIPT_MODELS: dict[str, tuple[str, ...]] = {
    "Cyrillic": ("CYRILLIC",),
    "Greek": ("GREEK",),
    "Arabic": ("ARABIC",),
    "Hebrew": ("HEBREW",),
    "Devanagari": ("DEVANAGARI",),
    "Bengali": ("BENGALI",),
    "Tamil": ("TAMIL",),
    "Telugu": ("TELUGU",),
    "Thai": ("THAI",),
    "Hangul": ("HANGUL",),
    "HanS": ("HAN",),
    "HanT": ("HAN",),
    "Japanese": ("HAN", "HIRAGANA", "KATAKANA"),
    "Armenian": ("ARMENIAN",),
    "Georgian": ("GEORGIAN",),
}


def validate_language_codes(codes: Sequence[str]) -> list[str]:
    """Return *codes* de-duplicated in order. Raise ``ValueError`` on a bad code."""
    if not codes:
        raise ValueError("ocr_languages needs at least one language code")
    seen: list[str] = []
    for code in codes:
        if not isinstance(code, str) or not _CODE.match(code):
            raise ValueError(
                f"invalid OCR language code {code!r}. Use Tesseract codes such as 'eng', 'deu', 'chi_sim' "
                "or 'script/Cyrillic'"
            )
        if code not in seen:
            seen.append(code)
    return seen


def installed_tesseract_languages() -> list[str] | None:
    """Language packs Tesseract reports, sorted. ``None`` if Tesseract cannot be queried."""
    binary = shutil.which("tesseract")
    if binary is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [binary, "--list-langs"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in proc.stdout.splitlines()[1:] if ln.strip()]
    return sorted(ln for ln in lines if ln != "osd")


@dataclass(frozen=True)
class LanguageSetup:
    """Requested OCR languages versus what is installed."""

    requested: list[str]
    installed: list[str] | None
    missing: list[str]

    @property
    def ok(self) -> bool:
        return self.installed is not None and not self.missing


def check_language_setup(requested: Sequence[str], installed: Sequence[str] | None) -> LanguageSetup:
    req = list(requested)
    if installed is None:
        return LanguageSetup(req, None, [])
    have = set(installed)
    return LanguageSetup(req, sorted(installed), [c for c in req if c not in have])


def script_counts(text: str) -> dict[str, int]:
    """Count letters per Unicode script (first word of the character name)."""
    counts: Counter[str] = Counter()
    for ch in text:
        if not ch.isalpha():
            continue
        first = unicodedata.name(ch, "").split(" ", 1)[0]
        if first:
            counts["HAN" if first == "CJK" else first] += 1
    return dict(counts)


def _covered_scripts(languages: Sequence[str]) -> set[str]:
    covered: set[str] = set()
    for code in languages:
        if code.startswith("script/"):
            covered.update(_SCRIPT_MODELS.get(code.split("/", 1)[1], ()))
            continue
        covered.update(script for script, codes in SCRIPT_LANGUAGES.items() if code in codes)
    return covered


def script_warnings(text: str, languages: Sequence[str]) -> list[str]:
    """Warn for each non-Latin script in *text* that no configured language reads."""
    counts = script_counts(text)
    total = sum(counts.values())
    if total == 0:
        return []
    covered = _covered_scripts(languages)
    warnings: list[str] = []
    for script, count in sorted(counts.items()):
        if script not in SCRIPT_LANGUAGES or script in covered:
            continue
        share = count / total
        if count < _MIN_SCRIPT_LETTERS or share < _MIN_SCRIPT_SHARE:
            continue
        warnings.append(
            f"{count} letters ({share:.0%}) are {script}, but ocr_languages has none of: "
            f"{', '.join(SCRIPT_LANGUAGES[script])}"
        )
    return warnings
