"""Conditional driver distributions (SPEC §7.3, §8.1). Phase 3, DRIVER-DIST-v1.

Per driver, in TRANSFORMED space z = T(x) (DRIVER-TRANSFORMS-v1):
- Robust pooled estimates: loc_hat = median(z), s_hat = 1.4826 x MAD(z).
- Shrinkage toward the profile prior (PRIORS-GLOBAL-v1) with k = prior_strength pseudo-observations:
      loc = (n loc_hat + k mu0) / (n + k);   s^2 = (n_d s_hat^2 + k s0^2) / (n_d + k),  n_d = n - 1.
- Regime-conditional: observation weights w_i(s) = fundamental posterior of FY i (REGIME-ANNUAL-LABEL-v1).
  With n_s = sum_i w_i(s) >= min_regime_support, weighted median/MAD shrink toward the pooled estimate with
  k_regime. Otherwise the pooled estimate is used (REGIME_POOLED_FALLBACK).
- Families (DRIVER-FAMILY-v1): Student-t(df) or empirical standardized residuals.
- Parameter uncertainty (PARAM-UNCERTAINTY-BOOTSTRAP-v1): bootstrap of the whole pooled estimator.
- Specs (model uncertainty): prior_only, pooled_t, pooled_empirical, regime_t, persistence_t (last obs + shrunk dispersion); naive_last is a
  benchmark only. Selection is done by walk-forward (vms.drivers.walk_forward), never in-sample.
Quantiles are back-transformed to raw units and clipped to bounds (monotone => quantiles map).
Dependence between drivers is Phase 4 (DRIVER-DEPENDENCE-PHASE4-v1).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy import stats

from vms.drivers.definitions import DEFINITIONS
from vms.drivers.history import AnnualHistory
from vms.drivers.transforms import forward, inverse
from vms.schemas.config import DriverSpec, EstimationConfig
from vms.seeding import stream_rng

DISTRIBUTION_VERSION = "DRIVER-DIST-1"
SPECS = ("prior_only", "pooled_t", "pooled_empirical", "regime_t", "persistence_t")
BENCHMARKS = ("naive_last",)
MAD_K = 1.4826


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DistObservation(_M):
    year: int
    value: float
    z: float
    state_weights: dict[str, float]
    refs: list[str]
    flags: list[str]


class RegimeParams(_M):
    state: str
    n_eff: float
    loc: float
    scale: float
    method: str
    flags: list[str]


class SpecFit(_M):
    spec_id: str
    family: str
    loc: float
    scale: float
    df: float | None
    residuals: list[float] | None
    regime: list[RegimeParams] | None
    param_se: float
    quantiles_z: dict[str, float]
    quantiles: dict[str, float]
    flags: list[str]


class ParamUncertainty(_M):
    method: str
    draws: int
    se_loc: float
    se_scale: float
    loc_q05_q95: tuple[float, float]
    scale_q05_q95: tuple[float, float]
    draws_loc: list[float]
    draws_scale: list[float]
    flags: list[str]


class DriverDistribution(_M):
    name: str
    role: str
    transform: str
    lower: float
    upper: float
    n_obs: int
    observations: list[DistObservation]
    prior_loc_z: float
    prior_scale_z: float
    loc_hat: float | None
    scale_hat: float | None
    shrink_weight_data: float
    specs: dict[str, SpecFit]
    benchmarks: dict[str, SpecFit]
    selected_spec: str
    selection: dict
    parameter_uncertainty: ParamUncertainty
    uncertainty: dict
    low_confidence: bool
    flags: list[str]


# ---------------------------------------------------------------- robust helpers
def wmedian(x: np.ndarray, w: np.ndarray) -> float:
    o = np.argsort(x)
    x, w = x[o], w[o]
    c = np.cumsum(w)
    half = c[-1] / 2
    i = int(np.searchsorted(c, half))
    if math.isclose(c[i], half) and i + 1 < len(x):
        return float((x[i] + x[i + 1]) / 2)
    return float(x[i])


def wmad(x: np.ndarray, w: np.ndarray, m: float) -> float:
    return wmedian(np.abs(x - m), w)


def pooled_fit(z: np.ndarray, mu0: float, s0: float, k: float) -> tuple[float | None, float | None, float, float]:
    """(loc_hat, s_hat, loc, s). Vectorisable logic kept scalar for clarity."""
    n = len(z)
    if n == 0:
        return None, None, mu0, s0
    loc_hat = float(np.median(z))
    s_hat = float(MAD_K * np.median(np.abs(z - loc_hat))) if n >= 2 else None
    loc = (n * loc_hat + k * mu0) / (n + k)
    nd = n - 1
    var = ((nd * s_hat ** 2 if s_hat is not None else 0.0) + k * s0 ** 2) / (nd + k)
    return loc_hat, s_hat, loc, math.sqrt(var)


def _bootstrap(z: np.ndarray, mu0: float, s0: float, k: float, draws: int, keep: int,
               rng: np.random.Generator) -> ParamUncertainty:
    n = len(z)
    if n < 2:
        _, _, loc, s = pooled_fit(z, mu0, s0, k)
        return ParamUncertainty(method="analytic_only", draws=0, se_loc=s / math.sqrt(n + k), se_scale=0.0,
                                loc_q05_q95=(loc, loc), scale_q05_q95=(s, s), draws_loc=[], draws_scale=[],
                                flags=["BOOTSTRAP_DEGENERATE_N_LT_2"])
    idx = rng.integers(0, n, size=(draws, n))
    zz = z[idx]
    med = np.median(zz, axis=1)
    mad = MAD_K * np.median(np.abs(zz - med[:, None]), axis=1)
    loc = (n * med + k * mu0) / (n + k)
    s = np.sqrt(((n - 1) * mad ** 2 + k * s0 ** 2) / (n - 1 + k))
    flags = ["BOOTSTRAP_SMALL_N_UNDERSTATES_UNCERTAINTY"] if n < 5 else []
    return ParamUncertainty(method="nonparametric_bootstrap", draws=draws, se_loc=float(np.std(loc, ddof=1)),
                            se_scale=float(np.std(s, ddof=1)),
                            loc_q05_q95=(float(np.quantile(loc, 0.05)), float(np.quantile(loc, 0.95))),
                            scale_q05_q95=(float(np.quantile(s, 0.05)), float(np.quantile(s, 0.95))),
                            draws_loc=[float(v) for v in loc[:keep]], draws_scale=[float(v) for v in s[:keep]],
                            flags=flags)


def t_mix_quantiles(qs: Sequence[float], comps: list[tuple[float, float, float]], df: float) -> list[float]:
    """Quantiles of a mixture of location-scale t's [(weight, loc, scale)]: vectorised bisection on the CDF."""
    q = np.asarray(qs, dtype=float)
    lo = np.full_like(q, min(m - 60 * sc for _, m, sc in comps))
    hi = np.full_like(q, max(m + 60 * sc for _, m, sc in comps))
    for _ in range(80):
        mid = (lo + hi) / 2
        c = sum(w * stats.t.cdf((mid - m) / sc, df) for w, m, sc in comps)
        below = c < q
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    return [float(v) for v in (lo + hi) / 2]


# ---------------------------------------------------------------- spec fitting
def observations(history: AnnualHistory, spec: DriverSpec, state_weights: dict[int, dict[str, float]],
                 states: Sequence[str], cfg: EstimationConfig) -> list[DistObservation]:
    d = DEFINITIONS[spec.name]
    out = []
    for y in history.years:
        v, fl = d.fn(history, y)
        if v is None:
            continue
        flags = list(fl)
        x = v
        if not (spec.lower <= v <= spec.upper):
            x = min(max(v, spec.lower), spec.upper)
            flags.append("OBS_CLIPPED_TO_BOUND")
        if spec.transform.value == "logit":
            p = (x - spec.lower) / (spec.upper - spec.lower)
            if p < cfg.boundary_eps or p > 1 - cfg.boundary_eps:
                flags.append("BOUNDARY_OBS")
            p = min(max(p, cfg.boundary_eps), 1 - cfg.boundary_eps)
            z = math.log(p / (1 - p))
        else:
            z = forward(spec.transform.value, x, spec.lower, spec.upper)
        w = state_weights.get(y)
        if w is None:
            w = {s: 1.0 / len(states) for s in states}
            flags.append("NO_REGIME_LABEL_EQUAL_WEIGHTS")
        out.append(DistObservation(year=y, value=v, z=z, state_weights=w, refs=d.refs(history, y),
                                   flags=sorted(set(flags))))
    return out[-cfg.max_history_years:]


def _prior_z(spec: DriverSpec, cfg: EstimationConfig) -> float:
    if spec.prior is None or spec.prior_scale is None:
        raise ValueError(f"driver '{spec.name}': prior and prior_scale are required for distribution estimation "
                         "(add labeled placeholders to the driver profile)")
    if spec.transform.value == "logit":
        p = min(max((spec.prior - spec.lower) / (spec.upper - spec.lower), cfg.boundary_eps), 1 - cfg.boundary_eps)
        return math.log(p / (1 - p))
    return forward(spec.transform.value, spec.prior, spec.lower, spec.upper)


def _to_raw(spec: DriverSpec, z: float) -> float:
    return min(max(inverse(spec.transform.value, z, spec.lower, spec.upper), spec.lower), spec.upper)


def fit_specs(obs: Sequence[DistObservation], spec: DriverSpec, states: Sequence[str],
              next_state: dict[str, float], cfg: EstimationConfig
              ) -> tuple[dict[str, SpecFit], dict[str, SpecFit], tuple[float | None, float | None, float, float]]:
    """All candidate specs (+ benchmarks) fitted on `obs` only; predictive quantiles for the next year."""
    qs = cfg.walk_forward.quantiles
    df = cfg.student_t_df
    tq = {q: float(stats.t.ppf(q, df)) for q in qs}
    mu0, s0 = _prior_z(spec, cfg), spec.prior_scale
    z = np.array([o.z for o in obs], dtype=float)
    n = len(z)
    k = cfg.prior_strength
    loc_hat, s_hat, loc, s = pooled_fit(z, mu0, s0, k)
    se = s / math.sqrt(n + k)
    sp = math.sqrt(s ** 2 + se ** 2)

    def mk(spec_id, family, l, sc, qz, *, dfv=df, resid=None, regime=None, pse=se, flags=()):  # noqa: ANN001, ANN202
        return SpecFit(spec_id=spec_id, family=family, loc=l, scale=sc, df=dfv, residuals=resid, regime=regime,
                       param_se=pse, quantiles_z={str(q): v for q, v in qz.items()},
                       quantiles={str(q): _to_raw(spec, v) for q, v in qz.items()}, flags=sorted(set(flags)))

    fits: dict[str, SpecFit] = {}
    fits["prior_only"] = mk("prior_only", "student_t", mu0, s0, {q: mu0 + s0 * tq[q] for q in qs}, pse=0.0)
    fits["pooled_t"] = mk("pooled_t", "student_t", loc, s, {q: loc + sp * tq[q] for q in qs},
                          flags=["PRIOR_FALLBACK"] if n == 0 else [])
    if n >= cfg.min_empirical_n and s_hat:
        r = (z - loc_hat) / s_hat
        fits["pooled_empirical"] = mk("pooled_empirical", "empirical", loc, s,
                                      {q: loc + sp * float(np.quantile(r, q)) for q in qs}, dfv=None,
                                      resid=[float(v) for v in r])
    else:
        f = fits["pooled_t"]
        fits["pooled_empirical"] = f.model_copy(update={"spec_id": "pooled_empirical",
                                                        "flags": sorted({*f.flags, "EMPIRICAL_FALLBACK_TO_T"})})
    # regime-conditional
    W = np.array([[o.state_weights[s_] for s_ in states] for o in obs], dtype=float).reshape(n, len(states))
    kr = cfg.regime_prior_strength
    regime: list[RegimeParams] = []
    for j, st in enumerate(states):
        w = W[:, j] if n else np.zeros(0)
        ne = float(w.sum())
        if n and ne >= cfg.min_regime_support:
            lh = wmedian(z, w)
            sh = MAD_K * wmad(z, w, lh)
            nd = max(ne - 1.0, 0.0)
            regime.append(RegimeParams(state=st, n_eff=ne, loc=(ne * lh + kr * loc) / (ne + kr),
                                       scale=math.sqrt((nd * sh ** 2 + kr * s ** 2) / (nd + kr)),
                                       method="conditional_shrunk_to_pooled", flags=[]))
        else:
            regime.append(RegimeParams(state=st, n_eff=ne, loc=loc, scale=s, method="pooled_fallback",
                                       flags=["REGIME_POOLED_FALLBACK"]))
    comps = [(next_state[r.state], r.loc, math.sqrt(r.scale ** 2 + se ** 2)) for r in regime if next_state[r.state] > 0]
    rflags = ["REGIME_POOLED_FALLBACK_ALL"] if all(r.method == "pooled_fallback" for r in regime) else []
    fits["regime_t"] = mk("regime_t", "student_t_mixture", sum(w * m for w, m, _ in comps),
                          math.sqrt(sum(w * (sc ** 2 + m ** 2) for w, m, sc in comps)
                                    - sum(w * m for w, m, _ in comps) ** 2),
                          dict(zip(qs, t_mix_quantiles(qs, comps, df))), regime=regime, flags=rflags)
    # persistence_t: last observation as location + shrunk pooled dispersion (selectable; MODEL-SELECTION-WF-v2)
    if n:
        last = float(z[-1])
        fits["persistence_t"] = mk("persistence_t", "student_t", last, s,
                                   {q: last + sp * tq[q] for q in qs},
                                   flags=["PERSISTENCE_LAST_PLUS_SHRUNK_SCALE"])
    else:
        fits["persistence_t"] = fits["pooled_t"].model_copy(
            update={"spec_id": "persistence_t", "flags": sorted({*fits["pooled_t"].flags, "PRIOR_FALLBACK"})})
    bench: dict[str, SpecFit] = {}
    if n:
        last = float(z[-1])
        bench["naive_last"] = mk("naive_last", "point", last, 0.0, {q: last for q in qs}, dfv=None, pse=0.0)
    return fits, bench, (loc_hat, s_hat, loc, s)


def pinball(qz: dict[str, float], y: float) -> float:
    return float(np.mean([max(float(q) * (y - v), (float(q) - 1) * (y - v)) for q, v in qz.items()]))


def realized_z(spec: DriverSpec, v: float, cfg: EstimationConfig) -> float:
    x = min(max(v, spec.lower), spec.upper)
    if spec.transform.value == "logit":
        p = min(max((x - spec.lower) / (spec.upper - spec.lower), cfg.boundary_eps), 1 - cfg.boundary_eps)
        return math.log(p / (1 - p))
    return forward(spec.transform.value, x, spec.lower, spec.upper)


def estimate_distribution(history: AnnualHistory, spec: DriverSpec, *, state_weights: dict[int, dict[str, float]],
                          states: Sequence[str], next_state: dict[str, float], cfg: EstimationConfig, seed: int,
                          selection: dict, min_history: int) -> DriverDistribution:
    obs = observations(history, spec, state_weights, states, cfg)
    fits, bench, (loc_hat, s_hat, loc, s) = fit_specs(obs, spec, states, next_state, cfg)
    z = np.array([o.z for o in obs], dtype=float)
    n = len(obs)
    k = cfg.prior_strength
    pu = _bootstrap(z, _prior_z(spec, cfg), spec.prior_scale, k, cfg.bootstrap_draws, cfg.persisted_param_draws,
                    stream_rng(seed, f"param_bootstrap:{spec.name}"))
    flags: set[str] = set()
    for o in obs:
        flags.update(f for f in o.flags if f in ("OBS_CLIPPED_TO_BOUND", "BOUNDARY_OBS", "NO_REGIME_LABEL_EQUAL_WEIGHTS"))
    if n == 0:
        flags.update({"PRIOR_FALLBACK", "LOW_CONFIDENCE"})
    elif n < min_history:
        flags.update({"SPARSE_HISTORY_SHRINKAGE", "LOW_CONFIDENCE"})
    if s_hat == 0.0:
        flags.add("DEGENERATE_DISPERSION_PRIOR_SCALE_ONLY")
    sel = selection["selected_spec"]
    flags.update(selection.get("flags", []))
    flags.update(fits[sel].flags)
    uncertainty = {
        "process": {"family": fits[sel].family, "scale_z": fits[sel].scale, "df": fits[sel].df},
        "parameter": {"method": pu.method, "se_loc_z": pu.se_loc, "se_scale_z": pu.se_scale,
                      "predictive_param_se_z": fits[sel].param_se},
        "regime": {"conditional": sel == "regime_t", "next_year_state_probabilities": next_state,
                   "states_with_own_params": [r.state for r in (fits["regime_t"].regime or [])
                                              if r.method != "pooled_fallback"]},
        "model": {"alternatives": list(SPECS), "selected": sel, "rule": selection["rule"]},
        "data": {"n_obs": n, "n_derived_or_flagged": sum(1 for o in obs if o.flags),
                 "clipped": sum("OBS_CLIPPED_TO_BOUND" in o.flags for o in obs),
                 "boundary": sum("BOUNDARY_OBS" in o.flags for o in obs)},
    }
    return DriverDistribution(
        name=spec.name, role=spec.role, transform=spec.transform.value, lower=spec.lower, upper=spec.upper, n_obs=n,
        observations=obs, prior_loc_z=_prior_z(spec, cfg), prior_scale_z=spec.prior_scale, loc_hat=loc_hat,
        scale_hat=s_hat, shrink_weight_data=n / (n + k), specs=fits, benchmarks=bench, selected_spec=sel,
        selection=selection, parameter_uncertainty=pu, uncertainty=uncertainty,
        low_confidence=("LOW_CONFIDENCE" in flags or "LOW_EVAL_SUPPORT" in flags), flags=sorted(flags))


class DistributionModel(_M):
    distribution_version: str = DISTRIBUTION_VERSION
    profile_id: str
    profile_version: str
    bounds_status: str
    estimation_config: dict
    seed: int
    seed_stream: str = "param_bootstrap:<driver>"
    regime_model: dict
    history_years: list[int]
    drivers: dict[str, DriverDistribution]
    assumptions: list[str]


def build_distribution_model(history: AnnualHistory, profile, *, regimes, walk_forward_report,  # noqa: ANN001
                             cfg: EstimationConfig, seed: int) -> DistributionModel:
    from vms.assumptions import cite
    from vms.drivers.walk_forward import in_sample_pinball, state_weights

    states = list(regimes.current.states)
    sw = state_weights(regimes)
    out: dict[str, DriverDistribution] = {}
    for spec in profile.drivers:
        sel = dict(walk_forward_report.per_driver[spec.name]["selection"])
        dd = estimate_distribution(history, spec, state_weights=sw, states=states, next_state=regimes.next_year,
                                   cfg=cfg, seed=seed, selection=sel, min_history=cfg.min_history_years)
        if dd.selected_spec == "pooled_empirical" and "EMPIRICAL_FALLBACK_TO_T" in dd.specs["pooled_empirical"].flags:
            dd = dd.model_copy(update={"flags": sorted({*dd.flags, "SELECTED_EMPIRICAL_UNAVAILABLE_USING_T"})})
        sel["in_sample_pinball_not_used_for_selection"] = in_sample_pinball([o.z for o in dd.observations], dd.specs)
        sel["walk_forward"] = {k: v for k, v in walk_forward_report.per_driver[spec.name].items() if k != "selection"}
        out[spec.name] = dd.model_copy(update={"selection": sel})
    return DistributionModel(
        profile_id=profile.profile_id, profile_version=profile.profile_version, bounds_status=profile.bounds_status,
        estimation_config=cfg.model_dump(mode="json"), seed=seed,
        regime_model={"model_id": regimes.current.model_id, "model_version": regimes.current.model_version,
                      "states": states},
        history_years=history.years, drivers=out,
        assumptions=cite("DRIVER-TRANSFORMS-v1", "DRIVER-DIST-v1", "DRIVER-FAMILY-v1", "PRIORS-GLOBAL-v1",
                         "PARAM-UNCERTAINTY-BOOTSTRAP-v1", "WALK-FORWARD-ORIGINS-v1", "MODEL-SELECTION-WF-v2",
                         "REGIME-ANNUAL-LABEL-v1", "DRIVER-DEPENDENCE-v1", "CENTRAL-FROM-SELECTED-v1", "REGIME-CLOCK-MISMATCH-v1", "INDUSTRY-PRIORS-DEFER-v1", "DRIVER-PRIORS-PLACEHOLDER-v1",
                         "ANNUAL-BASE-v1", "DIVIDEND-T-PLUS-1-v1"))
