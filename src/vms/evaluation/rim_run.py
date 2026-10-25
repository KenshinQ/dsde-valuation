"""Chronological bank RIM walk-forward calibration orchestrator (R6 / SPEC §17).

Reuses Phase 11 protocol gates (chronological-only, freeze-before-test,
forecast-before-outcome, CALIBRATION_INSUFFICIENT on thin OOS). Does NOT claim
CALIBRATION_PASS / ENSEMBLE_CALIBRATED / INVESTMENT_VALUE_SUPPORTED on the
default lean synthetic / thin real path.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from vms import SCHEMA_VERSION
from vms.assumptions import cite
from vms.evaluation.labels import assign_labels
from vms.evaluation.protocol import (
    enumerate_fy_origins,
    freeze_weights_before_test,
    reconstruct_pit,
    require_chronological,
)
from vms.evaluation.rim_forecast import build_rim_track_a_forecast
from vms.evaluation.rim_metrics import score_rim_targets
from vms.evaluation.rim_outcomes import realize_rim_outcomes
from vms.evaluation.universe import UniverseConfig, load_universe, materialize_universe
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.metadata import sha256_of
from vms.schemas.config import LoadedConfig
from vms.schemas.contracts import ClaimStatus

TZ = ZoneInfo("Asia/Shanghai")
RIM_EVAL_VERSION = "RIM-EVAL-1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RimCalibrationReport(_M):
    schema_kind: Literal["RimCalibrationReport"] = "RimCalibrationReport"
    version: str = RIM_EVAL_VERSION
    label: str = "BANK_RIM_WALK_FORWARD_CALIBRATION"
    universe_id: str
    data_label: str
    split_mode: str
    start: str
    end: str
    horizons_years: list[int]
    n_origins_attempted: int
    n_forecasts_persisted: int
    n_scored: int
    n_excluded_pit_incomplete: int
    n_pending_outcomes: int
    n_track_b_skipped: int
    n_track_b_eligible: int
    min_hist_pb_points: int = MIN_HIST_PB_POINTS
    baselines_present: list[str]
    scores: dict[str, Any]
    scores_unbiased: dict[str, Any]
    excluded_pit_incomplete: list[dict[str, Any]]
    track_b_skips: list[dict[str, Any]]
    labels: dict[str, Any]
    release_gates: dict[str, Any] = Field(default_factory=dict)
    frozen_weights: dict[str, Any] | None = None
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    declared_instruments: list[str] = Field(default_factory=list)
    content_hash: str


def _spot(snap) -> float | None:
    if not snap.market:
        return None
    return float(snap.market[-1].raw_close)


def _persist_forecast(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert "outcomes" not in payload or payload.get("outcomes") is None
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def run_rim_calibration(
    *,
    universe: UniverseConfig | str | Path,
    loaded: LoadedConfig,
    start: date,
    end: date,
    out_dir: str | Path,
    evaluation_as_of: datetime | None = None,
    split_mode: str | None = None,
    ensemble_weights: dict[str, float] | None = None,
) -> RimCalibrationReport:
    """Walk-forward calibrate bank RIM Track A. Random splits rejected."""
    if isinstance(universe, (str, Path)):
        universe = load_universe(universe)
    mode = split_mode or universe.split_mode
    require_chronological(mode)
    if universe.forbid_random_splits and mode != "chronological":
        require_chronological(mode)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    loads = materialize_universe(universe, work_dir=out)
    horizons = list(universe.horizons_years) or list(loaded.config.horizons_years)
    horizon = min(horizons)
    eval_as_of = evaluation_as_of or datetime.now(TZ)

    weights = ensemble_weights or {"rim_track_a_prior_equal": 1.0}
    freeze = freeze_weights_before_test(
        weights=weights,
        thresholds={
            "min_oos_for_calibration": 5,
            "min_hist_pb_points": MIN_HIST_PB_POINTS,
            "brier_pass_max": 0.35,
        },
        test_window_start=start,
        out_dir=out,
    )

    forecasts_dir = out / "forecasts"
    records: list[dict[str, Any]] = []
    excluded_pit: list[dict[str, Any]] = []
    track_b_skips: list[dict[str, Any]] = []
    pending = 0
    n_attempted = 0
    n_persisted = 0
    n_track_b_eligible = 0
    baseline_keys: set[str] = set()
    flags: list[str] = []

    for instrument_id, load in sorted(loads.items()):
        origins = enumerate_fy_origins(
            load,
            instrument_id=instrument_id,
            start=start,
            end=end,
            min_history_years=universe.min_history_years,
        )
        for fy_year, origin in origins:
            n_attempted += 1
            snap, report = reconstruct_pit(
                load,
                instrument_id=instrument_id,
                as_of=origin,
                cfg_quality=loaded.config.quality,
            )
            spot = _spot(snap)
            if spot is None or spot <= 0:
                flags.append(f"NO_SPOT:{instrument_id}@{origin.date()}")
                continue

            bundle = build_rim_track_a_forecast(
                snap=snap,
                quality_report=report,
                instrument_id=instrument_id,
                as_of=origin,
                loaded=loaded,
                spot=spot,
                horizon_years=horizon,
            )
            baseline_keys |= set(bundle.get("baselines", {}).keys())
            tb = bundle.get("track_b") or {}
            if tb.get("status") == "ELIGIBLE":
                n_track_b_eligible += 1
            else:
                skip_rec = {
                    "instrument_id": instrument_id,
                    "origin_as_of": origin.isoformat(),
                    "origin_fy": fy_year,
                    "hist_n": tb.get("hist_n"),
                    "min_required": tb.get("min_required", MIN_HIST_PB_POINTS),
                    "skip_reason": tb.get("skip_reason") or "HIST_PB_BELOW_MIN",
                }
                track_b_skips.append(skip_rec)

            forecast_payload = {
                "instrument_id": instrument_id,
                "origin_fy": fy_year,
                "origin_as_of": origin.isoformat(),
                "horizon_years": horizon,
                "spot_price": spot,
                "profile_id": bundle.get("profile_id") or "UNKNOWN",
                "fundamental_regime": bundle.get("fundamental_regime"),
                "pit_complete": bundle.get("pit_complete", snap.pit_complete),
                "quality_status": report.status.value,
                "rim_status": bundle.get("rim_status"),
                "forecasts": bundle.get("forecasts"),
                "baselines": bundle.get("baselines"),
                "track_b": tb,
                "assumptions": bundle.get("assumptions"),
                "flags": bundle.get("flags"),
                "outcomes": None,
                "persisted_before_outcomes": True,
                "frozen_weights_hash": freeze["content_hash"],
                "calibration_kind": "bank_rim_track_a",
            }
            fpath = forecasts_dir / instrument_id / f"{origin.date().isoformat()}_h{horizon}.json"
            _persist_forecast(fpath, forecast_payload)
            n_persisted += 1

            if not forecast_payload["pit_complete"]:
                excluded_pit.append({
                    "instrument_id": instrument_id,
                    "origin_as_of": origin.isoformat(),
                    "reason": "PIT_INCOMPLETE",
                    "forecast_path": str(fpath.relative_to(out)),
                })

            origin_vps = (bundle.get("forecasts") or {}).get("intrinsic_value", {}).get("point")
            outcomes = realize_rim_outcomes(
                load=load,
                instrument_id=instrument_id,
                origin=origin,
                horizon_years=horizon,
                entry_price=spot,
                evaluation_as_of=eval_as_of,
                quality_cfg=loaded.config.quality,
                loaded=loaded,
                origin_vps=origin_vps,
            )
            if outcomes.get("pending"):
                pending += 1
                forecast_payload["outcomes"] = {
                    "pending": True,
                    "due_as_of": outcomes.get("due_as_of"),
                }
            else:
                forecast_payload["outcomes"] = outcomes
            fpath.write_text(
                json.dumps(
                    forecast_payload, sort_keys=True, indent=2, ensure_ascii=False, default=str
                )
                + "\n",
                encoding="utf-8",
            )
            records.append({**forecast_payload, "forecast_path": str(fpath.relative_to(out))})

    scored = [r for r in records if r.get("outcomes") and not r["outcomes"].get("pending")]
    # pit_complete=false excluded from unbiased scores (AC11)
    unbiased = [r for r in scored if r.get("pit_complete")]
    scores_all = score_rim_targets(scored)
    scores_unbiased = score_rim_targets(unbiased)

    n_unbiased = int(scores_unbiased.get("n_records", 0))
    # Default lean / thin OOS → INSUFFICIENT (do not silently PASS)
    cal_ok: bool | None = None
    if n_unbiased < 5:
        cal_ok = None
        flags.append("CALIBRATION_INSUFFICIENT_FEW_ORIGINS")
    else:
        # Even with enough rows, R6-default does not auto-claim PASS without
        # a predeclared real-OOS protocol — leave None (INSUFFICIENT) unless
        # explicitly upgraded later.
        cal_ok = None
        flags.append("CALIBRATION_INSUFFICIENT_NO_PREDECLARED_OOS_PROTOCOL")

    engineering_ok = (
        mode == "chronological"
        and n_persisted > 0
        and all(r.get("persisted_before_outcomes") for r in records)
    )
    n_good = sum(
        1
        for r in records
        if ((r.get("forecasts") or {}).get("intrinsic_value") or {}).get("point") is not None
        or ((r.get("forecasts") or {}).get("driver_roe") or {}).get("point") is not None
    )
    data_quality_ok = n_persisted > 0 and (n_good / n_persisted) >= 0.5

    labels = assign_labels(
        engineering_ok=engineering_ok,
        data_quality_ok=data_quality_ok,
        calibration_ok=cal_ok,
        data_label=universe.data_label,
        predeclared_oos_alpha=False,
        ensemble_calibrated=False,
        n_unbiased_scored=n_unbiased,
        min_oos_for_calibration=5,
    )
    # Hard: never claim investment supported / ensemble calibrated on R6 path
    assert labels["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert labels["ENSEMBLE_CALIBRATED"] is False
    assert labels["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value

    notes = [
        "R6 bank RIM chronological walk-forward (SPEC §17 / EVAL-RIM-BANK-WF-v1).",
        "Random splits raise RandomSplitProhibitedError.",
        "Forecasts persisted with outcomes=null before realization.",
        "PIT_INCOMPLETE origins excluded from scores_unbiased.",
        "Targets declared separately: driver_roe, intrinsic_value, market_price (association).",
        "Intrinsic never judged solely by matching future market prices.",
        f"Track B: hist_n < {MIN_HIST_PB_POINTS} → SKIP (no invent OEI / no lower floor).",
        "Inadequate OOS → CALIBRATION_INSUFFICIENT (not inferred success).",
        "INVESTMENT_VALUE_NOT_ESTABLISHED; never ENSEMBLE_CALIBRATED on this path.",
        "Legacy industry.unsupported / UNSUPPORTED_PROFILE for vms value|project unchanged.",
        "SCHEMA remains phase12; this report does not bump schema to claim calibration PASS.",
    ]
    declared = [i.instrument_id for i in universe.instruments]
    payload = {
        "universe_id": universe.universe_id,
        "data_label": universe.data_label,
        "split_mode": mode,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "n_persisted": n_persisted,
        "n_scored": len(scored),
        "labels": labels,
        "scores_unbiased": scores_unbiased,
        "frozen_weights_hash": freeze["content_hash"],
        "n_track_b_skipped": len(track_b_skips),
    }
    content_hash = sha256_of(payload)[:16]

    report = RimCalibrationReport(
        universe_id=universe.universe_id,
        data_label=universe.data_label,
        split_mode=mode,
        start=start.isoformat(),
        end=end.isoformat(),
        horizons_years=horizons,
        n_origins_attempted=n_attempted,
        n_forecasts_persisted=n_persisted,
        n_scored=len(scored),
        n_excluded_pit_incomplete=len(excluded_pit),
        n_pending_outcomes=pending,
        n_track_b_skipped=len(track_b_skips),
        n_track_b_eligible=n_track_b_eligible,
        baselines_present=sorted(baseline_keys),
        scores=scores_all,
        scores_unbiased=scores_unbiased,
        excluded_pit_incomplete=excluded_pit,
        track_b_skips=track_b_skips,
        labels=labels,
        release_gates=labels.get("release_gates") or {},
        frozen_weights={
            "content_hash": freeze["content_hash"],
            "test_window_start": freeze["test_window_start"],
            "frozen_before_test": True,
        },
        assumptions=cite(
            "EVAL-RIM-BANK-WF-v1",
            "EVAL-CHRONOLOGICAL-ONLY-v1",
            "EVAL-FORECAST-BEFORE-OUTCOME-v1",
            "EVAL-TARGETS-SEPARATE-v1",
            "EVAL-INVESTMENT-LABEL-v1",
            "EVAL-CALIBRATION-INSUFFICIENT-v1",
            "EVAL-WEIGHTS-FROZEN-v1",
            "EVAL-IV-NOT-PRICE-TRUTH-v1",
            "RIM-COMMON-EQUITY-v1",
            "RIM-EXIT-OWN-PB-HIST-v1",
            "PIT-INCOMPLETE-v1",
        ),
        flags=sorted(set(flags)),
        notes=notes,
        declared_instruments=declared,
        content_hash=content_hash,
    )
    (out / "rim_calibration_report.json").write_text(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, **report.model_dump(mode="json")},
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "origin_records.json").write_text(
        json.dumps(
            {
                "n": len(records),
                "records": [
                    {
                        k: r[k]
                        for k in (
                            "instrument_id",
                            "origin_as_of",
                            "horizon_years",
                            "profile_id",
                            "pit_complete",
                            "quality_status",
                            "rim_status",
                            "forecast_path",
                            "persisted_before_outcomes",
                            "frozen_weights_hash",
                            "track_b",
                        )
                        if k in r
                    }
                    for r in records
                ],
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["RimCalibrationReport", "run_rim_calibration"]
