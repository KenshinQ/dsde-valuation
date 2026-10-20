"""Rolling-origin, past-only walk-forward diagnostics and model selection (SPEC §7.3, §15.1).
WALK-FORWARD-ORIGINS-v1, MODEL-SELECTION-WF-v1.

For each fiscal year y of the run's history (as known at the run as_of):
1. origin_as_of = first publication time of FY y revenue (the moment FY y became known).
2. Rebuild the PIT snapshot AT origin_as_of from the full dataset. build_snapshot filters by known-at
   time, so no later publication, restatement or corporate action is visible.
3. Re-infer regimes and fit every driver spec on that origin snapshot only.
4. Score the predictive quantiles for FY y+1 against its value as known at the run as_of
   (pinball loss and central-interval coverage in transformed space). The regime transition
   forecast (posterior x transition matrix) is scored with the Brier score against the later
   period's filtered posterior.
Selection per driver = minimum mean pinball over >= min_origins scored origins; otherwise the
configured default spec (flagged). In-sample fit is computed for reference and never used.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
from pydantic import BaseModel, ConfigDict

from vms.data.io import LoadResult
from vms.drivers.definitions import DEFINITIONS
from vms.drivers.distributions import SPECS, fit_specs, observations, pinball, realized_z
from vms.drivers.history import AnnualHistory, extract_annual
from vms.pit.snapshot import PITSnapshot, build_snapshot
from vms.regimes import RegimeResult, infer_regimes
from vms.schemas.config import DriverProfile, EstimationConfig, RegimeConfig

WALK_FORWARD_VERSION = "WF-1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OriginRecord(_M):
    origin_year: int
    origin_as_of: datetime
    train_years: list[int]
    target_year: int
    drivers: dict[str, dict]
    regime: dict | None


class WalkForwardReport(_M):
    version: str = WALK_FORWARD_VERSION
    protocol: str
    origins: list[OriginRecord]
    per_driver: dict[str, dict]
    regime: dict


def state_weights(reg: RegimeResult) -> dict[int, dict[str, float]]:
    """REGIME-ANNUAL-LABEL-v1: FY y <- posterior at y-12-31, else the last period within FY y."""
    out: dict[int, dict[str, float]] = {}
    for h in reg.history:
        y = h.period_end.year
        if y not in out or h.period_end >= max(p.period_end for p in reg.history if p.period_end.year == y):
            out[y] = dict(h.probabilities)
    return out


def origin_times(snap: PITSnapshot, history: AnnualHistory) -> dict[int, datetime]:
    out = {}
    for y in history.years:
        recs = [f for f in snap.financials if f.field_name == "revenue" and f.period_end == date(y, 12, 31)
                and f.formula is None]
        if recs:
            out[y] = min(v.published_at for r in recs for v in r.version_history)
    return out


def _brier(p: dict[str, float], r: dict[str, float]) -> float:
    return float(sum((p[s] - r[s]) ** 2 for s in p))


def walk_forward(load: LoadResult, *, instrument_id: str, snap: PITSnapshot, history: AnnualHistory,
                 regimes: RegimeResult, profile: DriverProfile, est: EstimationConfig,
                 reg_cfg: RegimeConfig) -> WalkForwardReport:
    wf = est.walk_forward
    states = list(reg_cfg.states)
    q_lo, q_hi = str(wf.quantiles[0]), str(wf.quantiles[-1])
    times = origin_times(snap, history)
    hist_by_period = {h.period_end: h for h in regimes.history}
    origins: list[OriginRecord] = []
    for y in history.years:
        if y + 1 not in history.years or y not in times:
            continue
        t = times[y]
        so, _, _ = build_snapshot(instrument_id=instrument_id, as_of=t, financial=load.financial, market=load.market,
                                  corporate_actions=load.corporate_actions, sources=load.sources,
                                  classifications=load.classifications)
        assert all(f.published_at <= t for f in so.financials), "walk-forward origin saw post-origin data"
        ho = extract_annual(so)
        if len(ho.years) < wf.min_train_years or max(ho.years, default=0) > y:
            continue
        ro = infer_regimes(so.financials, as_of=t, cfg=reg_cfg)
        sw = state_weights(ro)
        drv: dict[str, dict] = {}
        for spec in profile.drivers:
            real, _ = DEFINITIONS[spec.name].fn(history, y + 1)
            if real is None:
                continue
            obs = observations(ho, spec, sw, states, est)
            if any(o.year > y for o in obs):
                raise AssertionError(f"{spec.name}: training observation after origin year {y}")
            fits, bench, _ = fit_specs(obs, spec, states, ro.next_year, est)
            zr = realized_z(spec, real, est)
            allf = {**fits, **bench}
            drv[spec.name] = {
                "n_train_obs": len(obs), "realized_value": real, "realized_z": zr,
                "pinball": {k: pinball(f.quantiles_z, zr) for k, f in allf.items()},
                "covered": {k: bool(f.quantiles_z[q_lo] <= zr <= f.quantiles_z[q_hi]) for k, f in fits.items()},
                "abs_err_median": {k: abs(f.quantiles_z["0.5"] - zr) if "0.5" in f.quantiles_z else None
                                   for k, f in allf.items()},
                "forecast_quantiles": {k: f.quantiles for k, f in allf.items()},
            }
        rr = None
        if ro.current.period_end is not None:
            tgt = date(ro.current.period_end.year + 1, ro.current.period_end.month, ro.current.period_end.day)
            real_p = hist_by_period.get(tgt)
            if real_p is not None:
                u = {s: 1 / len(states) for s in states}
                rr = {"origin_period": ro.current.period_end.isoformat(), "target_period": tgt.isoformat(),
                      "forecast": ro.next_year, "realized": real_p.probabilities,
                      "brier": {"transition_model": _brier(ro.next_year, real_p.probabilities),
                                "persistence": _brier(ro.current.probabilities, real_p.probabilities),
                                "uniform": _brier(u, real_p.probabilities)}}
        origins.append(OriginRecord(origin_year=y, origin_as_of=t, train_years=ho.years, target_year=y + 1,
                                    drivers=drv, regime=rr))
    per_driver: dict[str, dict] = {}
    for spec in profile.drivers:
        recs = [o.drivers[spec.name] for o in origins if spec.name in o.drivers]
        n = len(recs)
        mean_pb = {k: float(np.mean([r["pinball"][k] for r in recs])) for k in [*SPECS, "naive_last"]
                   if n and all(k in r["pinball"] for r in recs)}
        cov = {k: float(np.mean([r["covered"][k] for r in recs])) for k in SPECS if n}
        if n >= wf.min_origins:
            best = min(SPECS, key=lambda k: (mean_pb[k], k != wf.default_spec))
            sel = {"selected_spec": best, "rule": "min mean walk-forward pinball (MODEL-SELECTION-WF-v1)",
                   "n_scored_origins": n, "flags": []}
        else:
            sel = {"selected_spec": wf.default_spec, "rule": "default spec: too few scored origins",
                   "n_scored_origins": n, "flags": ["SELECTION_DEFAULT_INSUFFICIENT_ORIGINS"]}
        if n and "naive_last" in mean_pb and mean_pb["naive_last"] < mean_pb[sel["selected_spec"]]:
            sel["flags"] = [*sel["flags"], "NAIVE_BENCHMARK_BETTER"]   # reported, not hidden (point benchmark)
        per_driver[spec.name] = {"n_scored_origins": n, "mean_pinball": mean_pb, "central_interval_coverage": cov,
                                 "nominal_central_coverage": wf.quantiles[-1] - wf.quantiles[0], "selection": sel}
    rs = [o.regime for o in origins if o.regime]
    regime = {"n_scored": len(rs),
              "mean_brier": ({k: float(np.mean([r["brier"][k] for r in rs])) for k in rs[0]["brier"]} if rs else {}),
              "note": "diagnostic only; the rule-based classifier has no fitted parameters to select"}
    return WalkForwardReport(protocol=__doc__.strip().split("\n\n")[1], origins=origins, per_driver=per_driver,
                             regime=regime)


def in_sample_pinball(fits_obs_z: list[float], fits: dict) -> dict[str, float]:
    """Reference only (never used for selection): mean pinball of each spec on its own training data."""
    if not fits_obs_z:
        return {}
    return {k: float(np.mean([pinball(f.quantiles_z, z) for z in fits_obs_z])) for k, f in fits.items()}
