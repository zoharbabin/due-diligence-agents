"""Comprehensive tests for DealConfig and related configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dd_agents.models.config import (
    AcquiredEntity,
    ActiveFilter,
    BuyerInfo,
    CustomDomain,
    DealConfig,
    EntityAliases,
    ExecutionConfig,
    ForensicDDConfig,
    JudgeConfig,
    ReportingConfig,
    SamplingRates,
    SourceOfTruth,
    SubjectDatabase,
    SubjectDatabaseColumns,
    TargetInfo,
)
from dd_agents.models.enums import AgentName, DealType, ExecutionMode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_deal_config_data() -> dict:
    """Return the minimal valid DealConfig data (only required fields)."""
    return {
        "config_version": "1.0.0",
        "buyer": {"name": "AcquireCo"},
        "target": {"name": "TargetCo"},
        "deal": {
            "type": "acquisition",
            "focus_areas": ["contract_review"],
        },
    }


def _full_deal_config_data() -> dict:
    """Return a fully-populated DealConfig data dict."""
    return {
        "config_version": "2.1.0",
        "buyer": {
            "name": "AcquireCo Inc.",
            "ticker": "ACQ",
            "exchange": "NYSE",
            "notes": "Large-cap buyer",
        },
        "target": {
            "name": "TargetCo Ltd.",
            "subsidiaries": ["SubA", "SubB"],
            "previous_names": [{"name": "OldTargetName", "period": "2010-2020", "notes": "Rebranded"}],
            "acquired_entities": [
                {
                    "name": "SmallCo",
                    "acquisition_date": "2022-06-15",
                    "deal_type": "asset_purchase",
                    "notes": "Small tuck-in",
                }
            ],
            "entity_name_variants_for_contract_matching": [
                "Target Co",
                "TargetCo Limited",
            ],
            "notes": "SaaS platform company",
        },
        "entity_aliases": {
            "canonical_to_variants": {"TargetCo Ltd.": ["Target Co", "TargetCo Limited"]},
            "short_name_guard": ["IT", "AI"],
            "exclusions": ["Generic Corp"],
            "parent_child": {"TargetCo Ltd.": ["SubA", "SubB"]},
        },
        "source_of_truth": {
            "subject_database": {
                "file": "data/customers.xlsx",
                "sheet": "Active",
                "header_row": 2,
                "columns": {
                    "subject_name": 1,
                    "parent_account": 2,
                    "entity": 3,
                    "platform": 4,
                    "contract_start": 5,
                    "contract_end": 6,
                    "arr": 7,
                },
                "active_filter": {
                    "arr_column": 7,
                    "arr_condition": "> 0",
                    "end_date_condition": ">= today",
                },
            }
        },
        "key_executives": [
            {
                "name": "Jane Doe",
                "title": "CEO",
                "company": "TargetCo Ltd.",
                "notes": "Founder",
            }
        ],
        "deal": {
            "type": "acquisition",
            "focus_areas": ["contract_review", "financial_analysis", "ip_review"],
            "notes": "Strategic acquisition for SaaS product",
        },
        "judge": {
            "enabled": True,
            "max_iteration_rounds": 3,
            "score_threshold": 80,
            "sampling_rates": {
                "p0": 1.0,
                "p1": 0.30,
                "p2": 0.15,
                "p3": 0.05,
            },
            "ocr_completeness_check": True,
            "cross_agent_contradiction_check": True,
        },
        "execution": {
            "execution_mode": "full",
            "staleness_threshold": 5,
            "force_full_on_config_change": True,
        },
        "reporting": {
            "report_schema_override": None,
            "include_diff_sheet": True,
            "include_metadata_sheet": True,
        },
        "forensic_dd": {
            "enabled": True,
            "domains": {
                "disabled": ["hr_compliance"],
                "custom": [
                    {
                        "id": "data_privacy",
                        "name": "Data Privacy Review",
                        "description": "GDPR and CCPA compliance check",
                        "agent_assignment": "legal",
                        "expected_finding_categories": ["privacy_violation", "consent_gap"],
                        "key_terms": ["GDPR", "CCPA", "data processing agreement"],
                        "weight": 2,
                    }
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# Valid Config Tests
# ---------------------------------------------------------------------------


class TestDealConfigValid:
    """Tests for valid DealConfig construction."""

    def test_full_config(self):
        """Full config with all fields should validate successfully."""
        data = _full_deal_config_data()
        config = DealConfig.model_validate(data)

        assert config.config_version == "2.1.0"
        assert config.buyer.name == "AcquireCo Inc."
        assert config.buyer.ticker == "ACQ"
        assert config.target.name == "TargetCo Ltd."
        assert len(config.target.subsidiaries) == 2
        assert len(config.target.previous_names) == 1
        assert len(config.target.acquired_entities) == 1
        assert config.target.acquired_entities[0].acquisition_date == "2022-06-15"
        assert config.deal.type == DealType.ACQUISITION
        assert len(config.deal.focus_areas) == 3
        assert config.judge.enabled is True
        assert config.judge.max_iteration_rounds == 3
        assert config.judge.score_threshold == 80
        assert config.judge.sampling_rates.p0 == 1.0
        assert config.judge.sampling_rates.p1 == 0.30
        assert config.execution.execution_mode == ExecutionMode.FULL
        assert config.execution.staleness_threshold == 5
        assert config.forensic_dd.enabled is True
        assert len(config.forensic_dd.domains.disabled) == 1
        assert len(config.forensic_dd.domains.custom) == 1
        assert config.forensic_dd.domains.custom[0].id == "data_privacy"
        assert config.forensic_dd.domains.custom[0].agent_assignment == AgentName.LEGAL

    def test_minimal_config(self):
        """Minimal config with only required fields should use correct defaults."""
        data = _minimal_deal_config_data()
        config = DealConfig.model_validate(data)

        assert config.config_version == "1.0.0"
        assert config.buyer.name == "AcquireCo"
        assert config.buyer.ticker == ""
        assert config.buyer.exchange == ""
        assert config.target.name == "TargetCo"
        assert config.target.subsidiaries == []
        assert config.target.previous_names == []
        assert config.target.acquired_entities == []
        assert config.target.entity_name_variants_for_contract_matching == []
        assert config.entity_aliases.canonical_to_variants == {}
        assert config.entity_aliases.short_name_guard == []
        assert config.entity_aliases.exclusions == []
        assert config.entity_aliases.parent_child == {}
        assert config.source_of_truth.subject_database is None
        assert config.key_executives == []
        assert config.deal.type == DealType.ACQUISITION
        assert config.deal.focus_areas == ["contract_review"]
        assert config.deal.notes == ""
        # Judge defaults
        assert config.judge.enabled is True
        assert config.judge.max_iteration_rounds == 2
        assert config.judge.score_threshold == 70
        assert config.judge.sampling_rates.p0 == 1.0
        assert config.judge.sampling_rates.p1 == 0.20
        assert config.judge.sampling_rates.p2 == 0.10
        assert config.judge.sampling_rates.p3 == 0.0
        assert config.judge.ocr_completeness_check is True
        assert config.judge.cross_agent_contradiction_check is True
        # Execution defaults
        assert config.execution.execution_mode == ExecutionMode.FULL
        assert config.execution.staleness_threshold == 3
        assert config.execution.force_full_on_config_change is True
        # Reporting defaults
        assert config.reporting.report_schema_override is None
        assert config.reporting.include_diff_sheet is True
        assert config.reporting.include_metadata_sheet is True
        # Forensic DD defaults
        assert config.forensic_dd.enabled is True
        assert config.forensic_dd.domains.disabled == []
        assert config.forensic_dd.domains.custom == []

    def test_serialization_round_trip(self):
        """Config should survive a serialization round-trip."""
        data = _full_deal_config_data()
        config = DealConfig.model_validate(data)
        dumped = config.model_dump(exclude_none=True)
        config2 = DealConfig.model_validate(dumped)
        assert config == config2

    def test_json_round_trip(self):
        """Config should survive JSON serialization round-trip."""
        data = _full_deal_config_data()
        config = DealConfig.model_validate(data)
        json_str = config.model_dump_json(exclude_none=True)
        config2 = DealConfig.model_validate_json(json_str)
        assert config == config2

    def test_extra_fields_allowed(self):
        """DealConfig should accept extra fields without error."""
        data = _minimal_deal_config_data()
        data["custom_field"] = "custom_value"
        data["buyer"]["custom_buyer_field"] = 42
        config = DealConfig.model_validate(data)
        assert config.custom_field == "custom_value"  # type: ignore[attr-defined]
        assert config.buyer.custom_buyer_field == 42  # type: ignore[attr-defined]

    def test_all_deal_types(self):
        """All DealType enum values should be accepted."""
        for deal_type in DealType:
            data = _minimal_deal_config_data()
            data["deal"]["type"] = deal_type.value
            config = DealConfig.model_validate(data)
            assert config.deal.type == deal_type

    def test_all_execution_modes(self):
        """All ExecutionMode enum values should be accepted."""
        for mode in ExecutionMode:
            data = _minimal_deal_config_data()
            data["execution"] = {"execution_mode": mode.value}
            config = DealConfig.model_validate(data)
            assert config.execution.execution_mode == mode


# ---------------------------------------------------------------------------
# Invalid Config Tests
# ---------------------------------------------------------------------------


class TestDealConfigInvalid:
    """Tests for invalid DealConfig data that should raise ValidationError."""

    def test_missing_config_version(self):
        """Missing config_version should raise ValidationError."""
        data = _minimal_deal_config_data()
        del data["config_version"]
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_invalid_config_version_format(self):
        """Non-semver config_version should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["config_version"] = "1.0"  # missing patch
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_config_version_below_minimum(self):
        """config_version below 1.0.0 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["config_version"] = "0.9.9"
        with pytest.raises(ValidationError, match="config_version must be >= 1.0.0"):
            DealConfig.model_validate(data)

    def test_config_version_zero(self):
        """config_version 0.0.0 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["config_version"] = "0.0.0"
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_missing_buyer(self):
        """Missing buyer should raise ValidationError."""
        data = _minimal_deal_config_data()
        del data["buyer"]
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_empty_buyer_name(self):
        """Empty buyer name should raise ValidationError (min_length=1)."""
        data = _minimal_deal_config_data()
        data["buyer"]["name"] = ""
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_missing_target(self):
        """Missing target should raise ValidationError."""
        data = _minimal_deal_config_data()
        del data["target"]
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_empty_target_name(self):
        """Empty target name should raise ValidationError (min_length=1)."""
        data = _minimal_deal_config_data()
        data["target"]["name"] = ""
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_missing_deal(self):
        """Missing deal should raise ValidationError."""
        data = _minimal_deal_config_data()
        del data["deal"]
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_invalid_deal_type(self):
        """Invalid deal type should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["deal"]["type"] = "hostile_takeover"
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_empty_focus_areas(self):
        """Empty focus_areas list should raise ValidationError (min_length=1)."""
        data = _minimal_deal_config_data()
        data["deal"]["focus_areas"] = []
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_invalid_execution_mode(self):
        """Invalid execution mode should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["execution"] = {"execution_mode": "partial"}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_judge_max_iteration_rounds_too_high(self):
        """max_iteration_rounds > 5 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"max_iteration_rounds": 10}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_judge_max_iteration_rounds_too_low(self):
        """max_iteration_rounds < 1 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"max_iteration_rounds": 0}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_judge_score_threshold_too_high(self):
        """score_threshold > 100 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"score_threshold": 101}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_judge_score_threshold_too_low(self):
        """score_threshold < 0 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"score_threshold": -1}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_sampling_rate_above_one(self):
        """Sampling rate > 1.0 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"sampling_rates": {"p0": 1.5}}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_sampling_rate_below_zero(self):
        """Sampling rate < 0.0 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["judge"] = {"sampling_rates": {"p1": -0.1}}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_staleness_threshold_too_low(self):
        """staleness_threshold < 1 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["execution"] = {"staleness_threshold": 0}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_staleness_threshold_too_high(self):
        """staleness_threshold > 100 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["execution"] = {"staleness_threshold": 101}
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_custom_domain_invalid_id_pattern(self):
        """Custom domain id with invalid pattern should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["forensic_dd"] = {
            "domains": {
                "custom": [
                    {
                        "id": "Invalid-ID",  # must be ^[a-z_]+$
                        "name": "Test",
                        "agent_assignment": "legal",
                    }
                ]
            }
        }
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_custom_domain_weight_out_of_range(self):
        """Custom domain weight outside 1-3 range should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["forensic_dd"] = {
            "domains": {
                "custom": [
                    {
                        "id": "test_domain",
                        "name": "Test",
                        "agent_assignment": "legal",
                        "weight": 5,
                    }
                ]
            }
        }
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_acquired_entity_bad_date(self):
        """Invalid acquisition_date format should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["target"]["acquired_entities"] = [{"name": "BadCo", "acquisition_date": "June 2022"}]
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            DealConfig.model_validate(data)

    def test_subject_database_column_below_one(self):
        """subject_name column < 1 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["source_of_truth"] = {
            "subject_database": {
                "file": "data.xlsx",
                "columns": {"subject_name": 0},
            }
        }
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_subject_database_header_row_below_one(self):
        """header_row < 1 should raise ValidationError."""
        data = _minimal_deal_config_data()
        data["source_of_truth"] = {
            "subject_database": {
                "file": "data.xlsx",
                "header_row": 0,
                "columns": {"subject_name": 1},
            }
        }
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_subject_database_empty_file(self):
        """Empty file string should raise ValidationError (min_length=1)."""
        data = _minimal_deal_config_data()
        data["source_of_truth"] = {
            "subject_database": {
                "file": "",
                "columns": {"subject_name": 1},
            }
        }
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Defaults Tests
# ---------------------------------------------------------------------------


class TestDealConfigDefaults:
    """Tests that default values are correctly applied."""

    def test_judge_defaults(self):
        """JudgeConfig should have correct defaults."""
        judge = JudgeConfig()
        assert judge.enabled is True
        assert judge.max_iteration_rounds == 2
        assert judge.score_threshold == 70
        assert judge.ocr_completeness_check is True
        assert judge.cross_agent_contradiction_check is True

    def test_sampling_rates_defaults(self):
        """SamplingRates should have correct defaults."""
        rates = SamplingRates()
        assert rates.p0 == 1.0
        assert rates.p1 == 0.20
        assert rates.p2 == 0.10
        assert rates.p3 == 0.0

    def test_execution_config_defaults(self):
        """ExecutionConfig should have correct defaults."""
        exec_config = ExecutionConfig()
        assert exec_config.execution_mode == ExecutionMode.FULL
        assert exec_config.staleness_threshold == 3
        assert exec_config.force_full_on_config_change is True

    def test_reporting_config_defaults(self):
        """ReportingConfig should have correct defaults."""
        report_config = ReportingConfig()
        assert report_config.report_schema_override is None
        assert report_config.include_diff_sheet is True
        assert report_config.include_metadata_sheet is True

    def test_forensic_dd_config_defaults(self):
        """ForensicDDConfig should have correct defaults."""
        fdd = ForensicDDConfig()
        assert fdd.enabled is True
        assert fdd.domains.disabled == []
        assert fdd.domains.custom == []

    def test_entity_aliases_defaults(self):
        """EntityAliases should have correct defaults."""
        aliases = EntityAliases()
        assert aliases.canonical_to_variants == {}
        assert aliases.short_name_guard == []
        assert aliases.exclusions == []
        assert aliases.parent_child == {}

    def test_source_of_truth_defaults(self):
        """SourceOfTruth should have correct defaults."""
        sot = SourceOfTruth()
        assert sot.subject_database is None

    def test_buyer_info_defaults(self):
        """BuyerInfo should have correct defaults for optional fields."""
        buyer = BuyerInfo(name="TestBuyer")
        assert buyer.ticker == ""
        assert buyer.exchange == ""
        assert buyer.notes == ""

    def test_target_info_defaults(self):
        """TargetInfo should have correct defaults for optional fields."""
        target = TargetInfo(name="TestTarget")
        assert target.subsidiaries == []
        assert target.previous_names == []
        assert target.acquired_entities == []
        assert target.entity_name_variants_for_contract_matching == []
        assert target.notes == ""

    def test_custom_domain_defaults(self):
        """CustomDomain should have correct defaults for optional fields."""
        domain = CustomDomain(id="test", name="Test", agent_assignment=AgentName.LEGAL)
        assert domain.description == ""
        assert domain.expected_finding_categories == []
        assert domain.key_terms == []
        assert domain.weight == 3


# ---------------------------------------------------------------------------
# Version Validation Tests
# ---------------------------------------------------------------------------


class TestConfigVersionValidation:
    """Tests for config_version pattern and minimum version validation."""

    def test_version_1_0_0(self):
        """Version 1.0.0 (minimum) should be accepted."""
        data = _minimal_deal_config_data()
        data["config_version"] = "1.0.0"
        config = DealConfig.model_validate(data)
        assert config.config_version == "1.0.0"

    def test_version_1_0_1(self):
        """Version 1.0.1 should be accepted."""
        data = _minimal_deal_config_data()
        data["config_version"] = "1.0.1"
        config = DealConfig.model_validate(data)
        assert config.config_version == "1.0.1"

    def test_version_2_0_0(self):
        """Version 2.0.0 should be accepted."""
        data = _minimal_deal_config_data()
        data["config_version"] = "2.0.0"
        config = DealConfig.model_validate(data)
        assert config.config_version == "2.0.0"

    def test_version_10_20_30(self):
        """Multi-digit version should be accepted."""
        data = _minimal_deal_config_data()
        data["config_version"] = "10.20.30"
        config = DealConfig.model_validate(data)
        assert config.config_version == "10.20.30"

    def test_version_0_0_1_rejected(self):
        """Version 0.0.1 should be rejected (below 1.0.0)."""
        data = _minimal_deal_config_data()
        data["config_version"] = "0.0.1"
        with pytest.raises(ValidationError, match="config_version must be >= 1.0.0"):
            DealConfig.model_validate(data)

    def test_version_0_99_99_rejected(self):
        """Version 0.99.99 should be rejected (below 1.0.0)."""
        data = _minimal_deal_config_data()
        data["config_version"] = "0.99.99"
        with pytest.raises(ValidationError, match="config_version must be >= 1.0.0"):
            DealConfig.model_validate(data)

    def test_version_non_numeric_rejected(self):
        """Non-numeric version should be rejected by pattern."""
        data = _minimal_deal_config_data()
        data["config_version"] = "abc.def.ghi"
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_version_missing_part_rejected(self):
        """Two-part version should be rejected by pattern."""
        data = _minimal_deal_config_data()
        data["config_version"] = "1.0"
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_version_four_parts_rejected(self):
        """Four-part version should be rejected by pattern."""
        data = _minimal_deal_config_data()
        data["config_version"] = "1.0.0.0"
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)

    def test_version_empty_rejected(self):
        """Empty string version should be rejected by pattern."""
        data = _minimal_deal_config_data()
        data["config_version"] = ""
        with pytest.raises(ValidationError):
            DealConfig.model_validate(data)


# ---------------------------------------------------------------------------
# AcquiredEntity Date Validation Tests
# ---------------------------------------------------------------------------


class TestAcquiredEntityDateValidation:
    """Tests for AcquiredEntity.acquisition_date validator."""

    def test_valid_date(self):
        """Valid YYYY-MM-DD date should be accepted."""
        entity = AcquiredEntity(name="TestCo", acquisition_date="2023-01-15")
        assert entity.acquisition_date == "2023-01-15"

    def test_empty_date_allowed(self):
        """Empty string date should be accepted (optional)."""
        entity = AcquiredEntity(name="TestCo", acquisition_date="")
        assert entity.acquisition_date == ""

    def test_default_empty_date(self):
        """Default acquisition_date should be empty string."""
        entity = AcquiredEntity(name="TestCo")
        assert entity.acquisition_date == ""

    def test_invalid_date_format(self):
        """Non-YYYY-MM-DD date should be rejected."""
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            AcquiredEntity(name="TestCo", acquisition_date="01/15/2023")

    def test_partial_date_rejected(self):
        """Partial date should be rejected."""
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            AcquiredEntity(name="TestCo", acquisition_date="2023-01")


# ---------------------------------------------------------------------------
# SubjectDatabase Validation Tests
# ---------------------------------------------------------------------------


class TestSubjectDatabaseValidation:
    """Tests for SubjectDatabase and related models."""

    def test_valid_subject_database(self):
        """Valid SubjectDatabase should be accepted."""
        db = SubjectDatabase(
            file="data/customers.xlsx",
            sheet="Active",
            header_row=2,
            columns=SubjectDatabaseColumns(
                subject_name=1,
                parent_account=2,
                arr=7,
            ),
            active_filter=ActiveFilter(
                arr_column=7,
                arr_condition="> 0",
            ),
        )
        assert db.file == "data/customers.xlsx"
        assert db.columns.subject_name == 1
        assert db.columns.parent_account == 2
        assert db.columns.arr == 7
        assert db.active_filter is not None
        assert db.active_filter.arr_column == 7

    def test_minimal_subject_database(self):
        """Minimal SubjectDatabase with only required fields."""
        db = SubjectDatabase(
            file="data.xlsx",
            columns=SubjectDatabaseColumns(subject_name=1),
        )
        assert db.file == "data.xlsx"
        assert db.sheet == ""
        assert db.header_row == 1
        assert db.columns.subject_name == 1
        assert db.columns.parent_account is None
        assert db.active_filter is None
