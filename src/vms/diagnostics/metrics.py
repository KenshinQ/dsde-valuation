"""Extract comparable metrics from valuation / return bundles (Phase 8)."""

from __future__ import annotations

from typing import Any

from vms.returns.distributions import ReturnDistributionBundle
from vms.valuation.value import ValuationBundle


def valuation_metrics(v: ValuationBundle) -> dict[str, Any]:
    agg = v.aggregates or {}
    def _m(block: dict | None, key: str = "mean") -> float | None:
        if not block:
            return None
        return block.get(key)

    c = v.central
    return {
        "n_valid_dcf": v.n_valid_dcf,
        "central_vps_dcf": None if not (c.bridge_dcf and c.bridge_dcf.valid) else c.bridge_dcf.value_per_share,
        "central_ev_dcf": None if not (c.dcf and c.dcf.valid) else c.dcf.enterprise_value,
        "central_tv_fraction": None if not (c.dcf and c.dcf.valid) else c.dcf.tv_fraction,
        "central_vps_exit": None if not (c.bridge_exit and c.bridge_exit.valid) else c.bridge_exit.value_per_share,
        "mean_vps_dcf": _m(agg.get("dcf_value_per_share")),
        "p05_vps_dcf": _m(agg.get("dcf_value_per_share"), "p05"),
        "p50_vps_dcf": _m(agg.get("dcf_value_per_share"), "p50"),
        "p95_vps_dcf": _m(agg.get("dcf_value_per_share"), "p95"),
        "mean_tv_fraction": _m(agg.get("dcf_tv_fraction")),
        "mean_vps_exit": _m(agg.get("exit_value_per_share")),
        # Explicit band labeling — NOT a statistical confidence interval
        "vps_dcf_mc_percentile_interval_05_95": {
            "kind": "monte_carlo_percentile_interval",
            "not_a_confidence_interval": True,
            "p05": _m(agg.get("dcf_value_per_share"), "p05"),
            "p95": _m(agg.get("dcf_value_per_share"), "p95"),
        },
        "dcf_minus_exit_central_vps": (
            None if not (c.bridge_dcf and c.bridge_dcf.valid and c.bridge_exit and c.bridge_exit.valid)
            else c.bridge_dcf.value_per_share - c.bridge_exit.value_per_share
        ),
    }


def return_metrics(r: ReturnDistributionBundle | None, *, horizon: int | None = None) -> dict[str, Any]:
    if r is None:
        return {"available": False}
    h = horizon if horizon is not None else (r.horizons_years[0] if r.horizons_years else None)
    cells = [c for c in r.mixture if abs(c.relative_to_spot - 1.0) < 1e-9]
    if h is not None:
        cells = [c for c in cells if c.horizon_years == h] or cells
    if not cells:
        return {"available": True, "n_cells": 0}
    c = cells[0]
    st = c.stats
    return {
        "available": True,
        "entry_price": c.entry_price,
        "horizon_years": c.horizon_years,
        "mean_return": st.get("mean"),
        "median_return": st.get("median"),
        "p05_return": st.get("p05"),
        "p01_return": st.get("p01"),
        "p_loss": st.get("p_loss"),
        "cvar_0.95": (st.get("cvar") or {}).get("0.95"),
        "cvar_0.99": (st.get("cvar") or {}).get("0.99"),
        # band labeling
        "return_mc_percentile_interval_05_95": {
            "kind": "monte_carlo_percentile_interval",
            "not_a_confidence_interval": True,
            "p05": st.get("p05"),
            "note": "empirical MC percentiles across paths; not a CI for a fixed parameter",
        },
        "n": st.get("n"),
    }


def delta(base: dict[str, Any], alt: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    out = {}
    for k in keys:
        b, a = base.get(k), alt.get(k)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            out[k] = {"base": b, "alt": a, "delta": a - b}
        else:
            out[k] = {"base": b, "alt": a, "delta": None}
    return out
