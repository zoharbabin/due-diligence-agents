"""Customer safe name convention and name preprocessing utilities."""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Unicode → ASCII transliteration
# ---------------------------------------------------------------------------

# Non-decomposable characters that NFKD cannot reduce to ASCII base + combining
# mark.  Covers the Latin-script letters most common in European company names.
_TRANSLITERATION: dict[int, str] = {
    ord("ø"): "o",
    ord("Ø"): "O",
    ord("æ"): "ae",
    ord("Æ"): "AE",
    ord("œ"): "oe",
    ord("Œ"): "OE",
    ord("ß"): "ss",
    ord("ð"): "d",
    ord("Ð"): "D",
    ord("þ"): "th",
    ord("Þ"): "Th",
    ord("ł"): "l",
    ord("Ł"): "L",
    ord("đ"): "d",
    ord("Đ"): "D",
}


def _transliterate_to_ascii(text: str) -> str:
    """Best-effort transliteration of Unicode text to ASCII.

    1. Explicit mapping for non-decomposable letters (ø→o, ß→ss, æ→ae, …).
    2. NFKD decomposition strips combining marks (ü→u, é→e, ñ→n, …)
       and resolves compatibility characters (full-width A→A, ﬁ→fi, …).
    3. Any remaining non-ASCII bytes are silently dropped.
    """
    text = text.translate(_TRANSLITERATION)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


# Legal suffixes to strip (case-insensitive, anchored to end of string)
LEGAL_SUFFIXES: list[str] = [
    r"\bInc\.?$",
    r"\bCorp\.?$",
    r"\bCorporation$",
    r"\bLLC$",
    r"\bLtd\.?$",
    r"\bL\.?P\.?$",
    r"\bGmbH$",
    r"\bS\.?A\.?$",
    r"\bPty\.?$",
    r"\bULC$",
    r"\bLP$",
    r"\bLimited$",
    r"\bCompany$",
    r"\bCo\.?$",
    r"\bPLC$",
    r"\bAG$",
    r"\bN\.?V\.?$",
    r"\bB\.?V\.?$",
    r"\bS\.?A\.?S\.?$",
]

_SUFFIX_PATTERN = re.compile(
    r",?\s*(?:" + "|".join(LEGAL_SUFFIXES) + r")\s*$",
    re.IGNORECASE,
)


def _strip_legal_suffixes(name: str) -> str:
    """Remove legal suffixes iteratively (handles stacked suffixes)."""
    for _ in range(3):
        cleaned = _SUFFIX_PATTERN.sub("", name).strip()
        if cleaned == name:
            break
        name = cleaned
    return name


def preprocess_name(name: str) -> str:
    """Normalize a company name for matching.

    Steps:
        1. Unicode NFKC normalization
        2. Lowercase
        3. Strip legal suffixes
        4. Replace special characters (& ' / , . -) with space
        5. Remove parenthesized text
        6. Collapse whitespace
        7. Strip leading/trailing whitespace

    Examples:
        >>> preprocess_name("Apex Digital Inc.")
        'apex digital'
        >>> preprocess_name("Global Analytics Group")
        'global analytics group'
        >>> preprocess_name("Alpine Systems, Inc.")
        'alpine systems'
    """
    name = _transliterate_to_ascii(name)
    name = name.lower()
    name = _strip_legal_suffixes(name)

    # Replace special characters with space
    for ch in "&'/,.":
        name = name.replace(ch, " ")

    # Remove parenthesized text
    name = re.sub(r"\([^)]*\)", " ", name)

    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return name


def customer_safe_name(name: str) -> str:
    """Convert a customer name to a filesystem-safe ASCII identifier.

    Steps:
        1. Transliterate Unicode to ASCII (ü→u, ø→o, ß→ss, …)
        2. Lowercase
        3. Strip legal suffixes
        4. Replace spaces and special chars (& ' / , . -) with _
        5. Remove parenthesized text
        6. Collapse consecutive underscores
        7. Strip leading/trailing underscores

    Raises:
        ValueError: If name is empty or becomes empty after processing.

    Examples:
        >>> customer_safe_name("Global Analytics Group")
        'global_analytics_group'
        >>> customer_safe_name("Alpine Systems, Inc.")
        'alpine_systems'
        >>> customer_safe_name("Müller GmbH")
        'muller'
    """
    if not name or not name.strip():
        raise ValueError("Customer name cannot be empty")

    name = _transliterate_to_ascii(name)
    name = name.lower()
    name = _strip_legal_suffixes(name)

    # Remove parenthesized text
    name = re.sub(r"\([^)]*\)", " ", name)

    # Replace special characters and spaces with underscore
    for ch in "&'/,.- ":
        name = name.replace(ch, "_")

    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name)

    # Strip leading/trailing underscores
    name = name.strip("_")

    if not name:
        raise ValueError("Customer name resolves to empty string after processing")

    return name
