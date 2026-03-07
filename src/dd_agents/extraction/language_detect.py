"""Lightweight language detection for extracted documents (Issue #144).

Uses stopword frequency analysis for the top 10 languages.
No external dependencies — relies on character frequency and
common stopword matching.
"""

from __future__ import annotations

# Minimum text length for reliable detection
_MIN_TEXT_LEN = 50

# Common stopwords per language (top 15 most frequent)
_STOPWORDS: dict[str, set[str]] = {
    "en": {"the", "and", "is", "in", "to", "of", "a", "for", "that", "it", "with", "on", "as", "by", "this"},
    "de": {"der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich", "des", "auf", "für", "ist", "im"},
    "fr": {"le", "la", "les", "de", "des", "un", "une", "et", "en", "du", "est", "que", "dans", "qui", "pour"},
    "es": {"de", "la", "el", "en", "los", "del", "las", "con", "una", "por", "que", "es", "se", "como", "para"},
    "pt": {"de", "da", "do", "em", "os", "das", "dos", "com", "uma", "por", "que", "se", "como", "para", "mais"},
    "it": {"di", "il", "la", "che", "non", "del", "della", "dei", "per", "con", "una", "sono", "gli", "anche", "nel"},
    "nl": {"de", "het", "van", "een", "en", "in", "is", "dat", "op", "te", "met", "voor", "zijn", "dit", "aan"},
    "ja": {"の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ", "ある", "い", "も"},
    "zh": {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也"},
    "ko": {"의", "에", "은", "는", "을", "를", "이", "가", "로", "와", "한", "다", "그", "것", "수"},
}

# Language display names for agent instructions
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
}


def detect_language(text: str) -> str:
    """Detect the primary language of *text*.

    Returns an ISO 639-1 code (e.g. ``"en"``, ``"de"``, ``"fr"``)
    or ``"unknown"`` if detection is unreliable.
    """
    if len(text) < _MIN_TEXT_LEN:
        return "unknown"

    # Use first 2000 chars for efficiency
    sample = text[:2000].lower()

    # CJK character detection (Japanese, Chinese, Korean)
    cjk_count = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
    hiragana_count = sum(1 for c in sample if "\u3040" <= c <= "\u309f")
    katakana_count = sum(1 for c in sample if "\u30a0" <= c <= "\u30ff")
    hangul_count = sum(1 for c in sample if "\uac00" <= c <= "\ud7af")

    total_chars = len(sample)
    if total_chars == 0:
        return "unknown"

    if hangul_count / total_chars > 0.1:
        return "ko"
    if (hiragana_count + katakana_count) / total_chars > 0.05:
        return "ja"
    if cjk_count / total_chars > 0.1:
        return "zh"

    # Stopword-based detection for Latin-script languages
    words = set(sample.split())
    best_lang = "unknown"
    best_score = 0

    for lang, stopwords in _STOPWORDS.items():
        if lang in ("ja", "zh", "ko"):
            continue  # Already handled above
        score = len(words & stopwords)
        if score > best_score:
            best_score = score
            best_lang = lang

    # Require minimum confidence (at least 3 stopwords matched)
    if best_score < 3:
        return "unknown"

    return best_lang
