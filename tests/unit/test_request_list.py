"""Tests for request-list reconciliation (Issue #192)."""

from __future__ import annotations

from dd_agents.inventory.request_list import (
    reconcile,
    seed_from_vdr_categories,
    to_gaps,
)
from dd_agents.models.config import RequestedDocument
from dd_agents.models.enums import DetectionMethod, GapType, Severity


def _items() -> list[RequestedDocument]:
    return [
        RequestedDocument(category="Signed MSA", keywords=["msa", "signed"], required=True),
        RequestedDocument(category="Cap table", required=True),
        RequestedDocument(category="Board minutes", required=False),
    ]


class TestReconcile:
    def test_received_missing_unexpected(self) -> None:
        files = ["Acme/msa_signed_2024.pdf", "Acme/cap_table_summary.xlsx", "Acme/random_memo.pdf"]
        r = reconcile(_items(), files)
        received = {s.category for s in r.received}
        assert received == {"Signed MSA", "Cap table"}
        assert {s.category for s in r.missing} == {"Board minutes"}
        assert r.unexpected_files == ["Acme/random_memo.pdf"]

    def test_required_missing_only(self) -> None:
        # Cap table absent (required); Board minutes absent (optional).
        files = ["Acme/msa_signed.pdf"]
        r = reconcile(_items(), files)
        assert {s.category for s in r.missing_required} == {"Cap table"}

    def test_keyword_and_match(self) -> None:
        # "signed" alone must NOT satisfy "Signed MSA" (needs both msa + signed).
        files = ["Acme/signed_nda.pdf"]
        r = reconcile([RequestedDocument(category="Signed MSA", keywords=["msa", "signed"])], files)
        assert r.missing and not r.received

    def test_subject_scoping(self) -> None:
        items = [RequestedDocument(category="Cap table", subject="acme", keywords=["cap", "table"])]
        files = ["beta/cap_table.xlsx", "acme/cap_table.xlsx"]
        r = reconcile(items, files, subject_of={"beta/cap_table.xlsx": "beta", "acme/cap_table.xlsx": "acme"})
        assert r.received and r.received[0].matched_files == ["acme/cap_table.xlsx"]

    def test_empty_items(self) -> None:
        r = reconcile([], ["a.pdf"])
        assert r.items == [] and r.unexpected_files == ["a.pdf"]


class TestToGaps:
    def test_missing_required_becomes_gap(self) -> None:
        files = ["Acme/msa_signed.pdf"]
        r = reconcile(_items(), files)
        gaps = to_gaps(r, run_id="run_test")
        assert len(gaps) == 1
        g = gaps[0]
        assert g.missing_item == "Cap table"
        assert g.gap_type == GapType.MISSING_DOC
        assert g.detection_method == DetectionMethod.FILE_INVENTORY
        assert g.priority == Severity.P2
        assert g.run_id == "run_test"

    def test_optional_missing_is_not_a_gap(self) -> None:
        # All required present; only the optional "Board minutes" missing.
        files = ["Acme/msa_signed.pdf", "Acme/cap_table.xlsx"]
        r = reconcile(_items(), files)
        assert to_gaps(r) == []


class TestSeedFromVdr:
    def test_seeds_required_items_dedup(self) -> None:
        cats = {"3.0 Material Contracts": "Material Contracts", "9.0 More Contracts": "Material Contracts"}
        items = seed_from_vdr_categories(cats)
        assert [i.category for i in items] == ["Material Contracts"]
        assert all(i.required for i in items)
