"""Path constants, tier names, and shared configuration values."""

from __future__ import annotations

from dd_agents.extraction._constants import IMAGE_EXTENSIONS

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
AGENT_JUDGE = "judge"
AGENT_ACQUIRER_INTELLIGENCE = "acquirer_intelligence"

ALL_SPECIALIST_AGENTS: list[str] = [
    AGENT_LEGAL,
    AGENT_FINANCE,
    AGENT_COMMERCIAL,
    AGENT_PRODUCTTECH,
]

# ---------------------------------------------------------------------------
# Severity labels
# ---------------------------------------------------------------------------

SEVERITY_P0 = "P0"
SEVERITY_P1 = "P1"
SEVERITY_P2 = "P2"
SEVERITY_P3 = "P3"

SEVERITY_ORDER: dict[str, int] = {
    SEVERITY_P0: 0,
    SEVERITY_P1: 1,
    SEVERITY_P2: 2,
    SEVERITY_P3: 3,
}

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

# All extensions the inventory scanner discovers.  Image extensions are
# imported from ``extraction._constants`` to avoid maintaining two copies.
SUPPORTED_EXTENSIONS: set[str] = set(IMAGE_EXTENSIONS) | _OFFICE_EXTENSIONS | _INVENTORY_PLAINTEXT

# ---------------------------------------------------------------------------
# Batch naming (1-based per spec)
# ---------------------------------------------------------------------------

BATCH_START_INDEX = 1

# ---------------------------------------------------------------------------
# Entity resolution thresholds
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD_LONG = 88  # Names > 8 chars after preprocessing
FUZZY_THRESHOLD_MEDIUM = 95  # Names 5-8 chars after preprocessing
SHORT_NAME_MAX_LEN = 5  # Names <= 5 chars: never fuzzy-matched
TFIDF_THRESHOLD = 0.80  # Cosine similarity threshold for TF-IDF
