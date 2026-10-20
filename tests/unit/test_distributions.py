"""Conditional driver estimators: robust stats, transforms/bounds, shrinkage, fallbacks, parameter uncertainty."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from tests.company import company, cyclical_company, loaded_config
from tests.factories import INST
from vms.drivers.distributions import MAD_K, DistObservation, fit_specs, pinball, pooled_fit, t_mix_quantiles, wmedian
from vms.pipeline import run_estimation
from vms.schemas.config import DriverSpec

L = loaded_config()
EST = L.config.estimation
STATES = list(L.config.regimes.states)
PROFILE = {d.name: d for d in L.profile.drivers}
U = {s: 0.25 for s in STATES}


def obs(zs, weights=None):
    return [DistObservation(year=2000 + i, value=0.0, z=z, state_weights=(weights[i] if weights else U), refs=[],
                            flags=[]) for i, z in enumerate(zs)]


def est(load, as_of, seed=1):
    return run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=seed)


def test_pooled_fit_hand_computed():
    z = np.array([0.0, 0.1, 0.2, 1.0])
    loc_hat, s_hat, loc, s = pooled_fit(z, mu0=0.5, s0=0.2, k=2.0)
    assert loc_hat == pytest.approx(0.15)
    assert s_hat == pytest.approx(MAD_K * np.median(np.abs(z - 0.15)))
    assert loc == pytest.approx((4 * 0.15 + 2 * 0.5) / 6)
    assert s == pytest.approx(math.sqrt((3 * s_hat ** 2 + 2 * 0.04) / 5))
    assert pooled_fit(np.array([]), 0.5, 0.2, 2.0) == (None, None, 0.5, 0.2)


def test_shrinkage_weight_increases_with_history():
    w = [pooled_fit(np.full(n, 1.0), 0.0, 0.1, 2.0)[2] for n in range(1, 30)]
    assert all(a < b for a, b in zip(w, w[1:])) and w[0] == pytest.approx(1 / 3) and w[-1] > 0.9


def test_robust_to_outlier():
    clean = pooled_fit(np.array([0.1, 0.11, 0.09, 0.1, 0.12]), 0.1, 0.05, 2.0)
    dirty = pooled_fit(np.array([0.1, 0.11, 0.09, 0.1, 25.0]), 0.1, 0.05, 2.0)
    assert abs(dirty[2] - clean[2]) < 0.01 and dirty[3] < 0.1


def test_weighted_median():
    assert wmedian(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 10.0])) == 3.0
    assert wmedian(np.array([1.0, 2.0]), np.array([1.0, 1.0])) == 1.5


@pytest.mark.parametrize("n", [0, 1, 2])
def test_sparse_history_shrinks_and_flags(n):
    load, as_of = company(years=tuple(range(2024 - n, 2025)), growth=0.30)  # far from the prior
    d = est(load, as_of).distributions.drivers["revenue_growth"]
    assert d.n_obs == n and d.low_confidence and "LOW_CONFIDENCE" in d.flags
    loc = d.specs["pooled_t"].loc
    if n == 0:
        assert "PRIOR_FALLBACK" in d.flags
        assert loc == d.prior_loc_z and d.specs["pooled_t"].scale == d.prior_scale_z
    else:
        assert "SPARSE_HISTORY_SHRINKAGE" in d.flags
        assert d.shrink_weight_data == pytest.approx(n / (n + EST.prior_strength))
        lo, hi = sorted([d.prior_loc_z, d.loc_hat])
        assert lo - 1e-12 <= loc <= hi + 1e-12 and loc != pytest.approx(d.loc_hat)   # pulled toward prior


def test_long_history_not_low_confidence():
    load, as_of = cyclical_company()
    d = est(load, as_of).distributions.drivers["revenue_growth"]
    assert d.n_obs == EST.max_history_years and not d.low_confidence and "SPARSE_HISTORY_SHRINKAGE" not in d.flags


def test_regime_conditional_only_with_support():
    spec = PROFILE["revenue_growth"]
    det = {s: (1.0 if s == "DETERIORATING" else 0.0) for s in STATES}
    gro = {s: (1.0 if s == "GROWTH" else 0.0) for s in STATES}
    fits, _, (_, _, loc, _) = fit_specs(obs([-0.2] * 5 + [0.3, 0.32], [det] * 5 + [gro] * 2), spec, STATES, det, EST)
    rp = {r.state: r for r in fits["regime_t"].regime}
    assert rp["DETERIORATING"].method == "conditional_shrunk_to_pooled" and rp["DETERIORATING"].n_eff == 5
    assert rp["GROWTH"].method == "pooled_fallback" and "REGIME_POOLED_FALLBACK" in rp["GROWTH"].flags
    assert rp["DETERIORATING"].loc < loc
    assert fits["regime_t"].quantiles_z["0.5"] < fits["pooled_t"].quantiles_z["0.5"]
    allfb, _, _ = fit_specs(obs([0.1, 0.2]), spec, STATES, U, EST)
    assert "REGIME_POOLED_FALLBACK_ALL" in allfb["regime_t"].flags


def test_mixture_quantiles_match_t_for_single_component():
    q = t_mix_quantiles([0.1, 0.5, 0.9], [(1.0, 0.3, 0.2)], 4.0)
    assert q == pytest.approx([0.3 + 0.2 * stats.t.ppf(p, 4.0) for p in (0.1, 0.5, 0.9)], abs=1e-9)


def test_empirical_spec_needs_enough_observations():
    spec = PROFILE["ebit_margin"]
    few, _, _ = fit_specs(obs([0.1, 0.2, 0.15]), spec, STATES, U, EST)
    assert "EMPIRICAL_FALLBACK_TO_T" in few["pooled_empirical"].flags
    many, _, _ = fit_specs(obs([0.1, 0.2, 0.15, 0.12, 0.18, 0.3, 0.05]), spec, STATES, U, EST)
    assert many["pooled_empirical"].family == "empirical" and len(many["pooled_empirical"].residuals) == 7


@pytest.mark.parametrize("name", sorted(PROFILE))
def test_quantiles_within_bounds_and_monotone_for_every_driver(name):
    spec = PROFILE[name]
    fits, bench, _ = fit_specs(obs([-40.0, 40.0, 0.0, 35.0, -35.0, 1.0, 2.0]), spec, STATES, U, EST)
    for f in [*fits.values(), *bench.values()]:
        q = [f.quantiles[k] for k in sorted(f.quantiles, key=float)]
        assert all(spec.lower <= v <= spec.upper for v in q) and q == sorted(q), f.spec_id
        assert all(math.isfinite(v) for v in q)


def test_logit_boundary_observation_flagged_and_finite():
    load, as_of = company(overrides={(y, "parent_net_income"): 90.0 for y in range(2021, 2025)})  # share > 1
    d = est(load, as_of).distributions.drivers["parent_share_of_net_income"]
    assert {"OBS_CLIPPED_TO_BOUND", "BOUNDARY_OBS"} <= set(d.flags)
    assert all(math.isfinite(o.z) and abs(o.z) < 10 for o in d.observations)


def test_transforms_variable_appropriate():
    t = {d.name: d.transform.value for d in L.profile.drivers}
    assert t["gross_margin"] == t["ebit_margin"] == t["effective_tax_rate"] == "logit"
    assert t["revenue_growth"] == "log1p"
    with pytest.raises(ValueError):
        DriverSpec.model_validate({**PROFILE["revenue_growth"].model_dump(), "lower": -1.0})


def test_parameter_uncertainty_bootstrap_seeded():
    load, as_of = cyclical_company()
    a, b, c = (est(load, as_of, s).distributions for s in (11, 11, 12))
    pa = a.drivers["revenue_growth"].parameter_uncertainty
    assert pa == b.drivers["revenue_growth"].parameter_uncertainty
    assert pa.draws_loc != c.drivers["revenue_growth"].parameter_uncertainty.draws_loc
    assert pa.method == "nonparametric_bootstrap" and pa.draws == EST.bootstrap_draws
    assert len(pa.draws_loc) == len(pa.draws_scale) == EST.persisted_param_draws and pa.se_loc > 0 and pa.se_scale > 0
    assert a.seed == 11 and a.drivers["revenue_growth"].specs["pooled_t"].param_se > 0


def test_bootstrap_degenerate_small_n():
    load, as_of = company(years=(2023, 2024))
    d = est(load, as_of).distributions.drivers["revenue_growth"]
    assert d.parameter_uncertainty.method == "analytic_only"
    assert "BOOTSTRAP_DEGENERATE_N_LT_2" in d.parameter_uncertainty.flags


def test_uncertainty_types_kept_separate():
    load, as_of = cyclical_company()
    d = est(load, as_of).distributions.drivers["ebit_margin"]
    assert set(d.uncertainty) == {"process", "parameter", "regime", "model", "data"}   # SPEC §8.1


def test_provenance_refs_resolve_to_snapshot_records():
    load, as_of = cyclical_company()
    r = est(load, as_of)
    known = {f"snapshot:{f.source_id}:{f.statement_type}.{f.field_name}@{f.period_end}[{f.basis}]#{f.revision_id or '-'}"
             for f in r.snapshot.financials}
    known |= {f"snapshot:market:{m.source_id}@{m.timestamp.isoformat()}" for m in r.snapshot.market}
    for d in r.distributions.drivers.values():
        for o in d.observations:
            assert o.refs and set(o.refs) <= known, (d.name, o.year)
    g = r.distributions.drivers["revenue_growth"].observations[-1]
    assert any("@2023-12-31" in x for x in g.refs) and any("@2024-12-31" in x for x in g.refs)


def test_pinball():
    assert pinball({"0.5": 1.0}, 3.0) == pytest.approx(1.0)
    assert pinball({"0.1": 0.0, "0.9": 0.0}, 1.0) == pytest.approx((0.1 + 0.9) / 2)


def test_inverse_transforms_stable_at_extreme_z():
    from vms.drivers.transforms import inverse
    for z in (-1e6, -800.0, 800.0, 1e6):
        assert -0.8 <= min(max(inverse("log1p", z, -0.8, 3.0), -0.8), 3.0) <= 3.0
        assert 0.0 <= inverse("logit", z, 0.0, 1.0) <= 1.0
    assert inverse("logit", 0.0, -1.0, 1.0) == 0.0
