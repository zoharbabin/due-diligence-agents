"""VDR folder-convention detection (Issue #193).

Professional M&A data rooms are usually exported from a VDR (Intralinks,
Datasite, Firmex, Ansarada) and follow **numbered folder conventions** —
``3.0 Material Contracts``, ``4.0 Financial Information``, ``5.0 HR & Benefits``,
etc. dd-agents understands a generic ``group/subject/file`` hierarchy and folder
trust tiers (see ``folder_priority.py``) but not VDR category numbering — so a
folder that clearly maps to a domain isn't used as a routing hint.

This module adds **best-effort, data-driven** convention recognition:

- A small, overridable table of ``regex → (domain, category)`` covering the
  common numbered index structures.
- :func:`classify_folder` — map one folder name to its VDR domain/category.
- :func:`detect_convention` — given the data room's folder names, decide whether
  it looks like a numbered VDR export and how many standard categories matched.

Pure + dependency-free. It is a **soft signal**: a non-VDR data room produces
no matches and behaves exactly as before (parity). Domains use the canonical
specialist names (``legal``, ``finance``, ``commercial``, ``producttech``,
``cybersecurity``, ``hr``, ``tax``, ``regulatory``, ``esg``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical specialist domain keys (mirror AgentRegistry.all_specialist_names()).
# Kept as a literal tuple so this module stays import-light + pure; a unit test
# asserts it matches the registry so the two never drift.
SPECIALIST_DOMAINS: tuple[str, ...] = (
    "legal",
    "finance",
    "commercial",
    "producttech",
    "cybersecurity",
    "hr",
    "tax",
    "regulatory",
    "esg",
)


@dataclass(frozen=True)
class VdrCategory:
    """A recognized VDR folder category.

    ``domain`` is the specialist routing hint (or ``None`` for corporate/admin
    categories that don't map to one specialist). ``category`` is the
    human-readable normalized label.
    """

    category: str
    domain: str | None


# Convention table: (compiled keyword regex) -> VdrCategory. Matched against the
# folder name with its leading numeric index stripped (e.g. "3.0 Material
# Contracts" -> "material contracts"). Order matters only for readability; all
# patterns are tried and the first match wins per folder. DATA, not logic —
# extend or override rather than branching in code.
_CONVENTION_TABLE: tuple[tuple[str, VdrCategory], ...] = (
    (
        r"corporate|organization|\bformation\b|charter|bylaw|incorporat|cap table|capitaliz",
        VdrCategory("Corporate & Organization", "legal"),
    ),
    (
        r"material contract|customer contract|commercial agreement|sales|revenue contract|order form|\bmsa\b|\bsow\b",
        VdrCategory("Material Contracts", "commercial"),
    ),
    (
        r"financial|finance|accounting|audit|management account|p&l|balance sheet|projection",
        VdrCategory("Financial Information", "finance"),
    ),
    (r"\btax\b|taxation|transfer pricing|vat\b|sales tax", VdrCategory("Tax", "tax")),
    (
        r"\bhr\b|human resource|employ|benefit|payroll|compensation|personnel|headcount",
        VdrCategory("HR & Benefits", "hr"),
    ),
    (
        r"intellectual property|\bip\b|patent|trademark|copyright|technology|software|source code|product|engineering",
        VdrCategory("IP & Technology", "producttech"),
    ),
    (
        r"data privacy|gdpr|ccpa|security|cyber|infosec|information security|breach",
        VdrCategory("Privacy & Security", "cybersecurity"),
    ),
    (
        r"regulatory|compliance|license|permit|antitrust|competition|sanctions|aml\b|kyc\b",
        VdrCategory("Regulatory & Compliance", "regulatory"),
    ),
    (r"litigation|dispute|legal|claims", VdrCategory("Legal & Litigation", "legal")),
    (r"environment|sustainab|\besg\b|social|governance|climate|carbon", VdrCategory("ESG", "esg")),
    (r"insurance", VdrCategory("Insurance", "finance")),
    (r"real estate|propert|lease|facilit", VdrCategory("Real Estate & Facilities", "legal")),
    # Admin/index categories that don't route to a specialist.
    (r"index|administration|admin\b|q&a|q and a|general|miscellaneous|process", VdrCategory("Administrative", None)),
)

_COMPILED_TABLE: tuple[tuple[re.Pattern[str], VdrCategory], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), cat) for pat, cat in _CONVENTION_TABLE
)

# A leading numbered index, e.g. "3.0 ", "04 - ", "5) ", "2.1.3 ". Stripped
# before keyword matching so the index doesn't interfere.
_NUMBER_PREFIX_RE = re.compile(r"^\s*\d+(\.\d+)*\s*[-).]?\s*")
# Does a folder name *start* with a numeric index? (the VDR-export signal)
_IS_NUMBERED_RE = re.compile(r"^\s*\d+(\.\d+)*\s*[-).]?\s+\S")


def _strip_index(folder_name: str) -> str:
    """Remove a leading numeric index from a folder name (lowercased)."""
    return _NUMBER_PREFIX_RE.sub("", folder_name).strip().lower()


def is_numbered_folder(folder_name: str) -> bool:
    """True if *folder_name* starts with a VDR-style numeric index."""
    return bool(_IS_NUMBERED_RE.match(folder_name))


def classify_folder(folder_name: str, overrides: dict[str, str] | None = None) -> VdrCategory | None:
    """Map one folder name to a :class:`VdrCategory`, or None if unrecognized.

    *overrides* maps a folder substring (case-insensitive) to a specialist
    domain key, letting a deal config force a routing hint the table misses.
    """
    bare = _strip_index(folder_name)
    if not bare:
        return None

    if overrides:
        for needle, domain in overrides.items():
            if needle.strip().lower() in bare:
                return VdrCategory(category=folder_name.strip(), domain=domain or None)

    for pattern, category in _COMPILED_TABLE:
        if pattern.search(bare):
            return category
    return None


@dataclass(frozen=True)
class ConventionDetection:
    """Result of scanning a data room's folders for a VDR convention."""

    is_vdr: bool
    numbered_folders: int
    matched_categories: int
    total_top_level: int
    categories: dict[str, VdrCategory] = field(default_factory=dict)

    def describe(self) -> str:
        """One-line, human-readable summary for `assess` output."""
        if not self.is_vdr:
            return "No VDR numbering convention detected (generic hierarchy)."
        return (
            f"Recognized numbered VDR layout: {self.matched_categories}/{self.total_top_level} "
            f"top-level folders mapped to a domain ({self.numbered_folders} numbered)."
        )


def detect_convention(
    top_level_folders: list[str],
    overrides: dict[str, str] | None = None,
    *,
    min_numbered_ratio: float = 0.5,
) -> ConventionDetection:
    """Decide whether *top_level_folders* look like a numbered VDR export.

    A data room is treated as VDR-style when at least *min_numbered_ratio* of
    its top-level folders start with a numeric index. Returns the per-folder
    category map regardless, so callers can use category hints even on a
    borderline layout. Empty / non-numbered rooms yield ``is_vdr=False`` and an
    empty map (parity — generic rooms are unaffected).
    """
    folders = [f for f in top_level_folders if f and f.strip()]
    total = len(folders)
    if total == 0:
        return ConventionDetection(False, 0, 0, 0)

    numbered = sum(1 for f in folders if is_numbered_folder(f))
    categories: dict[str, VdrCategory] = {}
    for f in folders:
        cat = classify_folder(f, overrides)
        if cat is not None:
            categories[f] = cat

    is_vdr = (numbered / total) >= min_numbered_ratio and numbered >= 2
    return ConventionDetection(
        is_vdr=is_vdr,
        numbered_folders=numbered,
        matched_categories=len(categories),
        total_top_level=total,
        categories=categories,
    )
