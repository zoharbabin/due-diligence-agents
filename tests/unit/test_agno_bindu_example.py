"""Keyless CI guard for the agno-bindu example's deterministic report tools.

The example (``examples/agno-bindu/``) serves a completed dd-agents report as an
A2A agent. Its three tools — ``report_overview`` / ``list_findings`` /
``get_finding`` — are pure, deterministic Python over the upstream
``dd_agents.query`` finding index: no agno, no Bindu, no API key. These tests
import ONLY ``report_tools`` (never ``agent.py``, which needs agno), so they run
on the normal CI matrix with zero extra dependencies.

They are a tripwire in two directions:
  1. The example stays wired to the real ``FindingIndexer`` contract — if the
     pipeline's finding/citation shape drifts, these fail instead of the example
     silently degrading.
  2. The bundled default report (``docs/marketing/sample-report-atlas/``) stays
     indexable — a docs refactor that moves/renames it fails CI here rather than
     leaving the example pointing at nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = REPO_ROOT / "examples" / "agno-bindu"

# The example modules import each other by bare name (they run from their own
# dir); make that importable here without installing the example.
sys.path.insert(0, str(EXAMPLE_DIR))

report_tools = pytest.importorskip("report_tools")  # dd_agents only; no agno/bindu


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Iterator[None]:
    """Reset the per-path index cache so DD_REPORT_DIR overrides take effect."""
    report_tools._index_for.cache_clear()
    yield
    report_tools._index_for.cache_clear()


def test_default_report_dir_exists() -> None:
    """The bundled default report the example points at must exist."""
    assert report_tools.DEFAULT_REPORT_DIR.is_dir(), report_tools.DEFAULT_REPORT_DIR


def test_overview_indexes_bundled_report() -> None:
    """report_overview returns the real Atlas counts (catches indexer/doc drift)."""
    data = json.loads(report_tools.report_overview())
    assert "error" not in data, data
    assert data["total_findings"] > 0
    # Severity buckets present and summing to the total.
    sev = data["severity_counts"]
    assert sum(sev.values()) == data["total_findings"]
    assert "P0" in sev  # the Atlas hero is a P0 change-of-control risk
    # Domain breakdown is populated across specialist domains.
    assert len(data["domain_counts"]) >= 1


def test_list_findings_filters_and_caps() -> None:
    """list_findings filters by severity and respects the limit cap."""
    all_rows = json.loads(report_tools.list_findings())
    assert all_rows["match_count"] > 0

    p0 = json.loads(report_tools.list_findings(severity="p0"))  # case-insensitive
    assert p0["match_count"] >= 1
    assert all(r["severity"] == "P0" for r in p0["findings"])

    capped = json.loads(report_tools.list_findings(limit=1))
    assert capped["returned"] == 1
    assert len(capped["findings"]) == 1


def test_get_finding_roundtrip_and_untrusted_fencing() -> None:
    """A row id round-trips through get_finding; verbatim text is fenced."""
    rows = json.loads(report_tools.list_findings(severity="P0", limit=1))
    fid = rows["findings"][0]["id"]
    detail = json.loads(report_tools.get_finding(fid))
    assert detail["id"] == fid
    assert detail["severity"] == "P0"
    # Description and any quotes are fenced as untrusted document text.
    assert detail["description"].startswith(report_tools.UNTRUSTED_OPEN)
    for c in detail["citations"]:
        assert c["exact_quote"] == "" or c["exact_quote"].startswith(report_tools.UNTRUSTED_OPEN)


def test_get_finding_unknown_id_errors_cleanly() -> None:
    """An unknown id returns a structured error, not an exception."""
    out = json.loads(report_tools.get_finding("does-not-exist"))
    assert "error" in out
    assert "hint" in out


def test_missing_report_dir_returns_in_band_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pointing at an empty dir yields a friendly in-band error, never a crash."""
    monkeypatch.setenv("DD_REPORT_DIR", str(tmp_path))
    out = json.loads(report_tools.report_overview())
    assert "error" in out
    assert "DD_REPORT_DIR" in out["error"]


def test_index_reindexes_when_report_dir_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The index is keyed on the resolved path, not cached globally (idempotency)."""
    # Default report → findings present.
    assert report_tools._index().total_findings > 0
    # Switch to an empty dir → re-indexes to zero (no stale cache).
    monkeypatch.setenv("DD_REPORT_DIR", str(tmp_path))
    assert report_tools._index().total_findings == 0
