"""VMS-0.2 Phase 2: economic-profile classifier (SPEC §7 / §20)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms.profiles import CLASSIFIER_VERSION, classify_profile, load_overrides
from vms.profiles.features import ProfileFeatureBundle
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.profiles.overrides import ManualOverride, OverrideCatalog
from vms.profiles.rules import RULES_VERSION
from vms.schemas.contracts import ProfileFlag, ProfileLabel


FIXTURES = fixtures_dir()


@pytest.mark.parametrize("name,expected", [
    ("mature_operating.json", ProfileLabel.MATURE_OPERATING),
    ("growth_negative_fcf.json", ProfileLabel.GROWTH_OR_REINVESTMENT_HEAVY),
    ("financial_institution.json", ProfileLabel.FINANCIAL_INSTITUTION),
    ("cyclical.json", ProfileLabel.CYCLICAL_OPERATING),
    ("holding.json", ProfileLabel.HOLDING_OR_CONGLOMERATE),
])
def test_synthetic_fixtures_route_to_expected_profile(name, expected):
    data = load_fixture(FIXTURES / name)
    report = classify_profile(features_from_fixture(data))
    allow_low = bool(data.get("allow_low_confidence"))
    if report.primary_profile is expected:
        assert True
    elif allow_low and report.low_confidence:
        # Spec: or visibly return low confidence
        assert report.low_confidence is True
    else:
        pytest.fail(
            f"{name}: expected {expected.value}, got {report.primary_profile.value} "
            f"low_confidence={report.low_confidence} scores={report.profile_scores} "
            f"hits={[h.rule_id for h in report.rule_hits]}"
        )
    assert report.investment_value == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert report.classifier_version == CLASSIFIER_VERSION
    assert report.rules_version == RULES_VERSION


def test_cyclical_flags_high_cyclicality():
    data = load_fixture(FIXTURES / "cyclical.json")
    report = classify_profile(features_from_fixture(data))
    assert ProfileFlag.HIGH_CYCLICALITY in report.flags
    assert any(h.rule_id.startswith("R_CYCLICAL") or h.rule_id.startswith("F_HIGH_CYCLICAL")
               for h in [*report.rule_hits, *report.flag_hits])


def test_growth_flags_negative_fcf():
    data = load_fixture(FIXTURES / "growth_negative_fcf.json")
    report = classify_profile(features_from_fixture(data))
    assert ProfileFlag.CURRENT_FCF_NEGATIVE in report.flags
    assert any(h.rule_id == "R_GROWTH_NEG_FCF" for h in report.rule_hits)


def test_classifier_output_traceable_to_features_and_rule_ids():
    data = load_fixture(FIXTURES / "mature_operating.json")
    feats = features_from_fixture(data)
    report = classify_profile(feats)
    assert report.rule_hits, "expected at least one profile rule hit"
    for hit in report.rule_hits:
        assert hit.rule_id
        assert hit.feature_refs
        for ref in hit.feature_refs:
            assert ref in report.feature_values
            # Feature value in report matches input bundle
            assert report.feature_values[ref] == getattr(feats, ref)
        assert hit.detail
    assert "fcf_to_revenue" in report.feature_values


def test_industry_alone_insufficient_for_hard_class():
    """Industry taxonomy alone must not silently hard-class with high confidence."""
    f = ProfileFeatureBundle(
        instrument_id="SYN_INDUSTRY_ONLY.SZ",
        as_of="2025-06-30",
        industry_name="银行",
        # No financial evidence
    )
    report = classify_profile(f)
    assert report.low_confidence is True
    # Either HYBRID or low-confidence FINANCIAL from aux-only rule
    assert report.primary_profile in {
        ProfileLabel.FINANCIAL_INSTITUTION, ProfileLabel.HYBRID_OR_UNCLEAR,
    }
    assert report.confidence < 0.45 or report.low_confidence


def test_manual_override_versioned_and_recorded(tmp_path):
    data = load_fixture(FIXTURES / "mature_operating.json")
    feats = features_from_fixture(data)
    catalog = OverrideCatalog(
        override_version="test-overrides-v1",
        overrides=[
            ManualOverride(
                instrument_id=feats.instrument_id,
                primary_profile=ProfileLabel.HOLDING_OR_CONGLOMERATE,
                reason="unit-test forced holding override",
                as_of_from="2020-01-01",
                as_of_to="2030-01-01",
            )
        ],
    )
    path = tmp_path / "overrides.yaml"
    import yaml
    path.write_text(yaml.safe_dump(catalog.model_dump(mode="json"), sort_keys=False))
    loaded = load_overrides(path)
    report = classify_profile(feats, overrides=loaded)
    assert report.manual_override.applied is True
    assert report.manual_override.override_version == "test-overrides-v1"
    assert report.manual_override.reason == "unit-test forced holding override"
    assert report.manual_override.overridden_primary is ProfileLabel.MATURE_OPERATING
    assert report.primary_profile is ProfileLabel.HOLDING_OR_CONGLOMERATE


def test_conflicting_signals_visible_low_confidence():
    """Strong bank + strong holding evidence → conflict / hybrid, not silent hard class."""
    f = ProfileFeatureBundle(
        instrument_id="SYN_CONFLICT.SZ",
        as_of="2025-06-30",
        interest_income_to_revenue=0.70,
        financial_assets_to_assets=0.80,
        investment_assets_to_assets=0.60,
        equity_method_income_to_pretax=0.50,
        n_segments=5,
        has_listed_subsidiaries=True,
        history_years=10,
        book_equity=1e9,
        revenue_cagr_3y=0.02,
        fcf_to_revenue=0.01,
        ebit_margin=0.05,
        ebit_margin_stdev_3y=0.01,
        net_income_to_revenue=0.1,
        debt_to_assets=0.2,
        cash_to_assets=0.1,
    )
    report = classify_profile(f)
    assert report.low_confidence or report.primary_profile is ProfileLabel.HYBRID_OR_UNCLEAR \
        or report.conflicting_signals
    if report.conflicting_signals:
        assert report.primary_profile is ProfileLabel.HYBRID_OR_UNCLEAR


def test_missing_fields_listed():
    f = ProfileFeatureBundle(instrument_id="X", as_of="2025-01-01")
    report = classify_profile(f)
    assert "fcf_to_revenue" in report.missing_fields
    assert report.low_confidence is True
