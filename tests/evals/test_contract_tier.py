"""Deterministic contract-tier tests (Tier 3).

No LLM calls, no API keys. Validates structural integrity of ground truth
files, contracts, models, and cross-references. Runs on every PR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .metrics import _SEVERITY_ORDER, _severity_in_range, evaluate_verdict
from .models import COMMON_SYNONYMS, GroundTruth, Verdict

_EVALS_DIR = Path(__file__).parent
_GROUND_TRUTH_DIR = _EVALS_DIR / "ground_truth"
_CONTRACTS_DIR = _GROUND_TRUTH_DIR / "contracts"
_EXPECTED_DIR = _GROUND_TRUTH_DIR / "expected"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_expected_jsons() -> list[tuple[str, Path]]:
    """Return (agent/filename, path) for all expected finding JSONs."""
    results: list[tuple[str, Path]] = []
    if not _EXPECTED_DIR.exists():
        return results
    for agent_dir in sorted(_EXPECTED_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        for jf in sorted(agent_dir.glob("*.json")):
            results.append((f"{agent_dir.name}/{jf.name}", jf))
    return results


def _load_gt(path: Path) -> GroundTruth:
    data = json.loads(path.read_text())
    return GroundTruth.model_validate(data)


# ---------------------------------------------------------------------------
# 1. Ground truth JSON schema validation
# ---------------------------------------------------------------------------


class TestGroundTruthSchema:
    """Every expected findings JSON must parse into a valid GroundTruth model."""

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_json_parses_into_model(self, label: str, path: Path) -> None:
        gt = _load_gt(path)
        assert gt.contract, f"{label}: contract field is empty"
        assert gt.agent, f"{label}: agent field is empty"
        assert len(gt.expected_findings) > 0 or len(gt.must_not_find) > 0, (
            f"{label}: must have at least one expected_finding or must_not_find"
        )

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_severity_ranges_valid(self, label: str, path: Path) -> None:
        """max_severity number <= min_severity number (P0 <= P3)."""
        gt = _load_gt(path)
        for ef in gt.expected_findings:
            max_ord = _SEVERITY_ORDER.get(ef.max_severity)
            min_ord = _SEVERITY_ORDER.get(ef.min_severity)
            assert max_ord is not None, f"{label}: invalid max_severity '{ef.max_severity}'"
            assert min_ord is not None, f"{label}: invalid min_severity '{ef.min_severity}'"
            assert max_ord <= min_ord, (  # type: ignore[operator]
                f"{label}: max_severity {ef.max_severity} must be more severe (lower number) "
                f"than min_severity {ef.min_severity}"
            )

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_must_not_find_no_overlap_with_expected(self, label: str, path: Path) -> None:
        """must_not_find categories must not overlap with expected_findings categories."""
        gt = _load_gt(path)
        expected_cats = {ef.category.lower() for ef in gt.expected_findings}
        for mnf in gt.must_not_find:
            assert mnf.category.lower() not in expected_cats, (
                f"{label}: '{mnf.category}' is both expected and must_not_find"
            )

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_tags_are_valid(self, label: str, path: Path) -> None:
        valid_tags = {"golden_path", "edge_case", "adversarial", "regression", "cross_domain"}
        gt = _load_gt(path)
        for tag in gt.tags:
            assert tag in valid_tags, f"{label}: invalid tag '{tag}', must be one of {valid_tags}"

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_ambiguity_zone_bounds(self, label: str, path: Path) -> None:
        gt = _load_gt(path)
        assert 0.0 <= gt.ambiguity_zone <= 0.5, f"{label}: ambiguity_zone {gt.ambiguity_zone} out of range [0.0, 0.5]"


# ---------------------------------------------------------------------------
# 2. Contract file integrity
# ---------------------------------------------------------------------------


class TestContractIntegrity:
    """Validate synthetic contract files are well-formed."""

    def _all_contracts(self) -> list[Path]:
        return sorted(_CONTRACTS_DIR.glob("*.md"))

    def test_contracts_exist(self) -> None:
        contracts = self._all_contracts()
        assert len(contracts) >= 5, f"Expected at least 5 contracts, found {len(contracts)}"

    @pytest.mark.parametrize(
        "contract",
        sorted(_CONTRACTS_DIR.glob("*.md")),
        ids=[p.name for p in sorted(_CONTRACTS_DIR.glob("*.md"))],
    )
    def test_contract_is_valid_utf8(self, contract: Path) -> None:
        text = contract.read_text(encoding="utf-8")
        assert len(text) > 0, f"{contract.name} is empty"

    @pytest.mark.parametrize(
        "contract",
        sorted(_CONTRACTS_DIR.glob("*.md")),
        ids=[p.name for p in sorted(_CONTRACTS_DIR.glob("*.md"))],
    )
    def test_contract_has_sections(self, contract: Path) -> None:
        """Each contract must have at least one section header."""
        text = contract.read_text()
        has_heading = any(line.startswith("#") for line in text.splitlines())
        assert has_heading, f"{contract.name} has no markdown headings"

    @pytest.mark.parametrize(
        "contract",
        sorted(_CONTRACTS_DIR.glob("*.md")),
        ids=[p.name for p in sorted(_CONTRACTS_DIR.glob("*.md"))],
    )
    def test_contract_size_bounds(self, contract: Path) -> None:
        size = contract.stat().st_size
        assert size > 100, f"{contract.name} too small ({size} bytes)"
        assert size < 100_000, f"{contract.name} too large ({size} bytes)"


# ---------------------------------------------------------------------------
# 3. Cross-reference integrity
# ---------------------------------------------------------------------------


class TestCrossReferences:
    """Verify ground truth files reference existing contracts and agents."""

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_referenced_contract_exists(self, label: str, path: Path) -> None:
        gt = _load_gt(path)
        contract_path = _CONTRACTS_DIR / gt.contract
        assert contract_path.exists(), (
            f"{label}: references contract '{gt.contract}' but file not found at {contract_path}"
        )

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_citation_files_match_contract(self, label: str, path: Path) -> None:
        """citation_must_reference.file should match the ground truth's contract."""
        gt = _load_gt(path)
        for ef in gt.expected_findings:
            ref_file = ef.citation_must_reference.get("file", "")
            if ref_file:
                assert ref_file == gt.contract, (
                    f"{label}: citation_must_reference.file '{ref_file}' doesn't match contract '{gt.contract}'"
                )

    @pytest.mark.parametrize("label,path", _all_expected_jsons(), ids=[t[0] for t in _all_expected_jsons()])
    def test_agent_dir_matches_agent_field(self, label: str, path: Path) -> None:
        """The directory name should match the agent field in the JSON."""
        gt = _load_gt(path)
        agent_dir_name = path.parent.name
        assert agent_dir_name == gt.agent, f"{label}: file is in '{agent_dir_name}/' but agent field is '{gt.agent}'"

    def test_every_builtin_agent_has_ground_truth(self) -> None:
        """Every registered agent should have at least one ground truth file."""
        from dd_agents.agents.registry import AgentRegistry

        AgentRegistry.reset()
        agent_names = AgentRegistry.all_specialist_names()
        agent_dirs = {p.name for p in _EXPECTED_DIR.iterdir() if p.is_dir()}
        for name in agent_names:
            assert name in agent_dirs, f"No ground truth directory for agent: {name}"

    def test_every_contract_has_at_least_one_expected(self) -> None:
        """Every contract file should be referenced by at least one expected findings JSON."""
        contract_names = {p.name for p in _CONTRACTS_DIR.glob("*.md")}
        referenced: set[str] = set()
        for _, jpath in _all_expected_jsons():
            gt = _load_gt(jpath)
            referenced.add(gt.contract)
        unreferenced = contract_names - referenced
        assert not unreferenced, f"Contracts with no expected findings: {unreferenced}"


# ---------------------------------------------------------------------------
# 4. Dataset composition
# ---------------------------------------------------------------------------


class TestDatasetComposition:
    """Verify dataset has a healthy mix of golden paths, edge cases, adversarial."""

    def _all_tags(self) -> dict[str, int]:
        tag_counts: dict[str, int] = {}
        for _, path in _all_expected_jsons():
            gt = _load_gt(path)
            for tag in gt.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        return tag_counts

    def test_has_golden_path_cases(self) -> None:
        tags = self._all_tags()
        assert tags.get("golden_path", 0) >= 4, "Need at least 4 golden path eval cases"

    def test_has_edge_cases(self) -> None:
        tags = self._all_tags()
        assert tags.get("edge_case", 0) >= 2, "Need at least 2 edge case eval cases"

    def test_has_adversarial_cases(self) -> None:
        tags = self._all_tags()
        assert tags.get("adversarial", 0) >= 1, "Need at least 1 adversarial eval case"

    def test_has_cross_domain_cases(self) -> None:
        tags = self._all_tags()
        assert tags.get("cross_domain", 0) >= 4, "Need at least 4 cross_domain eval cases"

    def test_must_not_find_coverage(self) -> None:
        """At least 30% of eval cases should have must_not_find entries (false positive guards)."""
        total = 0
        with_mnf = 0
        for _, path in _all_expected_jsons():
            gt = _load_gt(path)
            total += 1
            if gt.must_not_find:
                with_mnf += 1
        assert total > 0
        ratio = with_mnf / total
        assert ratio >= 0.3, f"Only {ratio:.0%} of cases have must_not_find (need >= 30%)"


# ---------------------------------------------------------------------------
# 5. Metric function deterministic tests
# ---------------------------------------------------------------------------


class TestVerdictLogic:
    """Verify three-valued verdict computation."""

    def test_pass_higher_is_better(self) -> None:
        assert evaluate_verdict(0.85, 0.80) == Verdict.PASS

    def test_fail_higher_is_better(self) -> None:
        assert evaluate_verdict(0.60, 0.80) == Verdict.FAIL

    def test_inconclusive_higher_is_better(self) -> None:
        assert evaluate_verdict(0.72, 0.80, ambiguity_zone=0.10) == Verdict.INCONCLUSIVE

    def test_pass_lower_is_better(self) -> None:
        assert evaluate_verdict(0.10, 0.15, higher_is_better=False) == Verdict.PASS

    def test_fail_lower_is_better(self) -> None:
        assert evaluate_verdict(0.30, 0.15, higher_is_better=False) == Verdict.FAIL

    def test_inconclusive_lower_is_better(self) -> None:
        assert evaluate_verdict(0.18, 0.15, ambiguity_zone=0.05, higher_is_better=False) == Verdict.INCONCLUSIVE

    def test_exact_threshold_passes(self) -> None:
        assert evaluate_verdict(0.80, 0.80) == Verdict.PASS

    def test_zero_ambiguity_no_inconclusive(self) -> None:
        assert evaluate_verdict(0.79, 0.80, ambiguity_zone=0.0) == Verdict.FAIL


class TestSeverityRangeEdgeCases:
    """Extended severity range tests."""

    def test_all_valid_severities(self) -> None:
        for sev in ["P0", "P1", "P2", "P3"]:
            assert _severity_in_range(sev, "P3", "P0") is True

    def test_empty_string_severity(self) -> None:
        assert _severity_in_range("", "P3", "P0") is False

    def test_none_like_severity(self) -> None:
        assert _severity_in_range("None", "P3", "P0") is False


class TestSynonymSetIntegrity:
    """Validate COMMON_SYNONYMS and CATEGORY_SYNONYMS are consistent and non-empty."""

    def test_all_entries_have_synonyms(self) -> None:
        for keyword, syns in COMMON_SYNONYMS.items():
            assert len(syns) >= 1, f"COMMON_SYNONYMS['{keyword}'] has no synonyms"
            assert keyword not in syns, f"COMMON_SYNONYMS['{keyword}'] contains itself"

    def test_no_empty_string_synonyms(self) -> None:
        for keyword, syns in COMMON_SYNONYMS.items():
            for s in syns:
                assert s.strip(), f"COMMON_SYNONYMS['{keyword}'] has empty synonym"

    def test_keyword_synonyms_in_ground_truth_are_valid(self) -> None:
        """keyword_synonyms keys must be present in must_contain_keywords."""
        for label, path in _all_expected_jsons():
            gt = _load_gt(path)
            for ef in gt.expected_findings:
                for syn_key in ef.keyword_synonyms:
                    kw_lower = [k.lower() for k in ef.must_contain_keywords]
                    assert syn_key.lower() in kw_lower, (
                        f"{label}: keyword_synonyms key '{syn_key}' not in "
                        f"must_contain_keywords {ef.must_contain_keywords}"
                    )

    def test_category_synonyms_non_empty(self) -> None:
        from .models import CATEGORY_SYNONYMS

        for cat, syns in CATEGORY_SYNONYMS.items():
            assert len(syns) >= 1, f"CATEGORY_SYNONYMS['{cat}'] has no synonyms"
            assert cat not in syns, f"CATEGORY_SYNONYMS['{cat}'] contains itself"

    def test_category_synonyms_no_empty_strings(self) -> None:
        from .models import CATEGORY_SYNONYMS

        for cat, syns in CATEGORY_SYNONYMS.items():
            for s in syns:
                assert s.strip(), f"CATEGORY_SYNONYMS['{cat}'] has empty synonym"

    def test_category_synonyms_cover_ground_truth_categories(self) -> None:
        """Every expected category in ground truth should have an entry in CATEGORY_SYNONYMS."""
        from .metrics import _categories_match
        from .models import CATEGORY_SYNONYMS

        all_expected_cats: set[str] = set()
        for _, path in _all_expected_jsons():
            gt = _load_gt(path)
            for ef in gt.expected_findings:
                all_expected_cats.add(ef.category.lower())
        for cat in all_expected_cats:
            has_entry = cat in CATEGORY_SYNONYMS or any(
                _categories_match(cat, canonical) for canonical in CATEGORY_SYNONYMS
            )
            assert has_entry, f"Category '{cat}' used in ground truth has no CATEGORY_SYNONYMS entry"


# ---------------------------------------------------------------------------
# 6. Finding dict compatibility with agent output models
# ---------------------------------------------------------------------------


class TestFindingModelCompat:
    """Verify that make_finding_dict output is structurally compatible with agent output."""

    def test_finding_dict_has_required_fields(self) -> None:
        from .conftest import make_finding_dict

        finding = make_finding_dict(category="test", severity="P1", title="Test", source_path="f.pdf")
        required_fields = {"category", "severity", "title", "description", "citations", "confidence"}
        assert required_fields.issubset(finding.keys())

    def test_citation_dict_has_required_fields(self) -> None:
        from .conftest import make_finding_dict

        finding = make_finding_dict(category="test", source_path="f.pdf", location="Section 1")
        cit = finding["citations"][0]
        assert "source_path" in cit
        assert "location" in cit
        assert "exact_quote" in cit

    def test_severity_values_match_expected(self) -> None:
        """All severity values used in ground truth must be in the recognized set."""
        valid = set(_SEVERITY_ORDER.keys())
        for label, path in _all_expected_jsons():
            gt = _load_gt(path)
            for ef in gt.expected_findings:
                assert ef.min_severity in valid, f"{label}: invalid min_severity '{ef.min_severity}'"
                assert ef.max_severity in valid, f"{label}: invalid max_severity '{ef.max_severity}'"
