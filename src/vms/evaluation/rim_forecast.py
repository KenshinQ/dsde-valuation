"""R6 deposit-taking FI RIM Track A forecast + FI baselines at a PIT origin (SPEC §17).

Driver (ROE) and intrinsic VPS are scored separately. Future market price is
never treated as intrinsic ground truth (EVAL-IV-NOT-PRICE-TRUTH-v1).
Track B hist P/B depth is assessed for eligibility; hist_n < MIN_HIST_PB_POINTS
→ honest SKIP (no invent OEI / no lower floor).
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from vms.assumptions import cite
from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.protocol import ValuationContext
from vms.methods.rim.distribution import historical_common_roe
from vms.methods.rim.from_snapshot import (
    RimBridgeError,
    features_from_snapshot,
    rim_inputs_from_snapshot,
)
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS, historical_common_pb
from vms.profiles import classify_profile
from vms.quality.report import QualityState
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import MethodEligibilityStatus, ProfileLabel, ValuationTarget


def build_rim_track_a_forecast(
    *,
    snap,
    quality_report,
    instrument_id: str,
    as_of: datetime,
    loaded: LoadedConfig,
    spot: float,
    horizon_years: int = 1,
    zeros_explicit: bool = True,
) -> dict[str, Any]:
    """Build Track A RIM forecast + FI baselines at origin. Past-only (PIT)."""
    flags: list[str] = []
    assumptions = cite(
        "EVAL-RIM-FI-DEPOSIT-WF-v1",
        "EVAL-FORECAST-BEFORE-OUTCOME-v1",
        "EVAL-TARGETS-SEPARATE-v1",
        "EVAL-IV-NOT-PRICE-TRUTH-v1",
        "RIM-COMMON-EQUITY-v1",
        "RIM-EXIT-OWN-PB-HIST-v1",
    )
    out: dict[str, Any] = {
        "origin_as_of": as_of.isoformat(),
        "spot_price": spot,
        "profile_id": "UNKNOWN",
        "fundamental_regime": None,
        "baselines": {},
        "forecasts": {},
        "flags": flags,
        "assumptions": assumptions,
        "pit_complete": bool(getattr(snap, "pit_complete", False)),
        "rim_status": "INELIGIBLE",
        "track_b": {
            "status": "NOT_ASSESSED",
            "hist_n": 0,
            "min_required": MIN_HIST_PB_POINTS,
            "skip_reason": None,
        },
        "equity_basis": "common",
    }

    # Track B hist depth is independent of RIM bridge success — assess always
    # so status is ELIGIBLE|SKIP (never leave NOT_ASSESSED on return paths).
    hist = historical_common_pb(snap, zeros_explicit=zeros_explicit)
    out["track_b"] = {
        "status": "ELIGIBLE" if hist.ok else "SKIP",
        "hist_n": int(hist.n),
        "min_required": MIN_HIST_PB_POINTS,
        "median_pb": hist.median,
        "skip_reason": None if hist.ok else (hist.ineligible_reason or "HIST_PB_BELOW_MIN"),
        "year_funnel": [
            {"year": e.year, "status": e.status, "reason": e.reason} for e in (hist.year_funnel or [])
        ],
        "assumption_ids": list(hist.assumption_ids),
    }
    if not hist.ok:
        flags.append(f"TRACK_B_SKIP:hist_n={hist.n}<{MIN_HIST_PB_POINTS}")
        out["flags"] = sorted(set(flags))

    feats = features_from_snapshot(snap)
    profile = classify_profile(feats)
    out["profile_id"] = (
        profile.primary_profile.value
        if hasattr(profile.primary_profile, "value")
        else str(profile.primary_profile)
    )
    if profile.primary_profile is ProfileLabel.MATURE_OPERATING:
        flags.append("RIM_REFUSED_MATURE_OPERATING")
        out["flags"] = flags
        return out

    try:
        bridge = rim_inputs_from_snapshot(
            snap,
            loaded=loaded,
            years=max(horizon_years, loaded.config.projection.default_years),
            zeros_explicit=zeros_explicit,
            equity_basis="common",
        )
    except RimBridgeError as e:
        flags.append(f"RIM_BRIDGE_ERROR:{e}")
        out["flags"] = flags
        return out

    if not bridge.ok:
        flags.append(bridge.ineligible_reason or "BRIDGE_INELIGIBLE")
        out["flags"] = sorted(set(flags) | set(bridge.flags))
        return out

    flags.extend(bridge.flags)
    out["assumptions"] = sorted(set(assumptions) | set(bridge.assumption_ids or []))

    # ---- Driver baseline: historical common ROE median ----
    roe_hist = historical_common_roe(snap, zeros_explicit=zeros_explicit)
    roe_median = statistics.median(roe_hist.roe) if roe_hist.roe else None
    out["baselines"]["historical_roe_median"] = {
        "label": "historical_common_roe_median",
        "roe_median": roe_median,
        "n_years": len(roe_hist.roe),
        "years": list(roe_hist.years),
    }
    out["baselines"]["fi_note"] = {
        "label": "industrial_fcff_dcf_unavailable_for_fi",
        "note": (
            "Deposit-taking FI walk-forward uses RIM Track A + ROE driver baselines; "
            "industrial FCFF/DCF remains unsupported (legacy industry.unsupported)."
        ),
    }

    # Driver forecast = ROE median persistence into next FY
    out["forecasts"]["driver_roe"] = {
        "point": roe_median,
        "family": "common_roe",
        "policy": "HIST_MEDIAN_PERSISTENCE",
        "note": "Scored vs realized next-FY common ROE; separate from intrinsic VPS",
    }

    # ---- Track A intrinsic: residual_income plugin ----
    registry = build_registry_from_config(loaded.method_registry)
    plugin = registry.plugin("residual_income")
    available = frozenset({
        "total_equity", "parent_net_income", "dividends_paid", "revenue",
        "total_assets", "total_liabilities", "ebit", "cash_flow_from_operations",
        "capex", "interest_bearing_debt", "cash",
        "other_equity_instruments", "minority_interest", "basic_eps",
        "other_comprehensive_income", "goodwill", "interest_income",
    })
    vps_point = None
    equity_value = None
    rim_status = "INELIGIBLE"
    if plugin is not None:
        ctx = ValuationContext(
            instrument_id=instrument_id,
            as_of=as_of.isoformat(),
            target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
            profile=profile,
            available_fields=available,
            data_quality_blocked=(
                quality_report.status is QualityState.BLOCKED
                if quality_report is not None
                else False
            ),
            loaded=loaded,
            rim_inputs=dict(bridge.rim_inputs),
            subject_metrics={
                "total_equity": bridge.rim_inputs.get("book_equity_0"),
                "parent_net_income": bridge.last_fy_ni,
            },
        )
        method_result = plugin.value_paths(
            ctx,
            None,
            MethodConfig(method_id="residual_income", assumptions=dict(bridge.rim_inputs)),
        )
        rim_status = method_result.status.value
        if method_result.status is MethodEligibilityStatus.VALID and method_result.values:
            equity_value = method_result.values.get("equity_value")
            vps = method_result.values.get("value_per_share")
            if isinstance(vps, dict):
                vps_point = vps.get("mean") or vps.get("point")
            else:
                vps_point = vps
            if method_result.diagnostics.get("flags"):
                flags.extend(method_result.diagnostics["flags"])

    out["rim_status"] = rim_status
    out["baselines"]["central_rim"] = {
        "label": "deterministic_central_rim_vps",
        "vps": vps_point,
        "equity_value": equity_value,
        "status": rim_status,
    }
    out["forecasts"]["intrinsic_value"] = {
        "point": vps_point,
        "family": "residual_income_common_equity",
        "status": rim_status,
        "note": (
            "Intrinsic VPS from RIM Track A. Never scored by price MAE alone "
            "(EVAL-IV-NOT-PRICE-TRUTH-v1)."
        ),
    }
    # Optional market association forecast = spot persistence (NOT IV truth)
    out["forecasts"]["market_price"] = {
        "point": spot,
        "family": "spot_persistence",
        "note": "Market-price association only; not intrinsic ground truth",
    }

    out["flags"] = sorted(set(flags))
    return out


__all__ = ["build_rim_track_a_forecast", "MIN_HIST_PB_POINTS"]
