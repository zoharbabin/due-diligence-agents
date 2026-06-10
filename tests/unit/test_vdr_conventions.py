"""Tests for VDR folder-convention detection (Issue #193)."""

from __future__ import annotations

from dd_agents.precedence.vdr_conventions import (
    SPECIALIST_DOMAINS,
    classify_folder,
    detect_convention,
    is_numbered_folder,
)


class TestNumberedFolder:
    def test_recognizes_numbered(self) -> None:
        assert is_numbered_folder("3.0 Material Contracts")
        assert is_numbered_folder("04 - Financial")
        assert is_numbered_folder("5) HR")
        assert is_numbered_folder("2.1.3 Sub Item")

    def test_rejects_unnumbered(self) -> None:
        assert not is_numbered_folder("Acme Corp")
        assert not is_numbered_folder("Material Contracts")
        assert not is_numbered_folder("")


class TestClassifyFolder:
    def test_maps_standard_categories_to_domains(self) -> None:
        cases = {
            "3.0 Material Contracts": "commercial",
            "4.0 Financial Information": "finance",
            "5.0 HR & Benefits": "hr",
            "6.0 Tax": "tax",
            "7.0 Intellectual Property": "producttech",
            "8.0 Data Privacy & Security": "cybersecurity",
            "9.0 Regulatory & Compliance": "regulatory",
            "2.0 Corporate & Organization": "legal",
        }
        for folder, domain in cases.items():
            cat = classify_folder(folder)
            assert cat is not None, folder
            assert cat.domain == domain, f"{folder} -> {cat.domain} (expected {domain})"

    def test_financial_information_not_misclassified_as_corporate(self) -> None:
        # Regression: "formation" substring of "Information" must not match Corporate.
        cat = classify_folder("4.0 Financial Information")
        assert cat is not None and cat.domain == "finance"

    def test_unrecognized_returns_none(self) -> None:
        assert classify_folder("3.0 Zorblax Widgets") is None

    def test_override_forces_domain(self) -> None:
        cat = classify_folder("9.9 Special Stuff", overrides={"special stuff": "legal"})
        assert cat is not None and cat.domain == "legal"

    def test_all_mapped_domains_are_valid_specialists(self) -> None:
        for folder in ["1 Corporate", "2 Financial", "3 Material Contracts", "4 Tax", "5 HR", "6 ESG"]:
            cat = classify_folder(folder)
            if cat is not None and cat.domain is not None:
                assert cat.domain in SPECIALIST_DOMAINS


class TestDetectConvention:
    def test_numbered_vdr_export_detected(self) -> None:
        folders = [
            "1.0 Corporate",
            "2.0 Financial Information",
            "3.0 Material Contracts",
            "4.0 HR & Benefits",
        ]
        d = detect_convention(folders)
        assert d.is_vdr
        assert d.numbered_folders == 4
        assert d.matched_categories == 4
        assert "Recognized numbered VDR layout" in d.describe()

    def test_generic_room_not_flagged(self) -> None:
        # Parity: a plain subject-folder room must NOT be treated as VDR.
        d = detect_convention(["Acme Corp", "Beta Inc", "Gamma LLC"])
        assert not d.is_vdr
        assert d.categories == {}
        assert "No VDR numbering convention" in d.describe()

    def test_empty_room(self) -> None:
        d = detect_convention([])
        assert not d.is_vdr and d.total_top_level == 0

    def test_partial_numbering_below_threshold(self) -> None:
        # One numbered folder among many generic ones is not a VDR export.
        d = detect_convention(["Acme Corp", "Beta Inc", "3.0 Material Contracts"])
        assert not d.is_vdr
        # But the category map still includes the one that matched (soft signal).
        assert any(c.domain == "commercial" for c in d.categories.values())


class TestSpecialistDomainsParity:
    def test_matches_registry(self) -> None:
        # Guard: the literal SPECIALIST_DOMAINS must equal the live registry,
        # so the convention table can never route to a non-existent agent.
        from dd_agents.agents.registry import AgentRegistry

        AgentRegistry.discover_entry_points()
        assert set(SPECIALIST_DOMAINS) == set(AgentRegistry.all_specialist_names())
