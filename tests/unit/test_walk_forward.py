"""Rolling-origin walk-forward diagnostics and selection (never in-sample)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.drivers.distributions import SPECS
from vms.pipeline import run_estimation

L = loaded_config()
WF = L.config.estimation.walk_forward


def est(load, as_of):
    return run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=3)


@pytest.fixture(scope="module")
def cyc():
    load, as_of = cyclical_company()
    return load, as_of, est(load, as_of)


def test_origins_past_only(cyc):
    _, as_of, r = cyc
    assert [o.origin_year for o in r.walk_forward.origins] == list(range(2011, 2024))   # 13 origins
    for o in r.walk_forward.origins:
        assert max(o.train_years) == o.origin_year and o.target_year == o.origin_year + 1
        assert o.origin_as_of.date() == date(o.origin_year + 1, 4, 20) and o.origin_as_of < as_of
        for d in o.drivers.values():
            assert d["n_train_obs"] <= len(o.train_years)


def test_selection_is_argmin_walk_forward_pinball(cyc):
    _, _, r = cyc
    checked = 0
    for name, pd in r.walk_forward.per_driver.items():
        if pd["n_scored_origins"] < WF.min_origins:
            continue
        best = min(SPECS, key=lambda k: (pd["mean_pinball"][k], k != WF.default_spec))
        assert pd["selection"]["selected_spec"] == best == r.distributions.drivers[name].selected_spec
        recomputed = np.mean([o.drivers[name]["pinball"][best] for o in r.walk_forward.origins if name in o.drivers])
        assert recomputed == pytest.approx(pd["mean_pinball"][best])
        if pd["mean_pinball"]["naive_last"] < pd["mean_pinball"][best]:
            assert "NAIVE_BENCHMARK_BETTER" in pd["selection"]["flags"]
        checked += 1
    assert checked >= 5


def test_selection_never_in_sample(monkeypatch, cyc):
    """Corrupting the (reported-only) in-sample scores must not change any selection."""
    load, as_of, r = cyc
    import vms.drivers.walk_forward as wfm
    monkeypatch.setattr(wfm, "in_sample_pinball", lambda zs, fits: {k: (0.0 if k == "prior_only" else 1e9) for k in fits})
    r2 = est(load, as_of)
    sel = lambda run: {k: v.selected_spec for k, v in run.distributions.drivers.items()}  # noqa: E731
    assert sel(r2) == sel(r)
    assert any(v != "prior_only" for v in sel(r2).values())
    assert r2.distributions.drivers["ebit_margin"].selection["in_sample_pinball_not_used_for_selection"]["prior_only"] == 0.0


def test_too_few_origins_default_flagged():
    load, as_of = cyclical_company(first_year=2018, n_years=4)  # classification published 2020 (PIT)
    r = est(load, as_of)
    assert len(r.walk_forward.origins) < WF.min_origins
    d = r.distributions.drivers["ebit_margin"]
    assert d.selected_spec == WF.default_spec
    assert {"SELECTION_DEFAULT_INSUFFICIENT_ORIGINS", "LOW_EVAL_SUPPORT"} <= set(d.flags)
    assert d.low_confidence


def test_diagnostics_content(cyc):
    _, _, r = cyc
    pd = r.walk_forward.per_driver["revenue_growth"]
    assert pd["n_scored_origins"] == len(r.walk_forward.origins)
    assert set(pd["mean_pinball"]) == {*SPECS, "naive_last"}
    assert "persistence_t" in SPECS
    assert all(0 <= v <= 1 for v in pd["central_interval_coverage"].values())
    assert pd["nominal_central_coverage"] == pytest.approx(WF.quantiles[-1] - WF.quantiles[0])
    reg = r.walk_forward.regime
    assert reg["n_scored"] > 0 and set(reg["mean_brier"]) == {"transition_model", "persistence", "uniform"}


def test_later_revision_changes_only_realized_not_forecasts(cyc):
    load, as_of, r = cyc
    load2, _ = cyclical_company(overrides={(2024, "revenue"): 5000.0})
    r2 = est(load2, as_of)
    o1 = {o.origin_year: o for o in r.walk_forward.origins}
    o2 = {o.origin_year: o for o in r2.walk_forward.origins}
    assert o1.keys() == o2.keys()
    for y in o1:
        if y < 2023:
            assert o1[y] == o2[y]
    a, b = o1[2023].drivers["revenue_growth"], o2[2023].drivers["revenue_growth"]
    assert a["forecast_quantiles"] == b["forecast_quantiles"] and a["realized_value"] != b["realized_value"]
