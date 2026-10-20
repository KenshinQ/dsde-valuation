"""Fundamental regime classifier, transitions, HMM interface, market-regime separation (SPEC §7.4)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tests.company import company, cyclical_company, loaded_config
from tests.factories import INST
from vms.pipeline import run_estimation
from vms.regimes import (FeatureRow, FundamentalRegimePosterior, MarketRegimePosterior, RegimeModelNotImplemented,
                         estimate_transitions, infer_regimes, make_regime_model, propagate)
from vms.regimes.market import market_regime
from vms.regimes.rule_based import RuleBasedClassifier
from vms.regimes.schemas import PeriodPosterior
from vms.schemas.config import RegimeConfig

CST = timezone(timedelta(hours=8))
RC = loaded_config().config.regimes


def row(g, dm, d=date(2024, 12, 31)):
    return FeatureRow(period_end=d, cadence="annual", revenue_growth_yoy=g, ebit_margin_ttm=0.1,
                      ebit_margin_change_yoy=dm, known_at=datetime(2025, 4, 1, tzinfo=CST), refs=[], flags=[])


CLF = RuleBasedClassifier(RC)


@pytest.mark.parametrize("g,dm,prev,expected", [
    (0.30, 0.02, None, "GROWTH"),
    (0.03, 0.00, None, "STABLE"),
    (-0.15, 0.00, None, "DETERIORATING"),
    (0.03, -0.05, None, "DETERIORATING"),
    (0.04, 0.02, {"GROWTH": 0.0, "STABLE": 0.0, "DETERIORATING": 1.0, "RECOVERY": 0.0}, "RECOVERY"),
])
def test_rules_interpretable(g, dm, prev, expected):
    p = CLF.classify_period(row(g, dm), prev)
    assert p.argmax == expected
    assert sum(p.probabilities.values()) == pytest.approx(1.0, abs=1e-12)
    assert set(p.memberships) == {"growth_high", "contraction", "margin_compression", "deteriorating",
                                  "weak_prior_state"}


def test_partial_and_missing_features():
    p = CLF.classify_period(row(None, -0.05), None)
    assert "PARTIAL_FEATURES" in p.flags and p.argmax == "DETERIORATING"
    p2 = CLF.classify_period(row(0.02, None), None)
    assert p2.memberships["deteriorating"] < 0.5   # missing margin does not invent deterioration
    with pytest.raises(ValueError, match="no features"):
        CLF.classify_period(row(None, None), None)


def test_states_subset_merges_into_stable():
    cfg = RC.model_copy(update={"states": ["GROWTH", "STABLE", "DETERIORATING"]})
    p = RuleBasedClassifier(cfg).classify_period(row(0.04, 0.02), {"GROWTH": 0, "STABLE": 0, "DETERIORATING": 1.0})
    assert list(p.probabilities) == ["GROWTH", "STABLE", "DETERIORATING"]
    assert sum(p.probabilities.values()) == pytest.approx(1.0) and p.argmax == "STABLE"


@pytest.mark.parametrize("upd,msg", [({"states": ["GROWTH", "DETERIORATING"]}, "must include STABLE"),
                                     ({"states": ["BOOM", "STABLE"]}, "distinct members"),
                                     ({"rules": {**RC.rules.model_dump(), "growth_low": 0.2}}, "must be <")])
def test_regime_config_validation(upd, msg):
    with pytest.raises(ValidationError, match=msg):
        RegimeConfig.model_validate({**RC.model_dump(), **upd})


def test_no_features_gives_uniform_flagged_prior():
    cur = CLF.current([], datetime(2025, 5, 6, 15, tzinfo=CST))
    assert set(cur.probabilities.values()) == {0.25} and "NO_FEATURES_UNIFORM_PRIOR" in cur.flags


def _pp(d, state):
    probs = {s: (1.0 if s == state else 0.0) for s in RC.states}
    return PeriodPosterior(period_end=d, probabilities=probs, memberships={}, argmax=state, entropy=0.0, flags=[])


def test_transitions_dirichlet_counts_and_support():
    seq = ["GROWTH", "GROWTH", "DETERIORATING", "RECOVERY", "GROWTH"]
    hist = [_pp(date(2015 + i, 12, 31), s) for i, s in enumerate(seq)]
    tm = estimate_transitions(hist, RC, "annual")
    S = RC.states
    gi, di, ri = S.index("GROWTH"), S.index("DETERIORATING"), S.index("RECOVERY")
    assert tm.n_pairs == 4 and tm.pair_weight == 1.0
    assert tm.expected_counts[gi][gi] == 1 and tm.expected_counts[gi][di] == 1 and tm.expected_counts[di][ri] == 1
    a = RC.transition_prior
    row_tot = a.stay + 3 * a.move + 2
    assert tm.mean[gi][gi] == pytest.approx((a.stay + 1) / row_tot)
    assert tm.row_support[gi] == 2 and any(f.startswith("PRIOR_DOMINATED_ROW") for f in tm.flags)
    assert all(abs(sum(r) - 1) < 1e-12 for r in tm.mean)
    assert sum(propagate({s: 0.25 for s in S}, tm).values()) == pytest.approx(1.0)


def test_quarterly_pairs_downweighted():
    hist = [_pp(date(2020 + (i // 4), (3, 6, 9, 12)[i % 4], (31, 30, 30, 31)[i % 4]), "STABLE") for i in range(12)]
    tm = estimate_transitions(hist, RC, "quarterly")
    assert tm.n_pairs == 8 and tm.pair_weight == 0.25
    assert sum(tm.row_support) == pytest.approx(2.0)   # 8 overlapping pairs ~ 2 effective years


def test_no_history_prior_only():
    tm = estimate_transitions([], RC, None)
    assert "NO_TRANSITIONS_OBSERVED_PRIOR_ONLY" in tm.flags and "STATES_EXCEED_SUPPORT" in tm.flags


def test_hmm_interface_not_implemented():
    with pytest.raises(RegimeModelNotImplemented, match="interface only"):
        make_regime_model(RC.model_copy(update={"model": "hmm"}))


# ---------------------------------------------------------------- distinct schemas
def test_fundamental_and_market_schemas_distinct():
    m = market_regime("none")
    assert m.kind == "MARKET" and m.status == "UNAVAILABLE" and m.probabilities is None
    load, as_of = cyclical_company()
    r = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=loaded_config(), seed=1)
    f = r.regimes.current
    assert f.kind == "FUNDAMENTAL" and f.inputs == "PIT_FUNDAMENTALS_ONLY"
    assert r.regimes.market.status == "UNAVAILABLE"           # never filled from the fundamental state
    with pytest.raises(ValidationError):
        MarketRegimePosterior.model_validate(f.model_dump())
    with pytest.raises(ValidationError):
        FundamentalRegimePosterior.model_validate(m.model_dump())
    with pytest.raises(ValidationError, match="must not carry"):
        MarketRegimePosterior(status="UNAVAILABLE", reason="x", states=["A"], probabilities={"A": 1.0})
    with pytest.raises(ValidationError, match="needs probabilities"):
        MarketRegimePosterior(status="AVAILABLE", states=["A"])
    assert not issubclass(MarketRegimePosterior, FundamentalRegimePosterior)


@pytest.mark.parametrize("probs", [{"GROWTH": 0.5, "STABLE": 0.6, "DETERIORATING": 0.0, "RECOVERY": -0.1},
                                   {"GROWTH": math.nan, "STABLE": 1.0, "DETERIORATING": 0.0, "RECOVERY": 0.0},
                                   {"GROWTH": 0.5, "STABLE": 0.4, "DETERIORATING": 0.0, "RECOVERY": 0.0}])
def test_posterior_validator_rejects_invalid(probs):
    with pytest.raises(ValidationError):
        FundamentalRegimePosterior(model_id="X", model_version="1", states=list(RC.states), probabilities=probs,
                                   period_end=None, as_of=datetime(2025, 1, 1, tzinfo=CST), staleness_days=None,
                                   flags=[], assumptions=[])


def test_cyclical_company_regime_sequence_and_staleness():
    load, as_of = cyclical_company()
    r = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=loaded_config(), seed=1).regimes
    seq = [h.argmax for h in r.history]
    assert {"GROWTH", "DETERIORATING", "RECOVERY"} <= set(seq)
    i = seq.index("RECOVERY")
    assert seq[i - 1] in ("DETERIORATING", "RECOVERY")       # recovery only follows weakness
    assert r.current.period_end == date(2024, 12, 31) and r.current.staleness_days == (as_of.date() - date(2024, 12, 31)).days
    assert r.features[0].cadence == "annual"


def test_annual_only_company_features():
    load, as_of = company()
    from vms.pit.snapshot import build_snapshot
    snap, _, _ = build_snapshot(instrument_id=INST, as_of=as_of, financial=load.financial, market=load.market,
                                corporate_actions=[], sources=load.sources)
    r = infer_regimes(snap.financials, as_of=as_of, cfg=RC)
    assert [f.period_end.year for f in r.features] == [2022, 2023, 2024]
    assert all(f.revenue_growth_yoy == pytest.approx(0.05) for f in r.features)
