"""Metric computation functions for agent eval framework."""

from __future__ import annotations

from typing import Any

from .models import (
    CATEGORY_SYNONYMS,
    COMMON_SYNONYMS,
    AgentEvalMetrics,
    ExpectedFinding,
    GroundTruth,
    Verdict,
)

# Severity ordering for range checks (P0=most severe, P3=least severe)
_SEVERITY_ORDER: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _normalize_category(cat: str) -> str:
    """Normalize a category name for comparison.

    Agents use varied formats: "Change of Control", "Financial / Revenue Recognition",
    "security_posture", "Entity/Governance". Normalize to lowercase with underscores.
    """
    import re

    result = cat.lower().strip()
    result = re.sub(r"[/&,]+", " ", result)
    result = re.sub(r"\s+", "_", result)
    result = re.sub(r"_+", "_", result)
    return result.strip("_")


def _categories_match(produced_cat: str, expected_cat: str) -> bool:
    """Check if produced category matches expected, using CATEGORY_SYNONYMS."""
    prod = _normalize_category(produced_cat)
    exp = _normalize_category(expected_cat)

    if exp in prod or prod in exp:
        return True

    exp_synonyms = CATEGORY_SYNONYMS.get(exp, [])
    for syn in exp_synonyms:
        syn_norm = _normalize_category(syn)
        if syn_norm in prod or prod in syn_norm:
            return True

    for canonical, syns in CATEGORY_SYNONYMS.items():
        canonical_norm = _normalize_category(canonical)
        if exp == canonical_norm or exp in [_normalize_category(s) for s in syns]:
            all_names = {canonical_norm} | {_normalize_category(s) for s in syns}
            if prod in all_names or any(name in prod or prod in name for name in all_names):
                return True

    return False


def _severity_in_range(produced_severity: str, min_severity: str, max_severity: str) -> bool:
    """Check whether a produced severity falls within [max_severity, min_severity].

    Severity ordering: P0 (most severe) < P1 < P2 < P3 (least severe).
    max_severity is the most severe acceptable (e.g. P0), min_severity the least (e.g. P3).
    """
    p = _SEVERITY_ORDER.get(produced_severity)
    lo = _SEVERITY_ORDER.get(max_severity)  # most severe bound = lowest number
    hi = _SEVERITY_ORDER.get(min_severity)  # least severe bound = highest number
    if p is None or lo is None or hi is None:
        return False
    return lo <= p <= hi


def _expand_keyword(keyword: str, synonyms: dict[str, list[str]]) -> set[str]:
    """Expand a keyword into a set of acceptable alternatives using synonyms.

    Checks explicit synonyms first, falls back to COMMON_SYNONYMS.
    """
    kw_lower = keyword.lower()
    alternatives = {kw_lower}

    if kw_lower in synonyms:
        alternatives.update(s.lower() for s in synonyms[kw_lower])
    elif keyword in synonyms:
        alternatives.update(s.lower() for s in synonyms[keyword])

    for canonical, syns in COMMON_SYNONYMS.items():
        if kw_lower == canonical.lower() or kw_lower in (s.lower() for s in syns):
            alternatives.add(canonical.lower())
            alternatives.update(s.lower() for s in syns)
            break

    return alternatives


def match_finding(produced: dict[str, Any], expected: ExpectedFinding) -> bool:
    """Check if a produced finding matches an expected finding.

    Matching criteria:
    1. Category match (case-insensitive substring)
    2. Keyword containment with synonym expansion
    3. Citation file reference (if citation_must_reference specifies a file)
    """
    prod_cat = produced.get("category", "").lower()
    exp_cat = expected.category.lower()
    if not _categories_match(prod_cat, exp_cat):
        return False

    if expected.must_contain_keywords:
        text = f"{produced.get('title', '')} {produced.get('description', '')}".lower()
        for kw in expected.must_contain_keywords:
            alternatives = _expand_keyword(kw, expected.keyword_synonyms)
            if not any(alt in text for alt in alternatives):
                return False

    ref_file = expected.citation_must_reference.get("file", "")
    if ref_file:
        citations = produced.get("citations", [])
        if not isinstance(citations, list):
            return False
        found_file = False
        for cit in citations:
            source = ""
            if isinstance(cit, dict):
                source = cit.get("source_path", "")
            elif hasattr(cit, "source_path"):
                source = getattr(cit, "source_path", "")
            if ref_file.lower() in source.lower():
                found_file = True
                break
        if not found_file:
            return False

    return True


def _check_severity(produced: dict[str, Any], expected: ExpectedFinding) -> bool:
    """Check if produced finding severity is within expected range."""
    severity = produced.get("severity", "")
    if hasattr(severity, "value"):
        severity = severity.value
    return _severity_in_range(str(severity), expected.min_severity, expected.max_severity)


def _check_citation(produced: dict[str, Any], expected: ExpectedFinding) -> bool:
    """Check if produced finding citations satisfy expected constraints."""
    if not expected.citation_must_reference:
        return True

    ref_file = expected.citation_must_reference.get("file", "")
    ref_loc = expected.citation_must_reference.get("page_or_section", "")

    citations = produced.get("citations", [])
    if not isinstance(citations, list):
        return False

    for cit in citations:
        source = ""
        location = ""
        if isinstance(cit, dict):
            source = cit.get("source_path", "")
            location = cit.get("location", "")
        elif hasattr(cit, "source_path"):
            source = getattr(cit, "source_path", "")
            location = getattr(cit, "location", "")

        file_ok = (not ref_file) or (ref_file.lower() in source.lower())
        loc_ok = (not ref_loc) or (ref_loc.lower() in location.lower())
        if file_ok and loc_ok:
            return True

    return False


def evaluate_verdict(
    value: float,
    threshold: float,
    ambiguity_zone: float = 0.0,
    higher_is_better: bool = True,
) -> Verdict:
    """Compute a three-valued verdict with optional inconclusive zone.

    For higher_is_better=True (recall, precision, F1):
      - value >= threshold           -> PASS
      - value < threshold - zone     -> FAIL
      - otherwise                    -> INCONCLUSIVE

    For higher_is_better=False (false positive rate):
      - value <= threshold           -> PASS
      - value > threshold + zone     -> FAIL
      - otherwise                    -> INCONCLUSIVE
    """
    if higher_is_better:
        if value >= threshold:
            return Verdict.PASS
        if value < threshold - ambiguity_zone:
            return Verdict.FAIL
        return Verdict.INCONCLUSIVE
    else:
        if value <= threshold:
            return Verdict.PASS
        if value > threshold + ambiguity_zone:
            return Verdict.FAIL
        return Verdict.INCONCLUSIVE


def compute_agent_metrics(
    produced_findings: list[dict[str, Any]],
    ground_truth: GroundTruth,
) -> AgentEvalMetrics:
    """Compute all eval metrics for a single agent against ground truth.

    Args:
        produced_findings: List of finding dicts produced by the agent.
        ground_truth: Expected findings, gaps, and must-not-find constraints.

    Returns:
        AgentEvalMetrics with precision, recall, F1, citation accuracy,
        severity accuracy, false positive rate, and finding count.
    """
    expected = ground_truth.expected_findings
    must_not = ground_truth.must_not_find

    # --- Recall: how many expected findings were matched ---
    matched_expected: list[ExpectedFinding] = []
    matched_produced_indices: set[int] = set()

    for exp in expected:
        if not exp.required:
            continue
        for i, prod in enumerate(produced_findings):
            if i in matched_produced_indices:
                continue
            if match_finding(prod, exp):
                matched_expected.append(exp)
                matched_produced_indices.add(i)
                break

    required_count = sum(1 for e in expected if e.required)
    recall = len(matched_expected) / required_count if required_count > 0 else 1.0

    # --- Precision: what fraction of produced findings match any expected ---
    matches_for_precision: set[int] = set()
    for i, prod in enumerate(produced_findings):
        for exp in expected:
            if match_finding(prod, exp):
                matches_for_precision.add(i)
                break

    precision = len(matches_for_precision) / len(produced_findings) if produced_findings else 1.0

    # --- F1 score ---
    f1 = 2.0 * (precision * recall) / (precision + recall) if precision + recall > 0 else 0.0

    # --- Severity accuracy: of matched findings, how many have correct severity ---
    severity_correct = 0
    severity_total = 0
    for exp in expected:
        if not exp.required:
            continue
        for _i, prod in enumerate(produced_findings):
            if match_finding(prod, exp):
                severity_total += 1
                if _check_severity(prod, exp):
                    severity_correct += 1
                break

    severity_accuracy = severity_correct / severity_total if severity_total > 0 else 1.0

    # --- Citation accuracy: of matched findings, how many have correct citations ---
    citation_correct = 0
    citation_total = 0
    for exp in expected:
        if not exp.required:
            continue
        if not exp.citation_must_reference:
            continue
        for _i, prod in enumerate(produced_findings):
            if match_finding(prod, exp):
                citation_total += 1
                if _check_citation(prod, exp):
                    citation_correct += 1
                break

    citation_accuracy = citation_correct / citation_total if citation_total > 0 else 1.0

    # --- False positive rate: fraction of produced that match must_not_find ---
    false_positives = 0
    for prod in produced_findings:
        prod_cat = prod.get("category", "").lower()
        for mnf in must_not:
            if _categories_match(prod_cat, mnf.category):
                false_positives += 1
                break

    fp_rate = false_positives / len(produced_findings) if produced_findings else 0.0

    return AgentEvalMetrics(
        agent_name=ground_truth.agent,
        finding_recall=recall,
        finding_precision=precision,
        citation_accuracy=citation_accuracy,
        severity_accuracy=severity_accuracy,
        false_positive_rate=fp_rate,
        f1_score=f1,
        finding_count=len(produced_findings),
    )


def find_contradictions(all_results: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Detect contradictions across agents for the same contract.

    Looks for cases where two agents produce findings about the same category
    but with conflicting severity implications (one says P0/P1, other says P3).

    Args:
        all_results: Mapping of agent_name -> list of finding dicts.

    Returns:
        List of contradiction dicts with agent_a, agent_b, category, details.
    """
    contradictions: list[dict[str, Any]] = []

    category_index: dict[str, list[tuple[str, str]]] = {}
    for agent, findings in all_results.items():
        for f in findings:
            cat = f.get("category", "").lower()
            sev = f.get("severity", "")
            if hasattr(sev, "value"):
                sev = sev.value
            if cat:
                category_index.setdefault(cat, []).append((agent, str(sev)))

    for cat, entries in category_index.items():
        if len(entries) < 2:
            continue
        severities = [(agent, _SEVERITY_ORDER.get(sev, 99)) for agent, sev in entries]
        for i in range(len(severities)):
            for j in range(i + 1, len(severities)):
                agent_a, sev_a = severities[i]
                agent_b, sev_b = severities[j]
                if abs(sev_a - sev_b) >= 2:
                    contradictions.append(
                        {
                            "category": cat,
                            "agent_a": agent_a,
                            "agent_a_severity": entries[i][1],
                            "agent_b": agent_b,
                            "agent_b_severity": entries[j][1],
                            "gap": abs(sev_a - sev_b),
                        }
                    )

    return contradictions


def find_severity_disagreements(
    all_results: dict[str, list[dict[str, Any]]],
    max_gap: int = 1,
) -> list[dict[str, Any]]:
    """Detect severity disagreements across agents within an acceptable gap.

    Unlike find_contradictions which looks for large gaps (>=2), this detects
    any disagreement beyond max_gap levels.

    Args:
        all_results: Mapping of agent_name -> list of finding dicts.
        max_gap: Maximum acceptable severity gap (default 1 level).

    Returns:
        List of disagreement dicts.
    """
    disagreements: list[dict[str, Any]] = []

    category_index: dict[str, list[tuple[str, str]]] = {}
    for agent, findings in all_results.items():
        for f in findings:
            cat = f.get("category", "").lower()
            sev = f.get("severity", "")
            if hasattr(sev, "value"):
                sev = sev.value
            if cat:
                category_index.setdefault(cat, []).append((agent, str(sev)))

    for cat, entries in category_index.items():
        if len(entries) < 2:
            continue
        severities = [(agent, _SEVERITY_ORDER.get(sev, 99)) for agent, sev in entries]
        for i in range(len(severities)):
            for j in range(i + 1, len(severities)):
                agent_a, sev_a = severities[i]
                agent_b, sev_b = severities[j]
                if abs(sev_a - sev_b) > max_gap:
                    disagreements.append(
                        {
                            "category": cat,
                            "agent_a": agent_a,
                            "agent_a_severity": entries[i][1],
                            "agent_b": agent_b,
                            "agent_b_severity": entries[j][1],
                            "gap": abs(sev_a - sev_b),
                        }
                    )

    return disagreements
