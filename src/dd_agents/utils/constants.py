"""Path constants, tier names, and shared configuration values."""

from __future__ import annotations

import os  # noqa: TCH003 - used at module level for env var reads
from typing import TYPE_CHECKING

from dd_agents.extraction._constants import IMAGE_EXTENSIONS, MEDIA_EXTENSIONS

if TYPE_CHECKING:
    from dd_agents.models.config import DealConfig

# ---------------------------------------------------------------------------
# Directory structure constants
# ---------------------------------------------------------------------------

DD_DIR = "_dd"
SKILL_NAME = "forensic-dd"
SKILL_DIR = f"{DD_DIR}/{SKILL_NAME}"
INDEX_DIR = f"{SKILL_DIR}/index"
TEXT_DIR = f"{INDEX_DIR}/text"
INVENTORY_DIR = f"{SKILL_DIR}/inventory"
FINDINGS_DIR = "findings"
JUDGE_DIR = "judge"
REPORT_DIR = "report"
AUDIT_DIR = "audit"
KNOWLEDGE_DIR = f"{SKILL_DIR}/knowledge"

# ---------------------------------------------------------------------------
# Persistence tier names
# ---------------------------------------------------------------------------

TIER_PERMANENT = "PERMANENT"
TIER_VERSIONED = "VERSIONED"
TIER_FRESH = "FRESH"

# ---------------------------------------------------------------------------
# Agent names (must match AgentName enum)
# ---------------------------------------------------------------------------

AGENT_LEGAL = "legal"
AGENT_FINANCE = "finance"
AGENT_COMMERCIAL = "commercial"
AGENT_PRODUCTTECH = "producttech"
AGENT_CYBERSECURITY = "cybersecurity"
AGENT_JUDGE = "judge"
AGENT_ACQUIRER_INTELLIGENCE = "acquirer_intelligence"

ALL_SPECIALIST_AGENTS: list[str] = [
    AGENT_LEGAL,
    AGENT_FINANCE,
    AGENT_COMMERCIAL,
    AGENT_PRODUCTTECH,
    AGENT_CYBERSECURITY,
]


def get_active_agents(deal_config: DealConfig | None = None) -> list[str]:
    """Return the list of active specialist agents, respecting config disablement.

    Delegates to :class:`~dd_agents.agents.registry.AgentRegistry` so that
    callers don't need to import the registry directly.
    """
    from dd_agents.agents.registry import AgentRegistry

    return AgentRegistry.resolve_active(deal_config)


# ---------------------------------------------------------------------------
# Severity labels
# ---------------------------------------------------------------------------

SEVERITY_P0 = "P0"
SEVERITY_P1 = "P1"
SEVERITY_P2 = "P2"
SEVERITY_P3 = "P3"

ALL_SEVERITIES: tuple[str, ...] = (SEVERITY_P0, SEVERITY_P1, SEVERITY_P2, SEVERITY_P3)

SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_P0: 0,
    SEVERITY_P1: 1,
    SEVERITY_P2: 2,
    SEVERITY_P3: 3,
}


def _sev_count_init() -> dict[str, int]:
    """Return a fresh ``{P0: 0, P1: 0, P2: 0, P3: 0}`` dict."""
    return {s: 0 for s in ALL_SEVERITIES}


# ---------------------------------------------------------------------------
# File discovery exclude patterns
# ---------------------------------------------------------------------------

EXCLUDE_PATTERNS: list[str] = [
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".git",
    ".svn",
    "~$*",  # Office temp files
    "~lock.*",  # LibreOffice lock files
    "dd_output",  # claude-agent-sdk default output directory
    ".python-version",  # pyenv version file
    ".node-version",  # Node.js version file
    ".ruby-version",  # Ruby version file
    ".tool-versions",  # asdf version manager
]

# Office/document formats unique to inventory scanning (not in extraction sets).
_OFFICE_EXTENSIONS: set[str] = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".pptx",
    ".ppt",
    ".rtf",
    ".html",
    ".htm",
}

# Plaintext subset recognised by inventory (extraction PLAINTEXT_EXTENSIONS
# includes additional config formats like .yaml, .ini, .cfg that are not
# expected in data rooms).
_INVENTORY_PLAINTEXT: set[str] = {".txt", ".csv", ".md", ".json", ".xml"}

# All extensions the inventory scanner discovers.  Image and media extensions
# are imported from ``extraction._constants`` to avoid maintaining two copies.
SUPPORTED_EXTENSIONS: set[str] = (
    set(IMAGE_EXTENSIONS) | set(MEDIA_EXTENSIONS) | _OFFICE_EXTENSIONS | _INVENTORY_PLAINTEXT
)

# ---------------------------------------------------------------------------
# Well-known filenames (used by inventory, validation, and reporting)
# ---------------------------------------------------------------------------

COVERAGE_MANIFEST_JSON = "coverage_manifest.json"
NUMERICAL_MANIFEST_JSON = "numerical_manifest.json"
QUALITY_SCORES_JSON = "quality_scores.json"
FILES_TXT = "files.txt"
SUBJECTS_CSV = "subjects.csv"

# ---------------------------------------------------------------------------
# Batch naming (1-based per spec)
# ---------------------------------------------------------------------------

BATCH_START_INDEX = 1

# ---------------------------------------------------------------------------
# Entity resolution thresholds
# ---------------------------------------------------------------------------

# Override via DD_FUZZY_THRESHOLD_LONG, DD_FUZZY_THRESHOLD_MEDIUM,
# DD_SHORT_NAME_MAX_LEN, DD_TFIDF_THRESHOLD env vars.
FUZZY_THRESHOLD_LONG = int(os.getenv("DD_FUZZY_THRESHOLD_LONG", "88"))  # Names > 8 chars
FUZZY_THRESHOLD_MEDIUM = int(os.getenv("DD_FUZZY_THRESHOLD_MEDIUM", "95"))  # Names 5-8 chars
SHORT_NAME_MAX_LEN = int(os.getenv("DD_SHORT_NAME_MAX_LEN", "5"))  # Never fuzzy-matched
TFIDF_THRESHOLD = float(os.getenv("DD_TFIDF_THRESHOLD", "0.80"))  # Cosine similarity for TF-IDF

# ---------------------------------------------------------------------------
# Non-subject JSON stems (used by merge and pre-merge validation)
# ---------------------------------------------------------------------------

NON_SUBJECT_STEMS: frozenset[str] = frozenset(
    {
        "coverage_manifest",
        "numerical_manifest",
        "report_diff",
        "quality_scores",
        "metadata",
    }
)

# ---------------------------------------------------------------------------
# Severity scoring weights (used for sorting and risk scoring)
# ---------------------------------------------------------------------------

# General-purpose sorting weight (higher = more severe).
SEVERITY_WEIGHTS: dict[str, float] = {
    SEVERITY_P0: 10.0,
    SEVERITY_P1: 5.0,
    SEVERITY_P2: 2.0,
    SEVERITY_P3: 1.0,
}

# Risk score weights used for composite scoring (e.g. domain risk, SaaS health).
SEVERITY_RISK_SCORE_WEIGHTS: dict[str, int] = {
    SEVERITY_P0: 25,
    SEVERITY_P1: 15,
    SEVERITY_P2: 8,
    SEVERITY_P3: 3,
}
