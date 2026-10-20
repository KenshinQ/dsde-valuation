"""Separate-target metrics and calibration (SPEC §15.2). Never mix IV scoring with price MAE."""

from __future__ import annotations

import math
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
    """Reliability-style bins: mean forecast p_loss vs empirical loss rate."""
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


def score_targets(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score each target family separately from persisted forecast+outcome pairs (unbiased subset only)."""
    # Operating CF
    fc_fcff = [r.get("forecasts", {}).get("operating_cash_flow", {}).get("point") for r in records]
    ac_fcff = [r.get("outcomes", {}).get("operating_cash_flow", {}).get("fcff_proxy") for r in records]
    cf = {
        "errors": point_errors(ac_fcff, fc_fcff),
        "note": "FCFF/CFO forecast errors only — not mixed with price or return scores",
    }
    # Intrinsic: stability vs later re-estimate if present; NEVER price MAE
    iv_fc = [r.get("forecasts", {}).get("intrinsic_value", {}).get("point") for r in records]
    iv_later = [r.get("outcomes", {}).get("intrinsic_value", {}).get("later_origin_vps") for r in records]
    iv = {
        "stability_vs_later_origin": point_errors(iv_later, iv_fc),
        "price_mae_forbidden": True,
        "note": "Intrinsic scored via coherence/stability only; market price is not the truth target",
    }
    # Market price
    px_fc = [r.get("forecasts", {}).get("market_price", {}).get("point") for r in records]
    px_ac = [r.get("outcomes", {}).get("market_price", {}).get("raw_close") for r in records]
    px = {"errors": point_errors(px_ac, px_fc), "note": "Market-price forecast errors — separate from intrinsic"}
    # Returns
    r_fc = [r.get("forecasts", {}).get("total_shareholder_return", {}).get("point") for r in records]
    r_ac = [r.get("outcomes", {}).get("total_shareholder_return", {}).get("realized") for r in records]
    p_loss_fc = [r.get("forecasts", {}).get("total_shareholder_return", {}).get("p_loss") for r in records]
    realized_loss = [None if x is None else (x < 0) for x in r_ac]
    ret = {
        "point_errors": point_errors(r_ac, r_fc),
        "loss_probability_calibration": loss_prob_calibration(realized_loss, p_loss_fc),
        "hurdle_calibration": [
            hurdle_calibration(r_ac, [r.get("forecasts", {}).get("total_shareholder_return", {}).get("p_exceed_0")
                                      for r in records], 0.0),
            hurdle_calibration(r_ac, [r.get("forecasts", {}).get("total_shareholder_return", {}).get("p_exceed_0.08")
                                      for r in records], 0.08),
        ],
        "note": "TSR under DIVIDEND-NO-REINVEST; separate from CF and intrinsic",
    }
    return {
        "operating_cash_flow": cf,
        "intrinsic_value": iv,
        "market_price": px,
        "total_shareholder_return": ret,
        "n_records": len(records),
    }
