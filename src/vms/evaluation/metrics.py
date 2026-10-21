"""Separate-target metrics and calibration (SPEC §17.2–17.3). Never mix IV scoring with price MAE."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np


def _finite(xs: list[float | None]) -> np.ndarray:
    return np.array([x for x in xs if x is not None and math.isfinite(x)], dtype=float)


def point_errors(actual: list[float | None], forecast: list[float | None]) -> dict[str, Any]:
    pairs = [(a, f) for a, f in zip(actual, forecast)
             if a is not None and f is not None and math.isfinite(a) and math.isfinite(f)]
    if not pairs:
        return {"n": 0}
    err = np.array([f - a for a, f in pairs], dtype=float)
    abs_err = np.abs(err)
    return {
        "n": int(len(pairs)),
        "mae": float(abs_err.mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "mean_error": float(err.mean()),
        "median_abs_error": float(np.median(abs_err)),
    }


def pinball_loss(actual: list[float | None], quantile_forecast: list[float | None],
                 tau: float) -> dict[str, Any]:
    """Mean pinball (quantile) loss at level ``tau`` ∈ (0,1)."""
    if not (0.0 < tau < 1.0):
        raise ValueError(f"tau must be in (0,1), got {tau}")
    losses = []
    for a, q in zip(actual, quantile_forecast):
        if a is None or q is None or not (math.isfinite(a) and math.isfinite(q)):
            continue
        u = a - q
        losses.append((tau * u) if u >= 0 else ((tau - 1.0) * u))
    if not losses:
        return {"n": 0, "tau": tau, "mean_pinball": None}
    return {"n": len(losses), "tau": tau, "mean_pinball": float(np.mean(losses))}


def crps_gaussian(actual: list[float | None], mean: list[float | None],
                  std: list[float | None]) -> dict[str, Any]:
    """Closed-form CRPS for N(μ,σ²) predictive distributions (Gneiting & Raftery).

    Used only when a Gaussian predictive summary is declared; otherwise callers
    should leave this block null rather than invent a distribution.
    """
    vals = []
    for a, m, s in zip(actual, mean, std):
        if a is None or m is None or s is None:
            continue
        if not all(math.isfinite(x) for x in (a, m, s)) or s <= 0:
            continue
        z = (a - m) / s
        # Φ and φ via math.erf / gaussian density
        phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
        Phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        vals.append(s * (z * (2.0 * Phi - 1.0) + 2.0 * phi - 1.0 / math.sqrt(math.pi)))
    if not vals:
        return {"n": 0, "mean_crps": None, "family": "gaussian"}
    return {"n": len(vals), "mean_crps": float(np.mean(vals)), "family": "gaussian"}


def quantile_coverage(actual: list[float | None], q_lo: list[float | None], q_hi: list[float | None],
                      nominal: float = 0.8) -> dict[str, Any]:
    """Central-interval coverage: fraction of actuals in [q_lo, q_hi]."""
    hits = []
    for a, lo, hi in zip(actual, q_lo, q_hi):
        if a is None or lo is None or hi is None:
            continue
        if not all(math.isfinite(x) for x in (a, lo, hi)):
            continue
        hits.append(1.0 if lo <= a <= hi else 0.0)
    if not hits:
        return {"n": 0, "nominal": nominal, "coverage": None}
    cov = float(np.mean(hits))
    return {"n": len(hits), "nominal": nominal, "coverage": cov, "abs_gap": abs(cov - nominal)}


def loss_prob_calibration(realized_loss: list[bool | None], forecast_p_loss: list[float | None],
                          bins: int = 5) -> dict[str, Any]:
    """Reliability-style bins: mean forecast p_loss vs empirical loss rate + Brier."""
    pairs = [(r, p) for r, p in zip(realized_loss, forecast_p_loss)
             if r is not None and p is not None and math.isfinite(p)]
    if not pairs:
        return {"n": 0, "bins": []}
    ps = np.array([p for _, p in pairs])
    rs = np.array([1.0 if r else 0.0 for r, _ in pairs])
    edges = np.linspace(0.0, 1.0, bins + 1)
    out_bins = []
    for i in range(bins):
        m = (ps >= edges[i]) & (ps < edges[i + 1] if i < bins - 1 else ps <= edges[i + 1])
        if not m.any():
            continue
        out_bins.append({
            "p_lo": float(edges[i]), "p_hi": float(edges[i + 1]),
            "n": int(m.sum()), "mean_forecast": float(ps[m].mean()), "emp_rate": float(rs[m].mean()),
        })
    return {"n": len(pairs), "bins": out_bins, "brier": float(np.mean((ps - rs) ** 2))}


def hurdle_calibration(realized_ret: list[float | None], forecast_p_exceed: list[float | None],
                       hurdle: float) -> dict[str, Any]:
    hits = []
    for r, p in zip(realized_ret, forecast_p_exceed):
        if r is None or p is None or not math.isfinite(p):
            continue
        hits.append((1.0 if r > hurdle else 0.0, p))
    if not hits:
        return {"n": 0, "hurdle": hurdle}
    emp = float(np.mean([h for h, _ in hits]))
    mean_p = float(np.mean([p for _, p in hits]))
    return {"n": len(hits), "hurdle": hurdle, "emp_exceed_rate": emp, "mean_forecast_p": mean_p,
            "gap": mean_p - emp}


def baseline_comparison(records: list[dict[str, Any]], *, target_key: str,
                        actual_getter, forecast_getter, baseline_getter) -> dict[str, Any]:
    """MAE of primary forecast vs a named baseline on the same actuals."""
    fc = [forecast_getter(r) for r in records]
    bl = [baseline_getter(r) for r in records]
    ac = [actual_getter(r) for r in records]
    return {
        "target": target_key,
        "forecast_errors": point_errors(ac, fc),
        "baseline_errors": point_errors(ac, bl),
        "note": "Lower MAE/RMSE is better; compare on identical realized outcomes.",
    }


def subgroup_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Profile / regime subgroup scorecards (SPEC §17.3 stability by profile/state)."""
    by_profile: dict[str, list] = defaultdict(list)
    by_regime: dict[str, list] = defaultdict(list)
    for r in records:
        prof = str(r.get("profile_id") or r.get("profile") or "UNKNOWN")
        reg = str(r.get("fundamental_regime") or r.get("regime_id") or "UNKNOWN")
        by_profile[prof].append(r)
        by_regime[reg].append(r)

    def _block(groups: dict[str, list]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, recs in sorted(groups.items()):
            px_fc = [(r.get("forecasts") or {}).get("market_price", {}).get("point") for r in recs]
            px_ac = [(r.get("outcomes") or {}).get("market_price", {}).get("raw_close") for r in recs]
            r_fc = [(r.get("forecasts") or {}).get("total_shareholder_return", {}).get("point") for r in recs]
            r_ac = [(r.get("outcomes") or {}).get("total_shareholder_return", {}).get("realized") for r in recs]
            out[name] = {
                "n": len(recs),
                "market_price_errors": point_errors(px_ac, px_fc),
                "tsr_point_errors": point_errors(r_ac, r_fc),
            }
        return out

    return {
        "by_profile": _block(by_profile),
        "by_fundamental_regime": _block(by_regime),
        "note": (
            "Subgroup diagnostics are descriptive stability checks. "
            "They do not authorize ENSEMBLE_CALIBRATED or investment-value claims."
        ),
    }


def score_targets(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score each target family separately from persisted forecast+outcome pairs."""
    # Operating CF
    fc_fcff = [(r.get("forecasts") or {}).get("operating_cash_flow", {}).get("point") for r in records]
    ac_fcff = [(r.get("outcomes") or {}).get("operating_cash_flow", {}).get("fcff_proxy") for r in records]
    q10 = [(r.get("forecasts") or {}).get("operating_cash_flow", {}).get("q10") for r in records]
    q90 = [(r.get("forecasts") or {}).get("operating_cash_flow", {}).get("q90") for r in records]
    mu = [(r.get("forecasts") or {}).get("operating_cash_flow", {}).get("dist_mean") for r in records]
    sd = [(r.get("forecasts") or {}).get("operating_cash_flow", {}).get("dist_std") for r in records]
    cf = {
        "errors": point_errors(ac_fcff, fc_fcff),
        "pinball_q10": pinball_loss(ac_fcff, q10, 0.10),
        "pinball_q90": pinball_loss(ac_fcff, q90, 0.90),
        "coverage_80": quantile_coverage(ac_fcff, q10, q90, nominal=0.8),
        "crps_gaussian": crps_gaussian(ac_fcff, mu, sd),
        "note": "FCFF/CFO forecast errors only — not mixed with price or return scores",
    }
    # Intrinsic: stability vs later re-estimate if present; NEVER price MAE
    iv_fc = [(r.get("forecasts") or {}).get("intrinsic_value", {}).get("point") for r in records]
    iv_later = [(r.get("outcomes") or {}).get("intrinsic_value", {}).get("later_origin_vps") for r in records]
    # Market-price association labeled separately — not IV ground truth
    px_ac = [(r.get("outcomes") or {}).get("market_price", {}).get("raw_close") for r in records]
    iv = {
        "stability_vs_later_origin": point_errors(iv_later, iv_fc),
        "price_mae_forbidden": True,
        "market_price_association_only": {
            "errors": point_errors(px_ac, iv_fc),
            "label": "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH",
            "note": (
                "Association between intrinsic point and realized market price is reported "
                "for transparency only. Future market price is NOT ground truth for intrinsic "
                "value (SPEC §17.2 / §22.4)."
            ),
        },
        "note": "Intrinsic scored via coherence/stability; market price is not the truth target",
    }
    # Market price
    px_fc = [(r.get("forecasts") or {}).get("market_price", {}).get("point") for r in records]
    px = {
        "errors": point_errors(px_ac, px_fc),
        "note": "Market-price forecast errors — separate from intrinsic",
    }
    # Persistence baseline comparison for exit pricing
    px_persist = [
        ((r.get("baselines") or {}).get("current_multiple_persistence") or {}).get("exit_price_point")
        for r in records
    ]
    px["vs_current_multiple_persistence"] = {
        "forecast_errors": point_errors(px_ac, px_fc),
        "baseline_errors": point_errors(px_ac, px_persist),
        "baseline": "current_multiple_persistence",
    }
    # Returns
    r_fc = [(r.get("forecasts") or {}).get("total_shareholder_return", {}).get("point") for r in records]
    r_ac = [(r.get("outcomes") or {}).get("total_shareholder_return", {}).get("realized") for r in records]
    p_loss_fc = [(r.get("forecasts") or {}).get("total_shareholder_return", {}).get("p_loss") for r in records]
    realized_loss = [None if x is None else (x < 0) for x in r_ac]
    ret = {
        "point_errors": point_errors(r_ac, r_fc),
        "loss_probability_calibration": loss_prob_calibration(realized_loss, p_loss_fc),
        "hurdle_calibration": [
            hurdle_calibration(
                r_ac,
                [(r.get("forecasts") or {}).get("total_shareholder_return", {}).get("p_exceed_0")
                 for r in records],
                0.0,
            ),
            hurdle_calibration(
                r_ac,
                [(r.get("forecasts") or {}).get("total_shareholder_return", {}).get("p_exceed_0.08")
                 for r in records],
                0.08,
            ),
        ],
        "note": "TSR under DIVIDEND-NO-REINVEST; separate from CF and intrinsic",
    }
    # Historical-median CF baseline comparison
    hist_fcff = [
        ((r.get("baselines") or {}).get("historical_median") or {}).get("fcff_y1") for r in records
    ]
    baselines_vs = {
        "operating_cash_flow_vs_historical_median": {
            "forecast_errors": point_errors(ac_fcff, fc_fcff),
            "baseline_errors": point_errors(ac_fcff, hist_fcff),
            "baseline": "historical_driver_median",
        },
        "market_price_vs_current_multiple_persistence": px["vs_current_multiple_persistence"],
    }
    return {
        "operating_cash_flow": cf,
        "intrinsic_value": iv,
        "market_price": px,
        "total_shareholder_return": ret,
        "baseline_comparisons": baselines_vs,
        "subgroups": subgroup_diagnostics(records),
        "n_records": len(records),
        "evaluation_targets_declared": [
            "operating_cash_flow",
            "intrinsic_value",
            "market_price",
            "total_shareholder_return",
        ],
    }


__all__ = [
    "point_errors",
    "pinball_loss",
    "crps_gaussian",
    "quantile_coverage",
    "loss_prob_calibration",
    "hurdle_calibration",
    "baseline_comparison",
    "subgroup_diagnostics",
    "score_targets",
]
