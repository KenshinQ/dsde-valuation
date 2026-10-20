"""Distribution statistics for entry-price × horizon returns."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _finite(xs: np.ndarray) -> np.ndarray:
    return xs[np.isfinite(xs)]


def cvar_es(returns: np.ndarray, level: float) -> float | None:
    """Expected shortfall / CVaR: mean of returns at or below the (1-level) empirical quantile (left tail)."""
    xs = _finite(returns)
    if xs.size == 0 or not (0.5 <= level < 1.0):
        return None
    q = float(np.quantile(xs, 1.0 - level))
    tail = xs[xs <= q + 1e-15]
    if tail.size == 0:
        return q
    return float(tail.mean())


def mcse_mean(xs: np.ndarray) -> float | None:
    xs = _finite(xs)
    if xs.size < 2:
        return None if xs.size == 0 else 0.0
    return float(xs.std(ddof=1) / math.sqrt(xs.size))


def mcse_prob(p_hat: float, n: int) -> float | None:
    if n <= 0:
        return None
    return float(math.sqrt(max(p_hat * (1.0 - p_hat), 0.0) / n))


def summarize_returns(returns: np.ndarray, *, vps: np.ndarray, loss_thresholds: list[float],
                      hurdles: list[float], cvar_levels: list[float],
                      ann_geo: np.ndarray | None = None) -> dict[str, Any]:
    xs = _finite(np.asarray(returns, dtype=float))
    vs = _finite(np.asarray(vps, dtype=float))
    n = int(xs.size)
    if n == 0:
        return {"n": 0, "note": "no finite returns"}
    p_loss = float(np.mean(xs < 0.0))
    out: dict[str, Any] = {
        "n": n,
        "mean": float(xs.mean()),
        "median": float(np.median(xs)),
        "p05": float(np.quantile(xs, 0.05)),
        "p01": float(np.quantile(xs, 0.01)),
        "p_loss": p_loss,
        "p_loss_beyond": {str(t): float(np.mean(xs <= t)) for t in loss_thresholds},
        "p_exceed_hurdle": {str(h): float(np.mean(xs > h)) for h in hurdles},
        "cvar": {str(lv): cvar_es(xs, lv) for lv in cvar_levels},
        "terminal_vps": {
            "mean": float(vs.mean()) if vs.size else None,
            "median": float(np.median(vs)) if vs.size else None,
            "p05": float(np.quantile(vs, 0.05)) if vs.size else None,
            "p01": float(np.quantile(vs, 0.01)) if vs.size else None,
            "n": int(vs.size),
        },
        "mcse": {
            "mean": mcse_mean(xs),
            "p_loss": mcse_prob(p_loss, n),
            "p05_note": "quantile MCSE not reported; use repeated-seed stability in Phase 8+",
        },
    }
    if ann_geo is not None:
        ag = _finite(np.asarray(ann_geo, dtype=float))
        if ag.size:
            out["annualized_geometric"] = {
                "mean": float(ag.mean()),
                "median": float(np.median(ag)),
                "p05": float(np.quantile(ag, 0.05)),
                "convention": "ANNUALIZED-GEO-ENDYEAR-v1: (1+R)^(1/H)-1",
                "n": int(ag.size),
                "n_undefined": int(np.asarray(ann_geo).size - ag.size),
            }
    # internal consistency: p01 <= p05 <= median
    if not (out["p01"] <= out["p05"] + 1e-12 and out["p05"] <= out["median"] + 1e-12):
        out["flags"] = ["QUANTILE_ORDER_INCONSISTENT"]
    return out
