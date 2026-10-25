"""Separate-target scoring for deposit-taking FI RIM walk-forward (R6).

Never mix intrinsic scoring with price MAE as truth (EVAL-IV-NOT-PRICE-TRUTH-v1).
Track B skips are counted, not silently treated as VALID.
"""

from __future__ import annotations

from typing import Any

from vms.evaluation.metrics import point_errors, subgroup_diagnostics
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS


def score_rim_targets(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score driver / intrinsic / optional market blocks separately."""
    # Driver ROE
    roe_fc = [(r.get("forecasts") or {}).get("driver_roe", {}).get("point") for r in records]
    roe_ac = [(r.get("outcomes") or {}).get("driver_roe", {}).get("realized") for r in records]
    driver = {
        "errors": point_errors(roe_ac, roe_fc),
        "note": "Common-equity ROE driver errors only — separate from intrinsic VPS",
    }

    # Intrinsic stability vs later-origin VPS; NEVER price MAE as truth
    iv_fc = [(r.get("forecasts") or {}).get("intrinsic_value", {}).get("point") for r in records]
    iv_later = [
        (r.get("outcomes") or {}).get("intrinsic_value", {}).get("later_origin_vps") for r in records
    ]
    px_ac = [(r.get("outcomes") or {}).get("market_price", {}).get("raw_close") for r in records]
    iv = {
        "stability_vs_later_origin": point_errors(iv_later, iv_fc),
        "price_mae_forbidden": True,
        "market_price_association_only": {
            "errors": point_errors(px_ac, iv_fc),
            "label": "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH",
            "note": (
                "Association between RIM VPS and realized market price is reported for "
                "transparency only. Future market price is NOT ground truth for intrinsic "
                "value (EVAL-IV-NOT-PRICE-TRUTH-v1 / SPEC §17.2)."
            ),
        },
        "note": "Intrinsic scored via coherence/stability; market price is not the truth target",
    }

    # Optional market-price block (spot persistence)
    px_fc = [(r.get("forecasts") or {}).get("market_price", {}).get("point") for r in records]
    market = {
        "errors": point_errors(px_ac, px_fc),
        "note": "Market-price forecast errors — separate from intrinsic; optional association block",
    }

    # Track B accounting — only status==SKIP is a skip ledger row.
    # NOT_ASSESSED / missing must not be defaulted to HIST_PB_BELOW_MIN.
    track_b_skips = []
    track_b_eligible = 0
    track_b_not_assessed = 0
    for r in records:
        tb = r.get("track_b") or {}
        status = tb.get("status")
        if status == "ELIGIBLE":
            track_b_eligible += 1
        elif status == "SKIP":
            track_b_skips.append({
                "instrument_id": r.get("instrument_id"),
                "origin_as_of": r.get("origin_as_of"),
                "hist_n": tb.get("hist_n"),
                "min_required": tb.get("min_required", MIN_HIST_PB_POINTS),
                "skip_reason": tb.get("skip_reason") or "HIST_PB_BELOW_MIN",
            })
        else:
            track_b_not_assessed += 1

    # Baseline: ROE median vs driver forecast (same series — identity check)
    hist_roe = [
        ((r.get("baselines") or {}).get("historical_roe_median") or {}).get("roe_median")
        for r in records
    ]
    baselines_vs = {
        "driver_roe_vs_historical_median": {
            "forecast_errors": point_errors(roe_ac, roe_fc),
            "baseline_errors": point_errors(roe_ac, hist_roe),
            "baseline": "historical_roe_median",
            "note": "FI baseline; industrial central_dcf deliberately absent",
        },
    }

    return {
        "driver_roe": driver,
        "intrinsic_value": iv,
        "market_price": market,
        "baseline_comparisons": baselines_vs,
        "subgroups": subgroup_diagnostics(records),
        "track_b": {
            "n_eligible": track_b_eligible,
            "n_skipped": len(track_b_skips),
            "n_not_assessed": track_b_not_assessed,
            "min_hist_pb_points": MIN_HIST_PB_POINTS,
            "skips": track_b_skips,
            "note": (
                "Track B scored only when hist_n >= MIN_HIST_PB_POINTS at origin; "
                "short OEI → honest SKIP (no invent OEI / no lower floor). "
                "Ledger rows only for status==SKIP; NOT_ASSESSED is not HIST_PB_BELOW_MIN."
            ),
        },
        "n_records": len(records),
        "evaluation_targets_declared": [
            "driver_roe",
            "intrinsic_value",
            "market_price",
        ],
        "price_mae_as_iv_truth_forbidden": True,
    }


__all__ = ["score_rim_targets"]
