"""Skeleton mid-cycle estimator (cyc-midcycle-skel / SPEC §12.6)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.multiples.midcycle import (
    MIN_COMPLETE_POINTS,
    MIN_COMPLETE_SPAN_YEARS,
    MidCycleConfidence,
    estimate_mid_cycle_denominator,
)
from vms.methods.protocol import ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.schemas.config import load_config
from vms.schemas.contracts import MethodEligibilityStatus, ProfileFlag, ProfileLabel, ValuationTarget
from vms.schemas.observations import PeerObservation, QualityStatus

CST = timezone(timedelta(hours=8))
ASOF = datetime(2025, 6, 30, 15, tzinfo=CST)
SUBJ = "SYNTH.CYC"


DIAG_KEYS = {
    "n_points",
    "n_usable",
    "window_span_years",
    "peak_value",
    "trough_value",
    "peak_detected",
    "trough_detected",
    "reason_codes",
    "estimator",
    "sector_prior_applied",
    "research_only",
}


def _complete_series():
    """7 annual points spanning 6y with clear peak/trough around a mid-cycle median."""
    # values sorted [40,50,55,60,80,90,100] → median = 60 (SF4: prior comment wrongly said 70)
    years = list(range(2018, 2025))  # 2018..2024 → span 6.0y
    values = [40.0, 55.0, 90.0, 100.0, 80.0, 60.0, 50.0]
    assert len(years) == len(values) == MIN_COMPLETE_POINTS
    assert (date(years[-1], 12, 31) - date(years[0], 12, 31)).days / 365.25 >= MIN_COMPLETE_SPAN_YEARS
    return [(date(y, 12, 31), v) for y, v in zip(years, values)]


def test_incomplete_missing_series_none_low_conf():
    est = estimate_mid_cycle_denominator(None, as_of=ASOF)
    assert est.mid_cycle_denominator is None
    assert est.confidence is MidCycleConfidence.LOW
    assert "SERIES_MISSING" in est.diagnostics["reason_codes"]
    assert DIAG_KEYS <= set(est.diagnostics)


def test_incomplete_short_series_none_low_conf():
    series = [(date(2020 + i, 12, 31), 10.0 + i) for i in range(3)]
    est = estimate_mid_cycle_denominator(series, as_of=ASOF)
    assert est.mid_cycle_denominator is None
    assert est.confidence is MidCycleConfidence.LOW
    assert "SERIES_TOO_SHORT" in est.diagnostics["reason_codes"]
    assert DIAG_KEYS <= set(est.diagnostics)
    assert est.diagnostics["sector_prior_applied"] is False


def test_sector_prior_stub_research_only_low_never_silent():
    # Without opt-in: prior present but not applied; denom still None.
    est = estimate_mid_cycle_denominator(
        [(date(2024, 12, 31), 10.0)],
        as_of=ASOF,
        sector_prior=50.0,
        use_sector_prior_stub=False,
    )
    assert est.mid_cycle_denominator is None
    assert est.confidence is MidCycleConfidence.LOW
    assert "SECTOR_PRIOR_PRESENT_BUT_STUB_OFF" in est.diagnostics["reason_codes"]
    assert est.diagnostics["sector_prior_applied"] is False

    # With opt-in: research-only LOW fill, never HIGH.
    est2 = estimate_mid_cycle_denominator(
        [(date(2024, 12, 31), 10.0)],
        as_of=ASOF,
        sector_prior=50.0,
        use_sector_prior_stub=True,
    )
    assert est2.mid_cycle_denominator == pytest.approx(50.0)
    assert est2.confidence is MidCycleConfidence.LOW
    assert est2.diagnostics["research_only"] is True
    assert est2.diagnostics["sector_prior_applied"] is True
    assert "SECTOR_PRIOR_STUB_RESEARCH_ONLY" in est2.diagnostics["reason_codes"]


def test_synthetic_complete_finite_denom_and_diagnostics():
    series = _complete_series()
    est = estimate_mid_cycle_denominator(series, as_of=ASOF)
    assert est.mid_cycle_denominator is not None
    assert est.mid_cycle_denominator == pytest.approx(60.0)  # median of series
    assert est.confidence is MidCycleConfidence.HIGH
    assert DIAG_KEYS <= set(est.diagnostics)
    assert "COMPLETE_CYCLE_RULES_PASSED" in est.diagnostics["reason_codes"]
    assert est.diagnostics["peak_detected"] is True
    assert est.diagnostics["trough_detected"] is True
    assert est.diagnostics["n_points"] == MIN_COMPLETE_POINTS
    assert est.diagnostics["window_span_years"] >= MIN_COMPLETE_SPAN_YEARS


def test_pit_drops_post_asof_points():
    series = _complete_series() + [(date(2026, 12, 31), 999.0)]
    est = estimate_mid_cycle_denominator(series, as_of=ASOF)
    assert est.confidence is MidCycleConfidence.HIGH
    assert est.mid_cycle_denominator == pytest.approx(60.0)
    assert "PIT_DROPPED_POST_ASOF" in est.diagnostics["reason_codes"]



def _complete_negative_series():
    """7 annual points spanning 6y with peak/trough but non-positive median (SF1)."""
    years = list(range(2018, 2025))
    # sorted [-100,-50,-20,-10,-5,-2,-1] → median = -10; peak/trough vs med detectable
    values = [-100.0, -50.0, -20.0, -1.0, -5.0, -2.0, -10.0]
    assert len(years) == len(values) == MIN_COMPLETE_POINTS
    return [(date(y, 12, 31), v) for y, v in zip(years, values)]


def test_sf1_nonpositive_median_not_high():
    est = estimate_mid_cycle_denominator(_complete_negative_series(), as_of=ASOF)
    assert est.confidence is MidCycleConfidence.LOW
    assert est.mid_cycle_denominator is None
    assert "NONPOSITIVE_MEDIAN" in est.diagnostics["reason_codes"]
    assert "COMPLETE_CYCLE_RULES_PASSED" not in est.diagnostics["reason_codes"]
    assert est.diagnostics["median_value"] == pytest.approx(-10.0)
    assert DIAG_KEYS <= set(est.diagnostics)


def test_sf2_bad_date_string_drops_point_no_throw():
    # One bad date amid an otherwise complete series → drop that point → may degrade short.
    good = _complete_series()
    tainted = list(good)
    tainted[3] = ("not-a-date", 100.0)  # was peak year; drop → 6 points → SHORT
    est = estimate_mid_cycle_denominator(tainted, as_of=ASOF)
    assert est.confidence is MidCycleConfidence.LOW
    assert est.mid_cycle_denominator is None
    assert est.diagnostics["n_points"] == MIN_COMPLETE_POINTS - 1
    assert "SERIES_TOO_SHORT" in est.diagnostics["reason_codes"]

    # Mapping form with bad period_end also drops; bare bad as_of degrades without throw.
    est2 = estimate_mid_cycle_denominator(
        [{"period_end": "bogus", "value": 10.0}, {"period_end": "2020-12-31", "value": 20.0}],
        as_of="also-bogus",
    )
    assert est2.confidence is MidCycleConfidence.LOW
    assert "ASOF_UNPARSEABLE" in est2.diagnostics["reason_codes"]
    assert est2.diagnostics["n_points"] == 1


def _peer(pid: str, field: str, value: float) -> PeerObservation:
    return PeerObservation(
        subject_instrument_id=SUBJ,
        peer_instrument_id=pid,
        published_at=datetime(2022, 1, 15, 9, tzinfo=CST),
        membership_start=date(2021, 1, 1),
        membership_end=None,
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        metric_timestamp=ASOF,
        source_id="SYNTHETIC",
        revision_id="r0",
        quality_status=QualityStatus.OBSERVED,
    )


def _cyclical_ctx(repo, *, subject=None, peers=None, assumptions_series=None):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "cyclical.json")
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={"instrument_id": SUBJ, "as_of": "2025-06-30"})
    profile = classify_profile(feats).model_copy(
        update={
            "primary_profile": ProfileLabel.CYCLICAL_OPERATING,
            "flags": [ProfileFlag.HIGH_CYCLICALITY],
        }
    )
    sm = subject or {
        "parent_net_income": 100.0,
        "total_equity": 500.0,
        "ebit": 140.0,
        "ebitda": 160.0,
        "depreciation_amortization": 20.0,
        "revenue": 1000.0,
        "cash": 50.0,
        "interest_bearing_debt": 120.0,
        "diluted_shares": 10.0,
    }
    if assumptions_series is not None:
        sm = {**sm, "pit_parent_net_income_series": assumptions_series}
    peers = peers or [_peer(f"P{i}.SZ", "pe", float(10 + i)) for i in range(8)]
    fields = frozenset(data.get("available_fields") or []) | {
        "parent_net_income", "total_equity", "ebit", "revenue",
    }
    ctx = ValuationContext(
        instrument_id=SUBJ,
        as_of=ASOF.isoformat(),
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        profile=profile,
        available_fields=fields,
        peer_count=len({p.peer_instrument_id for p in peers}),
        subject_metrics=sm,
        peer_observations=tuple(peers),
        loaded=loaded,
    )
    return loaded, ctx


def test_hook_cyclical_without_series_still_flags_trailing(repo):
    """Absent estimate → existing trailing-without-midcycle path (AC2/AC4)."""
    loaded, ctx = _cyclical_ctx(repo)
    r = build_registry_from_config(loaded.method_registry).plugin("pe").value_paths(
        ctx, None, MethodConfig(method_id="pe"),
    )
    assert r.values
    assert "CYCLE_ESTIMATE_LOW_CONFIDENCE" in r.values["flags"]
    assert r.status is MethodEligibilityStatus.LOW_CONFIDENCE
    # Estimator ran (cyclical, no mid supplied) → diagnostics present, denom None.
    est = (r.diagnostics or {}).get("midcycle_estimate")
    assert est is not None
    assert est["mid_cycle_denominator"] is None
    assert est["confidence"] == "LOW"


def test_hook_cyclical_high_conf_series_uses_midcycle(repo):
    loaded, ctx = _cyclical_ctx(repo, assumptions_series=_complete_series())
    # Trailing NI=100; mid-cycle median=60 → should use mid and flag MID_CYCLE_DENOMINATOR_USED.
    r = build_registry_from_config(loaded.method_registry).plugin("pe").value_paths(
        ctx, None, MethodConfig(method_id="pe"),
    )
    assert r.values
    assert "MID_CYCLE_DENOMINATOR_USED" in r.values["flags"]
    assert "CYCLE_ESTIMATE_LOW_CONFIDENCE" not in r.values["flags"]
    assert r.values["denominator_value"] == pytest.approx(60.0)
    est = (r.diagnostics or {}).get("midcycle_estimate")
    assert est is not None
    assert est["confidence"] == "HIGH"


def test_hook_non_cyclical_does_not_auto_normalize(repo):
    loaded = load_config(repo / "config/default.yaml")
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    feats = feats.model_copy(update={"instrument_id": SUBJ, "as_of": "2025-06-30"})
    profile = classify_profile(feats)
    peers = [_peer(f"P{i}.SZ", "pe", float(10 + i)) for i in range(8)]
    sm = {
        "parent_net_income": 100.0,
        "total_equity": 500.0,
        "ebit": 140.0,
        "ebitda": 160.0,
        "depreciation_amortization": 20.0,
        "revenue": 1000.0,
        "cash": 50.0,
        "interest_bearing_debt": 120.0,
        "diluted_shares": 10.0,
        "pit_parent_net_income_series": _complete_series(),
    }
    ctx = ValuationContext(
        instrument_id=SUBJ,
        as_of=ASOF.isoformat(),
        target=ValuationTarget.RELATIVE_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(sm),
        peer_count=8,
        subject_metrics=sm,
        peer_observations=tuple(peers),
        loaded=loaded,
    )
    r = build_registry_from_config(loaded.method_registry).plugin("pe").value_paths(
        ctx, None, MethodConfig(method_id="pe"),
    )
    assert r.values
    assert "MID_CYCLE_DENOMINATOR_USED" not in r.values["flags"]
    assert r.values["denominator_value"] == pytest.approx(100.0)
    assert (r.diagnostics or {}).get("midcycle_estimate") is None
