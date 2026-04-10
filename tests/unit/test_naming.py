"""Tests for subject_safe_name and preprocess_name utilities."""

from __future__ import annotations

import pytest

from dd_agents.utils.naming import preprocess_name, subject_safe_name

# ---------------------------------------------------------------------------
# preprocess_name tests
# ---------------------------------------------------------------------------


class TestPreprocessName:
    def test_lowercase(self) -> None:
        assert preprocess_name("ACME") == "acme"

    def test_strip_inc(self) -> None:
        assert preprocess_name("Acme Inc.") == "acme"

    def test_strip_corp(self) -> None:
        assert preprocess_name("Acme Corp.") == "acme"

    def test_strip_llc(self) -> None:
        assert preprocess_name("Acme LLC") == "acme"

    def test_strip_ltd(self) -> None:
        assert preprocess_name("Acme Ltd.") == "acme"

    def test_strip_gmbh(self) -> None:
        assert preprocess_name("Acme GmbH") == "acme"

    def test_strip_stacked_suffixes(self) -> None:
        assert preprocess_name("Acme Corp. LLC") == "acme"

    def test_ampersand_to_space(self) -> None:
        assert preprocess_name("R&D Global") == "r d global"

    def test_apostrophe_to_space(self) -> None:
        assert preprocess_name("O'Brien Press") == "o brien press"

    def test_parenthesized_text_removed(self) -> None:
        assert preprocess_name("Company (Subsidiary)") == "company"

    def test_collapse_whitespace(self) -> None:
        assert preprocess_name("  Multiple   Spaces  ") == "multiple spaces"

    def test_unicode_normalization(self) -> None:
        # Full-width characters should normalize
        result = preprocess_name("Ａcme")
        assert "acme" in result

    def test_diacritics_transliterated(self) -> None:
        assert preprocess_name("Müller GmbH") == "muller"

    def test_non_decomposable_transliterated(self) -> None:
        assert preprocess_name("Ørsted A/S") == "orsted a s"

    def test_empty_string(self) -> None:
        assert preprocess_name("") == ""

    def test_comma_suffix(self) -> None:
        assert preprocess_name("Alpine Systems, Inc.") == "alpine systems"


# ---------------------------------------------------------------------------
# subject_safe_name tests
# ---------------------------------------------------------------------------


class TestCustomerSafeName:
    @pytest.mark.parametrize(
        "input_name, expected",
        [
            ("Global Analytics Group", "global_analytics_group"),
            ("Alpine Systems, Inc.", "alpine_systems"),
            ("R&D Global", "r_d_global"),
            ("Acme Holdings", "acme_holdings"),
            ("Acme Corp.", "acme"),
            ("Acme Corp. LLC", "acme"),
            ("O'Brien Press", "o_brien_press"),
            ("A/B Testing Co.", "a_b_testing"),
            ("  Leading Spaces  ", "leading_spaces"),
            ("Multiple   Spaces", "multiple_spaces"),
            ("ALLCAPS INC.", "allcaps"),
            ("Already_safe_name", "already_safe_name"),
            ("123 Numeric Start", "123_numeric_start"),
            ("Company (Subsidiary)", "company"),
            ("[Confidential] HR materials", "confidential_hr_materials"),
            ("[Old] Potential transaction structures", "old_potential_transaction_structures"),
        ],
    )
    def test_safe_name_convention(self, input_name: str, expected: str) -> None:
        assert subject_safe_name(input_name) == expected

    def test_safe_name_empty_string(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            subject_safe_name("")

    def test_safe_name_whitespace_only(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            subject_safe_name("   ")

    def test_safe_name_only_legal_suffix(self) -> None:
        with pytest.raises(ValueError, match="resolves to empty"):
            subject_safe_name("Inc.")

    def test_no_leading_trailing_underscores(self) -> None:
        result = subject_safe_name("_underscored_")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_no_consecutive_underscores(self) -> None:
        result = subject_safe_name("A & B   Corp.")
        assert "__" not in result

    def test_dash_replaced(self) -> None:
        result = subject_safe_name("Smith-Jones Partners")
        assert "-" not in result
        assert result == "smith_jones_partners"

    @pytest.mark.parametrize(
        "input_name, expected",
        [
            ("Müller GmbH", "muller"),
            ("Société Générale", "societe_generale"),
            ("José García Ltd.", "jose_garcia"),
            ("Ørsted A/S", "orsted_a_s"),
            ("Zürich Holdings", "zurich_holdings"),
            ("Straße Corp.", "strasse"),
            ("Łódź Systems", "lodz_systems"),
        ],
    )
    def test_unicode_transliterated_to_ascii(self, input_name: str, expected: str) -> None:
        assert subject_safe_name(input_name) == expected
