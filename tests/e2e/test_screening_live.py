"""Live check that the real sanctions list downloads still parse (Issue #274).

Opt-in. Skipped unless ``DD_TEST_SCREENING_LIVE=1`` (CI has no business hitting
government servers on every run). To run it:

    DD_TEST_SCREENING_LIVE=1 pytest tests/e2e/test_screening_live.py -m screening_live -s

Checks structure only. It never prints entry names, only counts and dates.
The downloads go to a temp dir, never to ``~/.dd-agents``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from dd_agents.screening import store
from dd_agents.screening.sources import SOURCES

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.screening_live

skip_not_opted_in = pytest.mark.skipif(
    os.getenv("DD_TEST_SCREENING_LIVE", "").strip() != "1",
    reason="DD_TEST_SCREENING_LIVE=1 not set; skipping the live sanctions list download",
)

# Far below the real sizes (tens of thousands of entries). Catches an empty or cut-off file.
MIN_ENTRIES = {"ofac_sdn": 5000, "uk": 1000, "eu": 1000}


@skip_not_opted_in
@pytest.mark.timeout(600)
@pytest.mark.parametrize("source_id", list(SOURCES))
def test_real_list_downloads_and_parses(source_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DD_SCREENING_DIR", str(tmp_path))

    snapshot = store.update(source_id)

    assert snapshot.source == source_id
    assert snapshot.source_url == SOURCES[source_id].url
    assert len(snapshot.sha256) == 64
    assert snapshot.published, "the file should state its own publication date"
    assert len(snapshot.entries) >= MIN_ENTRIES[source_id]
    assert all(e.source == source_id and e.uid and e.name.strip() for e in snapshot.entries)
    assert len({e.uid for e in snapshot.entries}) == len(snapshot.entries), "uids should be unique"
    assert {e.kind for e in snapshot.entries} - {"unknown"}, "at least one entry should have a known kind"

    assert store.load_snapshot(source_id) == snapshot
    [row] = store.coverage([source_id])
    assert row.status == "screened"
    print(f"\n[screening_live] {source_id}: {len(snapshot.entries)} entries, published {snapshot.published}")
