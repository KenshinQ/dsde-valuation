"""Correlated path sampler (SPEC §8.2–8.3). PATH-SAMPLER-v1.

Per path: sample parameters → initial state → annual transitions → correlated drivers
conditional on state (and lag for persistence_t) → enforce constraints → emit / reject.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats

from vms.assumptions import cite
from vms.drivers.distributions import DistributionModel, DriverDistribution, SPECS
from vms.drivers.transforms import inverse
from vms.regimes import RegimeResult
from vms.sampling.dependence import cholesky_psd, estimate_dependence, gaussian_copula_shocks
from vms.sampling.schemas import (INVALID_REASON_CODES, InvalidPathSummary, MCDiagnostics, PathRecord,
                                  SimulationBundle, YearDrivers)
from vms.schemas.config import DriverProfile, EstimationConfig, MonteCarloConfig
from vms.seeding import stream_rng

SAMPLER_VERSION = "PATH-SAMPLER-1"


class SamplingGateError(RuntimeError):
    """Raised when invalid-path fraction exceeds the configured max in production (INVALID-PATH-FRACTION-GATE-v1)."""




def _hash_obj(obj: Any) -> str:
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _categorical(rng: np.random.Generator, probs: Mapping[str, float], states: Sequence[str]) -> str:
    p = np.array([probs[s] for s in states], dtype=float)
    p = np.clip(p, 0, None)
    p = p / p.sum() if p.sum() > 0 else np.full(len(states), 1 / len(states))
    return states[int(rng.choice(len(states), p=p))]


def _dirichlet_rows(rng: np.random.Generator, alpha: Sequence[Sequence[float]]) -> np.ndarray:
    rows = []
    for a in alpha:
        a = np.asarray(a, dtype=float)
        a = np.clip(a, 1e-12, None)
        rows.append(rng.dirichlet(a))
    return np.asarray(rows)


def _param_draw(dd: DriverDistribution, rng: np.random.Generator
                ) -> tuple[float, float, int | None, list[str]]:
    """Legacy independent draw (tests); production paths use _param_draw_coupled."""
    sel = dd.specs[dd.selected_spec]
    pu = dd.parameter_uncertainty
    flags: list[str] = []
    if pu.method == "nonparametric_bootstrap" and pu.draws_loc and pu.draws_scale:
        i = int(rng.integers(0, len(pu.draws_loc)))
        return float(pu.draws_loc[i]), max(float(pu.draws_scale[i]), 1e-12), i, flags
    flags.append("PARAM_POINT_ESTIMATE")
    return float(sel.loc), max(float(sel.scale), 1e-12), None, flags


def _param_draw_coupled(dd: DriverDistribution, shared_i: int | None
                        ) -> tuple[float, float, int | None, list[str]]:
    """Use shared bootstrap index when this driver has draws; else point estimate."""
    sel = dd.specs[dd.selected_spec]
    pu = dd.parameter_uncertainty
    flags: list[str] = []
    if (shared_i is not None and pu.method == "nonparametric_bootstrap"
            and pu.draws_loc and pu.draws_scale and shared_i < len(pu.draws_loc)):
        return float(pu.draws_loc[shared_i]), max(float(pu.draws_scale[shared_i]), 1e-12), shared_i, flags
    flags.append("PARAM_POINT_ESTIMATE")
    return float(sel.loc), max(float(sel.scale), 1e-12), None, flags


def _regime_params_for_path(dd: DriverDistribution, draw_loc: float, draw_scale: float
                            ) -> dict[str, tuple[float, float]]:
    """Shift regime-conditional params by the pooled bootstrap draw relative to the point pooled loc/scale."""
    rt = dd.specs["regime_t"]
    point_loc, point_scale = float(rt.loc), max(float(rt.scale), 1e-12)
    out: dict[str, tuple[float, float]] = {}
    for r in rt.regime or []:
        out[r.state] = (float(r.loc) + (draw_loc - point_loc),
                       max(float(r.scale) * (draw_scale / point_scale), 1e-12))
    return out


def _to_raw(dd: DriverDistribution, z: float) -> float:
    return min(max(inverse(dd.transform, z, dd.lower, dd.upper), dd.lower), dd.upper)


def _enforce_year(raw: dict[str, float], z: dict[str, float], dist: DistributionModel
                  ) -> tuple[dict[str, float], dict[str, float], list[str], str | None]:
    """Clip + soft margin repair. Returns (raw, z, flags, hard_reason_or_None)."""
    flags: list[str] = []
    for name, dd in dist.drivers.items():
        v = raw[name]
        if not math.isfinite(v) or not math.isfinite(z[name]):
            return raw, z, flags, "NONFINITE_DRAW"
        if v < dd.lower - 1e-12 or v > dd.upper + 1e-12:
            return raw, z, flags, "BOUND_VIOLATION"
        if name == "revenue_growth" and v <= -1.0 + 1e-15:
            return raw, z, flags, "GROWTH_UNDEFINED"
    if "ebit_margin" in raw and "gross_margin" in raw and raw["ebit_margin"] > raw["gross_margin"] + 1e-12:
        raw = dict(raw)
        z = dict(z)
        raw["ebit_margin"] = raw["gross_margin"]
        dd = dist.drivers["ebit_margin"]
        # recompute z at the repaired raw
        from vms.drivers.transforms import forward
        x = min(max(raw["ebit_margin"], dd.lower), dd.upper)
        if dd.transform == "logit":
            p = min(max((x - dd.lower) / (dd.upper - dd.lower), 1e-9), 1 - 1e-9)
            z["ebit_margin"] = math.log(p / (1 - p))
        else:
            z["ebit_margin"] = forward(dd.transform, x, dd.lower, dd.upper)
        flags.append("MARGIN_ORDER_REPAIRED")
    return raw, z, flags, None


def _selected_loc_scale(dd: DriverDistribution, state: str, draw_loc: float, draw_scale: float,
                       regime_shift: dict[str, tuple[float, float]] | None,
                       lag_z: float | None) -> tuple[float, float]:
    sel = dd.selected_spec
    if sel == "persistence_t":
        assert lag_z is not None
        return lag_z, draw_scale
    if sel == "regime_t" and regime_shift is not None and state in regime_shift:
        return regime_shift[state]
    if sel == "prior_only":
        return dd.prior_loc_z, dd.prior_scale_z
    # pooled_t / pooled_empirical / fallback: use path draw (shrunk pooled)
    return draw_loc, draw_scale


def _shock_to_z(dd: DriverDistribution, loc: float, scale: float, shock: float) -> float:
    """Map a Student-t-calibrated shock through the selected family."""
    sel = dd.selected_spec
    fit = dd.specs[sel]
    if fit.family == "empirical" and fit.residuals:
        # shock is t-distributed; map via its CDF to uniform then empirical quantile
        df = fit.df or 4.0
        u = float(np.clip(stats.t.cdf(shock, df), 1e-12, 1 - 1e-12))
        r = float(np.quantile(fit.residuals, u))
        return loc + scale * r
    return loc + scale * shock


def _central_path(regimes: RegimeResult, dist: DistributionModel, years: Sequence[int],
                  states: Sequence[str]) -> PathRecord:
    """Most-likely state path + selected-spec medians (q=0.5 / loc); no parameter or process noise."""
    P = np.asarray(regimes.transitions.mean, dtype=float)
    state = max(states, key=lambda s: regimes.current.probabilities[s])
    lag_z = {n: (dd.observations[-1].z if dd.observations else dd.prior_loc_z)
             for n, dd in dist.drivers.items()}
    out_years: list[YearDrivers] = []
    for i, y in enumerate(years):
        if i:
            state = states[int(np.argmax(P[states.index(state)]))]
        raw: dict[str, float] = {}
        zmap: dict[str, float] = {}
        flags: list[str] = []
        for name, dd in dist.drivers.items():
            fit = dd.specs[dd.selected_spec]
            if dd.selected_spec == "persistence_t":
                z = lag_z[name]
            elif dd.selected_spec == "regime_t" and fit.regime:
                rp = {r.state: r for r in fit.regime}
                z = rp[state].loc if state in rp else fit.loc
            else:
                z = fit.loc
            v = _to_raw(dd, z)
            raw[name] = v
            zmap[name] = z
            lag_z[name] = z
        raw, zmap, f2, reason = _enforce_year(raw, zmap, dist)
        assert reason is None, reason
        flags.extend(f2)
        out_years.append(YearDrivers(year_index=i + 1, state=state, drivers=raw, drivers_z=zmap, flags=flags))
    return PathRecord(
        path_id="central", kind="central", valid=True, years=out_years,
        parameter_draw_index={n: None for n in dist.drivers}, transition_seed_tag="central_argmax",
        flags=["CENTRAL_FROM_SELECTED"],
        assumptions=cite("CENTRAL-FROM-SELECTED-v1", "PATH-SAMPLER-v1"))


def _one_path(path_i: int, *, regimes: RegimeResult, dist: DistributionModel, years: Sequence[int],
              states: Sequence[str], chol: np.ndarray, names: Sequence[str], df: float,
              seed: int, parameter_mode: str = "resampled") -> PathRecord | InvalidPathSummary:
    rng = stream_rng(seed, f"path:{path_i}")
    # --- parameter uncertainty: ONE shared bootstrap index across drivers (PARAM-BOOTSTRAP-COUPLED-v1)
    # parameter_mode="fixed" => point estimates only (process uncertainty remains)
    draw_idx: dict[str, int | None] = {}
    path_loc: dict[str, float] = {}
    path_scale: dict[str, float] = {}
    regime_shift: dict[str, dict[str, tuple[float, float]]] = {}
    pflags: list[str] = ["PARAM_BOOTSTRAP_COUPLED"] if parameter_mode != "fixed" else ["PARAM_FIXED_POINT"]
    boot_lens = [len(dd.parameter_uncertainty.draws_loc)
                 for dd in dist.drivers.values()
                 if dd.parameter_uncertainty.method == "nonparametric_bootstrap" and dd.parameter_uncertainty.draws_loc]
    if parameter_mode == "fixed":
        shared_i = None
        pflags.append("PARAM_POINT_ESTIMATE_ALL")
    else:
        shared_i = int(rng.integers(0, min(boot_lens))) if boot_lens else None
        if shared_i is None:
            pflags.append("PARAM_POINT_ESTIMATE_ALL")
    for name, dd in dist.drivers.items():
        loc, scale, idx, fl = _param_draw_coupled(dd, shared_i)
        draw_idx[name] = idx
        path_loc[name] = loc
        path_scale[name] = scale
        pflags.extend(fl)
        if dd.selected_spec == "regime_t":
            regime_shift[name] = _regime_params_for_path(dd, loc, scale)
    # --- transitions: Dirichlet draw of the posterior
    P = _dirichlet_rows(rng, regimes.transitions.posterior_alpha)
    state = _categorical(rng, regimes.current.probabilities, states)
    lag_z = {n: (dd.observations[-1].z if dd.observations else dd.prior_loc_z)
             for n, dd in dist.drivers.items()}
    out_years: list[YearDrivers] = []
    for i, _y in enumerate(years):
        if i:
            state = _categorical(rng, {s: float(P[states.index(state)][j]) for j, s in enumerate(states)}, states)
        try:
            shocks = gaussian_copula_shocks(rng, chol, df)
        except Exception as e:  # noqa: BLE001
            return InvalidPathSummary(path_id=f"mc:{path_i}", reason="DEPENDENCE_DRAW_FAILED",
                                      year_index=i + 1, detail=str(e)[:200])
        raw: dict[str, float] = {}
        zmap: dict[str, float] = {}
        for j, name in enumerate(names):
            dd = dist.drivers[name]
            loc, scale = _selected_loc_scale(dd, state, path_loc[name], path_scale[name],
                                             regime_shift.get(name), lag_z[name])
            z = _shock_to_z(dd, loc, scale, float(shocks[j]))
            raw[name] = _to_raw(dd, z)
            zmap[name] = z
        raw, zmap, yflags, reason = _enforce_year(raw, zmap, dist)
        if reason is not None:
            return InvalidPathSummary(path_id=f"mc:{path_i}", reason=reason, year_index=i + 1, detail=None)
        for name in names:
            lag_z[name] = zmap[name]
        out_years.append(YearDrivers(year_index=i + 1, state=state, drivers=raw, drivers_z=zmap, flags=yflags))
    return PathRecord(
        path_id=f"mc:{path_i}", kind="monte_carlo", valid=True, years=out_years,
        parameter_draw_index=draw_idx, transition_seed_tag=f"path:{path_i}",
        flags=sorted(set(pflags)), assumptions=cite("PATH-SAMPLER-v1", "PATH-CONSTRAINTS-v1",
                                                      "PARAM-UNCERTAINTY-BOOTSTRAP-v1", "PARAM-BOOTSTRAP-COUPLED-v1",
                                                      "DRIVER-DEPENDENCE-v1"))


def _key_stats(paths: Sequence[PathRecord], names: Sequence[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not paths:
        return out
    # year-1 driver means + share of DETERIORATING in year 1
    for name in names:
        xs = np.array([p.years[0].drivers[name] for p in paths if p.years], dtype=float)
        if xs.size == 0:
            continue
        out[f"year1.{name}"] = {
            "mean": float(xs.mean()), "std": float(xs.std(ddof=1)) if xs.size > 1 else 0.0,
            "mcse": float(xs.std(ddof=1) / math.sqrt(xs.size)) if xs.size > 1 else 0.0,
            "p05": float(np.quantile(xs, 0.05)), "p50": float(np.quantile(xs, 0.5)),
            "p95": float(np.quantile(xs, 0.95)), "n": float(xs.size),
        }
    det = np.array([1.0 if p.years[0].state == "DETERIORATING" else 0.0 for p in paths if p.years])
    if det.size:
        out["year1.frac_DETERIORATING"] = {
            "mean": float(det.mean()), "std": float(det.std(ddof=1)) if det.size > 1 else 0.0,
            "mcse": float(det.std(ddof=1) / math.sqrt(det.size)) if det.size > 1 else 0.0,
            "p05": float(np.quantile(det, 0.05)), "p50": float(np.quantile(det, 0.5)),
            "p95": float(np.quantile(det, 0.95)), "n": float(det.size),
        }
    return out


def simulate_paths(*, regimes: RegimeResult, distributions: DistributionModel, profile: DriverProfile,
                   n_paths: int, n_years: int, seed: int, mc: MonteCarloConfig, est: EstimationConfig,
                   base_year: int, provenance: dict[str, Any] | None = None,
                   check_seed_stability: bool = True,
                   mode: str = "production", override_reason: str | None = None,
                   parameter_mode: str = "resampled") -> SimulationBundle:
    """Build a reproducible SimulationBundle. Independent sampling of material blocks is prohibited."""
    if n_paths <= 0 or n_years <= 0:
        raise ValueError("n_paths and n_years must be positive")
    states = list(regimes.current.states)
    names = [d.name for d in profile.drivers]
    assert list(distributions.drivers) == names or set(distributions.drivers) == set(names)
    names = list(distributions.drivers)
    dep = estimate_dependence(distributions, prior_strength=mc.correlation_prior_strength,
                              min_years=mc.min_correlation_years, states=states)
    chol = cholesky_psd(np.asarray(dep.correlation, dtype=float))
    years = list(range(base_year + 1, base_year + 1 + n_years))
    central = _central_path(regimes, distributions, years, states)
    valid: list[PathRecord] = []
    invalid: list[InvalidPathSummary] = []
    df = est.student_t_df
    if parameter_mode not in ("resampled", "fixed"):
        raise ValueError(f"parameter_mode must be 'resampled' or 'fixed'; got {parameter_mode!r}")
    for i in range(n_paths):
        r = _one_path(i, regimes=regimes, dist=distributions, years=years, states=states, chol=chol,
                      names=names, df=df, seed=seed, parameter_mode=parameter_mode)
        if isinstance(r, InvalidPathSummary):
            invalid.append(r)
        else:
            valid.append(r)
    by_reason = {c: 0 for c in INVALID_REASON_CODES}
    for inv in invalid:
        by_reason[inv.reason] = by_reason.get(inv.reason, 0) + 1
    frac = len(invalid) / n_paths
    dflags: list[str] = []
    if frac > mc.max_invalid_path_fraction:
        dflags.append("INVALID_PATH_FRACTION_EXCEEDED")
    stats_map = _key_stats(valid, names)
    repeated_diff = None
    repeated_ok = None
    if check_seed_stability and n_paths >= 10:
        # re-run with the same seed: first path must match exactly
        r0 = _one_path(0, regimes=regimes, dist=distributions, years=years, states=states, chol=chol,
                       names=names, df=df, seed=seed, parameter_mode=parameter_mode)
        r0b = _one_path(0, regimes=regimes, dist=distributions, years=years, states=states, chol=chol,
                        names=names, df=df, seed=seed, parameter_mode=parameter_mode)
        if isinstance(r0, PathRecord) and isinstance(r0b, PathRecord):
            repeated_ok = r0.model_dump() == r0b.model_dump()
            # different seed should move year-1 revenue_growth mean
            alt = [_one_path(i, regimes=regimes, dist=distributions, years=years, states=states, chol=chol,
                             names=names, df=df, seed=seed + 1, parameter_mode=parameter_mode)
                   for i in range(min(n_paths, 50))]
            a = [p.years[0].drivers["revenue_growth"] for p in alt if isinstance(p, PathRecord)]
            b = [p.years[0].drivers["revenue_growth"] for p in valid[:len(a)]]
            if a and b:
                repeated_diff = abs(float(np.mean(a)) - float(np.mean(b)))
        if repeated_ok is False:
            dflags.append("SEED_REPRODUCIBILITY_FAILED")
    diagnostics = MCDiagnostics(
        n_paths_requested=n_paths, n_paths_valid=len(valid), n_paths_invalid=len(invalid),
        invalid_fraction=frac, invalid_by_reason={k: v for k, v in by_reason.items() if v},
        key_statistics=stats_map, repeated_seed_max_abs_diff=repeated_diff,
        repeated_seed_stable=repeated_ok, flags=dflags)
    param_snap = {
        "parameter_mode": parameter_mode,
        "distribution_version": distributions.distribution_version,
        "selected_specs": {n: d.selected_spec for n, d in distributions.drivers.items()},
        "regime_model": distributions.regime_model,
        "distributions_seed": distributions.seed,
        "dependence_version": dep.version,
        "dependence_hash": _hash_obj(dep.model_dump(mode="json")),
        "transitions_hash": _hash_obj(regimes.transitions.model_dump(mode="json")),
        "posterior_hash": _hash_obj(regimes.current.model_dump(mode="json")),
    }
    flags = list(dep.flags)
    if any(d.low_confidence for d in distributions.drivers.values()):
        flags.append("DRIVER_LOW_CONFIDENCE_PRESENT")
    override = None
    if "INVALID_PATH_FRACTION_EXCEEDED" in dflags:
        if mode == "production":
            raise SamplingGateError(
                f"invalid path fraction {frac:.4g} exceeds max_invalid_path_fraction "
                f"{mc.max_invalid_path_fraction} (INVALID-PATH-FRACTION-GATE-v1). "
                f"Fix the sampler/data, or rerun with --mode exploratory --override-reason '...'")
        if not (override_reason or "").strip():
            raise SamplingGateError(
                "invalid path fraction exceeded: exploratory mode requires --override-reason")
        override = override_reason.strip()
        flags.append("INVALID_PATH_FRACTION_OVERRIDDEN")
    bundle = SimulationBundle(
        sampler_version=SAMPLER_VERSION, seed=seed, n_paths=n_paths, n_years=n_years, base_year=base_year,
        years=years, dependence=dep, central=central, paths=valid, invalid=invalid, diagnostics=diagnostics,
        parameter_snapshot=param_snap, provenance=dict(provenance or {}),
        assumptions=cite("PATH-SAMPLER-v1", "PATH-CONSTRAINTS-v1", "DRIVER-DEPENDENCE-v1",
                         "CENTRAL-FROM-SELECTED-v1", "PARAM-UNCERTAINTY-BOOTSTRAP-v1",
                         "PARAM-BOOTSTRAP-COUPLED-v1", "DEP-BLOCK-BOOTSTRAP-DEFER-v1",
                         "REGIME-TRANSITION-DIRICHLET-v1", "REGIME-CLOCK-MISMATCH-v1",
                         "INVALID-PATH-FRACTION-GATE-v1", "COVERAGE-MISCAL-NO-AUTOSWITCH-v1"),
        flags=sorted(set(flags)))
    if override is not None:
        prov = dict(bundle.provenance)
        prov["invalid_path_fraction_override"] = override
        bundle = bundle.model_copy(update={"provenance": prov})
    return bundle
