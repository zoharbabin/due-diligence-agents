"""Pure-Python TF-IDF used by entity-resolution pass 4.

Golden values were produced once with scikit-learn's
``TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4))`` plus cosine
similarity, so the replacement is pinned to the old behaviour without
needing scikit-learn installed.
"""

from __future__ import annotations

import pytest

from dd_agents.entity_resolution.matcher import _pass_4_tfidf_match, _tfidf_similarities

GOLDEN: list[tuple[str, list[str], list[float]]] = [
    (
        "alpha industries group",
        ["alpha industry group", "beta holdings", "alpha industries", "gamma partners"],
        [0.763459204343, 0.0, 0.841196666227, 0.0],
    ),
    (
        "northwind trading company",
        ["northwind trade co", "southwind trading company", "northwind"],
        [0.477708993196, 0.758828469715, 0.526663054597],
    ),
    ("a b", ["a b c", "ab", "b a"], [0.670060729269, 0.0, 1.0]),
    ("  spaced   out   name ", ["spaced out name", "spacedout name", "name spaced out"], [1.0, 0.621886959234, 1.0]),
    ("zeta", ["zeta", "zet", "zeta zeta zeta"], [1.0, 0.311191147512, 1.0]),
    (
        "café société générale",
        ["cafe societe generale", "café société générale", "societe"],
        [0.222407766101, 1.0, 0.126479362068],
    ),
    ("alpha 123 labs", ["alpha 124 labs", "alpha labs", "123"], [0.682970434731, 0.832198759867, 0.554477433334]),
    ("ab", ["ab", "a", "b"], [1.0, 0.0, 0.0]),
    ("one", ["two"], [0.0]),
    ("repeat repeat repeat", ["repeat", "repeat repeat", "other repeat"], [1.0, 1.0, 0.499718808284]),
]


@pytest.mark.parametrize(("source", "targets", "expected"), GOLDEN)
def test_matches_scikit_learn_values(source: str, targets: list[str], expected: list[float]) -> None:
    got = _tfidf_similarities(source, targets)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        assert g == pytest.approx(e, abs=1e-9)


def test_empty_vocabulary_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty vocabulary"):
        _tfidf_similarities("", [""])


def test_pass_4_returns_best_match_above_threshold() -> None:
    targets = {"alpha industries": "Alpha Industries", "beta holdings": "Beta Holdings"}
    name, score = _pass_4_tfidf_match("alpha industrie", targets, [])
    assert name == "Alpha Industries"
    assert score > 0.8


def test_pass_4_tie_picks_first_target() -> None:
    targets = {"repeat": "First", "repeat repeat": "Second"}
    name, score = _pass_4_tfidf_match("repeat repeat repeat", targets, [])
    assert name == "First"
    assert score == pytest.approx(1.0)


def test_pass_4_short_source_is_skipped() -> None:
    assert _pass_4_tfidf_match("ab", {"ab": "AB"}, []) == (None, 0.0)


def test_pass_4_no_vocabulary_returns_no_match() -> None:
    assert _pass_4_tfidf_match("          ", {"   ": "Blank"}, []) == (None, 0.0)
