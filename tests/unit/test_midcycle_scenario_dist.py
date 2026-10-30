"""Midcycle backlog #4 slice D — research-only peak/base/trough scenario dist."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from vms.ensemble import (
    diagnostics_with_midcycle_passthrough,
    method_distribution_from_result,
    samples_from_point,
)
from vms.methods.multiples.midcycle import (
    MidCycleConfidence,
    MidCycleEstimate,
    MidCycleScenario,
    MidCycleScenarioDistribution,
    attach_scenario_distribution,
    build_midcycle_scenario_distribution,
    estimate_mid_cycle_denominator,
    passthrough_midcycle_diagnostics,
)
from vms.methods.protocol import MethodResult
from vms.schemas.contracts import MethodEligibilityStatus, OutputBasis, ValuationTarget

CST = timezone(timedelta(hours=8))
ASOF = datetime(2025, 6, 30, 15, tzinfo=CST)


def _complete_series():
    """7 annual points spanning 6y; local peak=100 (i=3), trough=45 (i=5); median=60."""
    years = list(range(2018, 2025))
    values = [40.0, 55.0, 90.0, 100.0, 80.0, 45.0, 60.0]
    return [(date(y, 12, 31), v) for y, v in zip(years, values)]


def test_complete_high_attaches_equal_weight_scenario_dist():
    est = estimate_mid_cycle_denominator(_complete_series(), as_of=ASOF)
    assert est.confidence is MidCycleConfidence.HIGH
    assert est.mid_cycle_denominator == pytest.approx(60.0)
    sd = est.diagnostics.get("scenario_distribution")
    assert isinstance(sd, dict)
    assert sd["method"] == "equal_weight_v1"
    assert sd["research_only"] is True
    assert "CYCLE-MIDCYCLE-SCENARIO-DIST-v1" in sd["assumption_ids"]
    kinds = [s["kind"] for s in sd["scenarios"]]
    assert kinds == ["peak", "base", "trough"]
    by_kind = {s["kind"]: s for s in sd["scenarios"]}
    assert by_kind["peak"]["level"] == pytest.approx(100.0)
    assert by_kind["base"]["level"] == pytest.approx(60.0)
    assert by_kind["trough"]["level"] == pytest.approx(45.0)
    for s in sd["scenarios"]:
        assert s["probability"] == pytest.approx(1.0 / 3.0)
    assert sum(s["probability"] for s in sd["scenarios"]) == pytest.approx(1.0)


def test_builder_none_when_missing_peak_or_trough():
    est = estimate_mid_cycle_denominator(None, as_of=ASOF)
    assert "scenario_distribution" not in est.diagnostics
    assert build_midcycle_scenario_distribution(est) is None

    # Short monotone — no local extrema
    series = [(date(2020 + i, 12, 31), 10.0 + i) for i in range(3)]
    est2 = estimate_mid_cycle_denominator(series, as_of=ASOF)
    assert est2.diagnostics.get("peak_detected") is False
    assert "scenario_distribution" not in est2.diagnostics
    assert build_midcycle_scenario_distribution(est2) is None


def test_builder_none_on_nonpositive_or_order_invalid():
    # peak/trough detected but order peak≥base≥trough fails
    bad = MidCycleEstimate(
        mid_cycle_denominator=50.0,
        confidence=MidCycleConfidence.LOW,
        diagnostics={
            "peak_detected": True,
            "trough_detected": True,
            "peak_value": 10.0,
            "trough_value": 40.0,  # trough > peak → order invalid with base=50
            "median_value": 50.0,
            "reason_codes": ["SYNTHETIC_FIXTURE"],
        },
    )
    assert build_midcycle_scenario_distribution(bad) is None
    attached = attach_scenario_distribution(bad)
    assert "scenario_distribution" not in attached.diagnostics
    assert "SCENARIO_LEVEL_ORDER_INVALID" in attached.diagnostics["reason_codes"]
    assert "SYNTHETIC_FIXTURE" in attached.diagnostics["reason_codes"]

    nonpos = MidCycleEstimate(
        mid_cycle_denominator=50.0,
        confidence=MidCycleConfidence.LOW,
        diagnostics={
            "peak_detected": True,
            "trough_detected": True,
            "peak_value": 80.0,
            "trough_value": 0.0,
            "median_value": 50.0,
            "reason_codes": ["SYNTHETIC_FIXTURE"],
        },
    )
    assert build_midcycle_scenario_distribution(nonpos) is None
    attached_nonpos = attach_scenario_distribution(nonpos)
    assert "scenario_distribution" not in attached_nonpos.diagnostics
    assert "SCENARIO_LEVEL_ORDER_INVALID" not in attached_nonpos.diagnostics.get(
        "reason_codes", []
    )


def test_attach_order_invalid_appends_reason_without_inventing_dist():
    """SF2: order-invalid → SCENARIO_LEVEL_ORDER_INVALID on estimate; no dist."""
    est = MidCycleEstimate(
        mid_cycle_denominator=60.0,
        confidence=MidCycleConfidence.HIGH,
        diagnostics={
            "peak_detected": True,
            "trough_detected": True,
            "peak_value": 100.0,
            "trough_value": 70.0,  # trough > base=60 → order invalid
            "median_value": 60.0,
            "reason_codes": ["COMPLETE_CYCLE_RULES_PASSED"],
        },
    )
    assert build_midcycle_scenario_distribution(est) is None
    out = attach_scenario_distribution(est)
    assert "scenario_distribution" not in out.diagnostics
    assert out.mid_cycle_denominator == pytest.approx(60.0)
    assert out.confidence is MidCycleConfidence.HIGH
    codes = out.diagnostics["reason_codes"]
    assert "SCENARIO_LEVEL_ORDER_INVALID" in codes
    assert "COMPLETE_CYCLE_RULES_PASSED" in codes


def test_sector_prior_only_low_without_extrema_no_scenario_dist():
    est = estimate_mid_cycle_denominator(
        [],
        as_of=ASOF,
        sector_prior=50.0,
        use_sector_prior_stub=True,
    )
    assert est.confidence is MidCycleConfidence.LOW
    assert est.diagnostics["sector_prior_applied"] is True
    assert est.diagnostics.get("peak_detected") is False
    assert "scenario_distribution" not in est.diagnostics
    assert build_midcycle_scenario_distribution(est) is None


def test_incomplete_with_extrema_may_attach_via_median_base():
    """Incomplete span but local peak+trough + positive median → dist via median base."""
    # 5 points, span < 6y, but has local peak+trough
    years = [2020, 2021, 2022, 2023, 2024]
    values = [40.0, 100.0, 70.0, 30.0, 50.0]  # peak i=1=100, trough i=3=30; med=50
    series = [(date(y, 12, 31), v) for y, v in zip(years, values)]
    est = estimate_mid_cycle_denominator(series, as_of=ASOF)
    assert est.confidence is MidCycleConfidence.LOW
    assert "SERIES_TOO_SHORT" in est.diagnostics["reason_codes"]
    assert est.diagnostics["peak_detected"] is True
    assert est.diagnostics["trough_detected"] is True
    sd = est.diagnostics.get("scenario_distribution")
    assert sd is not None
    by_kind = {s["kind"]: s for s in sd["scenarios"]}
    assert by_kind["peak"]["level"] == pytest.approx(100.0)
    assert by_kind["base"]["level"] == pytest.approx(50.0)  # median fallback
    assert by_kind["trough"]["level"] == pytest.approx(30.0)


def test_model_rejects_bad_probs_or_levels():
    with pytest.raises(Exception):
        MidCycleScenario(kind="peak", level=-1.0, probability=0.5)
    with pytest.raises(Exception):
        MidCycleScenarioDistribution(
            scenarios=(
                MidCycleScenario(kind="peak", level=1.0, probability=0.5),
                MidCycleScenario(kind="base", level=1.0, probability=0.5),
                MidCycleScenario(kind="trough", level=1.0, probability=0.5),
            )
        )


def test_passthrough_preserves_nested_scenario_distribution():
    est = estimate_mid_cycle_denominator(_complete_series(), as_of=ASOF)
    dump = est.model_dump(mode="json")
    assert "scenario_distribution" in dump["diagnostics"]
    src = {"diagnostics": {"midcycle_estimate": dump}}
    frag = passthrough_midcycle_diagnostics(src)
    nested = frag["midcycle_estimate"]["diagnostics"]["scenario_distribution"]
    assert nested["method"] == "equal_weight_v1"
    assert nested["scenarios"][0]["kind"] == "peak"

    merged = diagnostics_with_midcycle_passthrough({"center": 1.0}, src)
    assert (
        merged["midcycle_estimate"]["diagnostics"]["scenario_distribution"]["research_only"]
        is True
    )

    md = method_distribution_from_result(
        MethodResult(
            method_id="pe",
            status=MethodEligibilityStatus.VALID,
            diagnostics={"midcycle_estimate": dump},
        ),
        samples=samples_from_point(1.0, n=8, seed=7),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        output_basis=OutputBasis.EQUITY,
        diagnostics={"center": 1.0},
    )
    assert (
        md.diagnostics["midcycle_estimate"]["diagnostics"]["scenario_distribution"]["method"]
        == "equal_weight_v1"
    )
