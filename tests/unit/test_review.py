"""Tests for Collaborative Review & Annotation Layer (Issue #122)."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

from dd_agents.models.review import Annotation, ReviewAssignment, ReviewProgress, ReviewState
from dd_agents.review.manager import ReviewManager, _finding_id


def _make_finding(title: str = "Test Finding", customer: str = "acme", agent: str = "legal") -> dict[str, Any]:
    return {"title": title, "_customer": customer, "agent": agent, "severity": "P1"}


class TestReviewModels:
    """Test review data models."""

    def test_annotation_defaults(self) -> None:
        ann = Annotation(id="a1", finding_id="f1", reviewer="alice", timestamp="2026-01-01T00:00:00Z")
        assert ann.status == "pending"
        assert ann.severity_override is None
        assert ann.comment == ""

    def test_review_assignment_defaults(self) -> None:
        asgn = ReviewAssignment(id="r1", reviewer="bob", assigned_at="2026-01-01T00:00:00Z")
        assert asgn.signed_off is False
        assert asgn.signed_off_at is None

    def test_review_progress_defaults(self) -> None:
        prog = ReviewProgress()
        assert prog.total_findings == 0
        assert prog.pct_complete == 0.0

    def test_review_state_defaults(self) -> None:
        state = ReviewState()
        assert state.annotations == []
        assert state.assignments == []


class TestFindingId:
    """Test finding ID generation."""

    def test_deterministic(self) -> None:
        f = _make_finding()
        assert _finding_id(f) == _finding_id(f)

    def test_different_findings(self) -> None:
        f1 = _make_finding(title="Finding A")
        f2 = _make_finding(title="Finding B")
        assert _finding_id(f1) != _finding_id(f2)

    def test_different_customers(self) -> None:
        f1 = _make_finding(customer="acme")
        f2 = _make_finding(customer="beta")
        assert _finding_id(f1) != _finding_id(f2)


class TestReviewManager:
    """Test review manager CRUD operations."""

    @pytest.fixture()
    def manager(self, tmp_path: Path) -> ReviewManager:
        return ReviewManager(tmp_path)

    def test_empty_state(self, manager: ReviewManager) -> None:
        assert manager.get_annotations() == []
        assert manager.get_assignments() == []

    def test_add_annotation(self, manager: ReviewManager) -> None:
        finding = _make_finding()
        ann = manager.add_annotation(finding, reviewer="alice", comment="Looks correct", status="reviewed")
        assert ann.reviewer == "alice"
        assert ann.status == "reviewed"
        assert ann.comment == "Looks correct"
        assert ann.finding_id == _finding_id(finding)

    def test_add_annotation_with_severity_override(self, manager: ReviewManager) -> None:
        finding = _make_finding()
        ann = manager.add_annotation(
            finding, reviewer="bob", severity_override="P0", severity_justification="More critical than assessed"
        )
        assert ann.severity_override == "P0"
        assert ann.severity_justification == "More critical than assessed"

    def test_get_annotations_by_finding(self, manager: ReviewManager) -> None:
        f1 = _make_finding(title="Finding A")
        f2 = _make_finding(title="Finding B")
        manager.add_annotation(f1, reviewer="alice", status="reviewed")
        manager.add_annotation(f2, reviewer="bob", status="disputed")
        fid1 = _finding_id(f1)
        anns = manager.get_annotations(finding_id=fid1)
        assert len(anns) == 1
        assert anns[0].reviewer == "alice"

    def test_update_annotation_status(self, manager: ReviewManager) -> None:
        ann = manager.add_annotation(_make_finding(), reviewer="alice", status="reviewed")
        updated = manager.update_annotation_status(ann.id, "accepted")
        assert updated is not None
        assert updated.status == "accepted"

    def test_update_nonexistent_annotation(self, manager: ReviewManager) -> None:
        assert manager.update_annotation_status("nonexistent", "accepted") is None

    def test_assign_reviewer(self, manager: ReviewManager) -> None:
        asgn = manager.assign_reviewer("alice", section="legal")
        assert asgn.reviewer == "alice"
        assert asgn.section == "legal"
        assert asgn.signed_off is False

    def test_assign_reviewer_to_customer(self, manager: ReviewManager) -> None:
        asgn = manager.assign_reviewer("bob", customer_safe_name="acme")
        assert asgn.customer_safe_name == "acme"

    def test_sign_off(self, manager: ReviewManager) -> None:
        asgn = manager.assign_reviewer("alice", section="finance")
        signed = manager.sign_off(asgn.id)
        assert signed is not None
        assert signed.signed_off is True
        assert signed.signed_off_at is not None

    def test_sign_off_nonexistent(self, manager: ReviewManager) -> None:
        assert manager.sign_off("nonexistent") is None

    def test_get_assignments_by_reviewer(self, manager: ReviewManager) -> None:
        manager.assign_reviewer("alice", section="legal")
        manager.assign_reviewer("bob", section="finance")
        manager.assign_reviewer("alice", section="commercial")
        alice_assignments = manager.get_assignments(reviewer="alice")
        assert len(alice_assignments) == 2

    def test_state_persists(self, tmp_path: Path) -> None:
        mgr1 = ReviewManager(tmp_path)
        mgr1.add_annotation(_make_finding(), reviewer="alice", status="reviewed")
        mgr2 = ReviewManager(tmp_path)
        assert len(mgr2.get_annotations()) == 1

    def test_corrupt_state_recovery(self, tmp_path: Path) -> None:
        state_path = tmp_path / "review_state.json"
        state_path.write_text("not json", encoding="utf-8")
        mgr = ReviewManager(tmp_path)
        assert mgr.get_annotations() == []


class TestReviewProgress:
    """Test review progress computation."""

    @pytest.fixture()
    def manager_with_annotations(self, tmp_path: Path) -> ReviewManager:
        mgr = ReviewManager(tmp_path)
        findings = [_make_finding(title=f"Finding {i}", customer="acme" if i < 3 else "beta") for i in range(5)]
        mgr.add_annotation(findings[0], reviewer="alice", status="reviewed")
        mgr.add_annotation(findings[1], reviewer="alice", status="accepted")
        mgr.add_annotation(findings[2], reviewer="bob", status="disputed")
        return mgr

    def test_progress_counts(self, manager_with_annotations: ReviewManager) -> None:
        progress = manager_with_annotations.compute_progress(total_findings=5)
        assert progress.total_findings == 5
        assert progress.reviewed == 3  # reviewed + accepted + disputed
        assert progress.pending == 2
        assert progress.disputed == 1
        assert progress.accepted == 1

    def test_progress_pct(self, manager_with_annotations: ReviewManager) -> None:
        progress = manager_with_annotations.compute_progress(total_findings=5)
        assert progress.pct_complete == pytest.approx(60.0)

    def test_progress_by_reviewer(self, manager_with_annotations: ReviewManager) -> None:
        progress = manager_with_annotations.compute_progress(total_findings=5)
        assert "alice" in progress.by_reviewer
        assert "bob" in progress.by_reviewer

    def test_progress_zero_findings(self, tmp_path: Path) -> None:
        mgr = ReviewManager(tmp_path)
        progress = mgr.compute_progress(total_findings=0)
        assert progress.pct_complete == 0.0


class TestExportAnnotations:
    """Test annotation export."""

    def test_export_json(self, tmp_path: Path) -> None:
        mgr = ReviewManager(tmp_path)
        mgr.add_annotation(_make_finding(), reviewer="alice", status="reviewed")
        exported = mgr.export_annotations(format="json")
        assert '"reviewer"' in exported
        assert '"alice"' in exported

    def test_export_csv(self, tmp_path: Path) -> None:
        mgr = ReviewManager(tmp_path)
        mgr.add_annotation(_make_finding(), reviewer="alice", status="reviewed")
        exported = mgr.export_annotations(format="csv")
        assert "finding_id,reviewer,status" in exported
        assert "alice" in exported
