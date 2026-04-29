"""Tests for the cross-domain dependency ontology (Issue #189)."""

from __future__ import annotations

from dd_agents.orchestrator.ontology import (
    DOMAIN_DEPENDENCIES,
    DomainDependency,
    describe_dependencies_for_chat,
    get_dependencies_for_domain,
    get_dependents_of_domain,
)


class TestDomainDependency:
    def test_frozen_dataclass(self) -> None:
        dep = DomainDependency(
            source_domain="finance",
            source_categories=("revenue_recognition",),
            target_domain="legal",
            target_categories=("enforceability",),
            relationship="requires_verification",
        )
        assert dep.source_domain == "finance"
        assert dep.bidirectional is False

    def test_all_dependencies_have_required_fields(self) -> None:
        for dep in DOMAIN_DEPENDENCIES:
            assert dep.source_domain, "source_domain must not be empty"
            assert dep.target_domain, "target_domain must not be empty"
            assert dep.source_categories, "source_categories must not be empty"
            assert dep.target_categories, "target_categories must not be empty"
            assert dep.relationship, "relationship must not be empty"

    def test_no_self_referencing_dependencies(self) -> None:
        for dep in DOMAIN_DEPENDENCIES:
            assert dep.source_domain != dep.target_domain, (
                f"Self-referencing dependency: {dep.source_domain} -> {dep.target_domain}"
            )

    def test_all_domains_are_lowercase(self) -> None:
        for dep in DOMAIN_DEPENDENCIES:
            assert dep.source_domain == dep.source_domain.lower()
            assert dep.target_domain == dep.target_domain.lower()

    def test_all_categories_are_lowercase(self) -> None:
        for dep in DOMAIN_DEPENDENCIES:
            for cat in dep.source_categories:
                assert cat == cat.lower(), f"Category not lowercase: {cat}"
            for cat in dep.target_categories:
                assert cat == cat.lower(), f"Category not lowercase: {cat}"

    def test_dependency_count(self) -> None:
        assert len(DOMAIN_DEPENDENCIES) >= 7

    def test_valid_relationships(self) -> None:
        valid = {"requires_verification", "quantifies", "technical_impact"}
        for dep in DOMAIN_DEPENDENCIES:
            assert dep.relationship in valid, f"Unknown relationship: {dep.relationship}"


class TestDependencyLookups:
    def test_get_dependencies_for_finance(self) -> None:
        deps = get_dependencies_for_domain("finance")
        assert len(deps) >= 2
        targets = {d.target_domain for d in deps}
        assert "legal" in targets
        assert "commercial" in targets

    def test_get_dependencies_for_legal(self) -> None:
        deps = get_dependencies_for_domain("legal")
        assert len(deps) >= 2
        targets = {d.target_domain for d in deps}
        assert "finance" in targets
        assert "producttech" in targets

    def test_get_dependencies_for_unknown_domain(self) -> None:
        deps = get_dependencies_for_domain("nonexistent")
        assert deps == []

    def test_get_dependents_of_legal(self) -> None:
        deps = get_dependents_of_domain("legal")
        assert len(deps) >= 2
        sources = {d.source_domain for d in deps}
        assert "producttech" in sources

    def test_get_dependents_of_finance(self) -> None:
        deps = get_dependents_of_domain("finance")
        assert len(deps) >= 2
        sources = {d.source_domain for d in deps}
        assert "legal" in sources
        assert "commercial" in sources

    def test_get_dependents_of_unknown_domain(self) -> None:
        deps = get_dependents_of_domain("nonexistent")
        assert deps == []


class TestChatDescription:
    def test_describe_returns_nonempty(self) -> None:
        text = describe_dependencies_for_chat()
        assert len(text) > 50

    def test_describe_contains_header(self) -> None:
        text = describe_dependencies_for_chat()
        assert "Cross-Domain Dependencies" in text

    def test_describe_mentions_domains(self) -> None:
        text = describe_dependencies_for_chat()
        assert "Finance" in text
        assert "Legal" in text

    def test_describe_deduplicates_pairs(self) -> None:
        text = describe_dependencies_for_chat()
        lines = [ln for ln in text.splitlines() if ln.startswith("- ")]
        pairs = [(ln.split("→")[0].strip(), ln.split("→")[1].strip()) for ln in lines if "→" in ln]
        assert len(pairs) == len(set(pairs)), "Duplicate domain pairs in description"

    def test_describe_filters_by_active_agents(self) -> None:
        text = describe_dependencies_for_chat(["finance", "legal"])
        assert "Finance" in text
        assert "Legal" in text
        assert "Producttech" not in text
        assert "Commercial" not in text

    def test_describe_returns_empty_for_single_agent(self) -> None:
        text = describe_dependencies_for_chat(["finance"])
        assert text == ""

    def test_describe_returns_empty_for_no_agents(self) -> None:
        text = describe_dependencies_for_chat([])
        assert text == ""
