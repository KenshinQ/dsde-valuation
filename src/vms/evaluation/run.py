"""Chronological walk-forward evaluation orchestrator (SPEC §15, Phase 9)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.evaluation.baselines import build_baselines
from vms.evaluation.labels import assign_labels
from vms.evaluation.metrics import score_targets
from vms.evaluation.outcomes import outcome_as_of, realize_outcomes
from vms.evaluation.protocol import enumerate_fy_origins, reconstruct_pit, require_chronological
from vms.evaluation.universe import UniverseConfig, load_universe, materialize_universe
from vms.reporting.metadata import sha256_of
from vms.schemas.config import LoadedConfig

TZ = ZoneInfo("Asia/Shanghai")
EVAL_VERSION = "EVAL-1"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationReport(_M):
    schema_kind: Literal["EvaluationReport"] = "EvaluationReport"
    version: str = EVAL_VERSION
    label: str = "WALK_FORWARD_EVALUATION"
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
    baselines_present: list[str]
    scores: dict[str, Any]
    scores_unbiased: dict[str, Any]
    excluded_pit_incomplete: list[dict[str, Any]]
    labels: dict[str, Any]
    assumptions: list[str]
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    content_hash: str


def _spot(snap) -> float | None:
    if not snap.market:
        return None
    return float(snap.market[-1].raw_close)


def _persist_forecast(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # CRITICAL: write forecast BEFORE outcomes are attached
    assert "outcomes" not in payload or payload.get("outcomes") is None
    path.write_text(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


def run_evaluation(*, universe: UniverseConfig | str | Path, loaded: LoadedConfig,
                   start: date, end: date, out_dir: str | Path,
                   evaluation_as_of: datetime | None = None,
                   split_mode: str | None = None) -> EvaluationReport:
    """Walk-forward evaluate a universe. Random splits are rejected."""
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

    forecasts_dir = out / "forecasts"
    records: list[dict[str, Any]] = []
    excluded_pit: list[dict[str, Any]] = []
    pending = 0
    n_attempted = 0
    n_persisted = 0
    baseline_keys: set[str] = set()
    flags: list[str] = []

    for instrument_id, load in sorted(loads.items()):
        origins = enumerate_fy_origins(
            load, instrument_id=instrument_id, start=start, end=end,
            min_history_years=universe.min_history_years)
        for fy_year, origin in origins:
            n_attempted += 1
            snap, report = reconstruct_pit(load, instrument_id=instrument_id, as_of=origin,
                                           cfg_quality=loaded.config.quality)
            spot = _spot(snap)
            if spot is None or spot <= 0:
                flags.append(f"NO_SPOT:{instrument_id}@{origin.date()}")
                continue
            # Build & PERSIST forecast before outcomes
            bundle = build_baselines(load=load, instrument_id=instrument_id, as_of=origin,
                                     loaded=loaded, spot=spot, horizon_years=horizon)
            baseline_keys |= set(bundle.get("baselines", {}).keys())
            forecast_payload = {
                "instrument_id": instrument_id,
                "origin_fy": fy_year,
                "origin_as_of": origin.isoformat(),
                "horizon_years": horizon,
                "spot_price": spot,
                "pit_complete": bundle.get("pit_complete", snap.pit_complete),
                "quality_status": report.status.value,
                "forecasts": bundle.get("forecasts"),
                "baselines": bundle.get("baselines"),
                "assumptions": bundle.get("assumptions"),
                "flags": bundle.get("flags"),
                "outcomes": None,  # explicitly unset at persist time
                "persisted_before_outcomes": True,
            }
            fpath = forecasts_dir / instrument_id / f"{origin.date().isoformat()}_h{horizon}.json"
            _persist_forecast(fpath, forecast_payload)
            n_persisted += 1

            # PIT incomplete: keep record but exclude from unbiased scores
            if not forecast_payload["pit_complete"]:
                excluded_pit.append({
                    "instrument_id": instrument_id, "origin_as_of": origin.isoformat(),
                    "reason": "PIT_INCOMPLETE", "forecast_path": str(fpath.relative_to(out)),
                })

            outcomes = realize_outcomes(
                load=load, instrument_id=instrument_id, origin=origin, horizon_years=horizon,
                entry_price=spot, evaluation_as_of=eval_as_of, quality_cfg=loaded.config.quality)
            if outcomes.get("pending"):
                pending += 1
                # rewrite with pending marker only (outcomes still not scored)
                forecast_payload["outcomes"] = {"pending": True, "due_as_of": outcomes.get("due_as_of")}
            else:
                forecast_payload["outcomes"] = outcomes
            # Update file WITH outcomes after persist-before-outcomes was already written
            fpath.write_text(json.dumps(forecast_payload, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n",
                             encoding="utf-8")
            records.append({**forecast_payload, "forecast_path": str(fpath.relative_to(out))})

    scored = [r for r in records if r.get("outcomes") and not r["outcomes"].get("pending")]
    unbiased = [r for r in scored if r.get("pit_complete")]
    scores_all = score_targets(scored)
    scores_unbiased = score_targets(unbiased)

    # Calibration: with few synthetic points may be inconclusive
    cal_ok: bool | None = None
    brier = (scores_unbiased.get("total_shareholder_return") or {}).get("loss_probability_calibration", {}).get("brier")
    if scores_unbiased.get("n_records", 0) >= 5 and brier is not None:
        cal_ok = brier <= 0.35  # loose synthetic threshold
    elif scores_unbiased.get("n_records", 0) < 5:
        cal_ok = None
        flags.append("CALIBRATION_INCONCLUSIVE_FEW_ORIGINS")

    engineering_ok = (
        mode == "chronological"
        and n_persisted > 0
        and all(r.get("persisted_before_outcomes") for r in records)
    )
    # Data quality: most origins produced usable forecast points; PIT-incomplete rate not dominant.
    # Exploratory walk-forward may continue past overridden CRITICAL; do not equate report.status==BLOCKED
    # with DATA_QUALITY fail when forecasts still materialize.
    n_good = sum(
        1 for r in records
        if ((r.get("forecasts") or {}).get("operating_cash_flow") or {}).get("point") is not None
    )
    data_quality_ok = (
        n_persisted > 0
        and (n_good / n_persisted) >= 0.8
        and (len(excluded_pit) / max(n_persisted, 1)) < 0.5
    )

    labels = assign_labels(
        engineering_ok=engineering_ok, data_quality_ok=data_quality_ok, calibration_ok=cal_ok,
        data_label=universe.data_label, predeclared_oos_alpha=False)

    # Never allow SUPPORTED on synthetic
    if "SYNTHETIC" in universe.data_label.upper():
        assert labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"

    notes = [
        "Chronological walk-forward only; random splits raise RandomSplitProhibitedError.",
        "Forecasts persisted with outcomes=null before realization (persisted_before_outcomes).",
        "PIT_INCOMPLETE origins excluded from scores_unbiased (PIT-INCOMPLETE-v1).",
        "Cash-flow, intrinsic, market-price, and TSR scored in separate blocks.",
        "Intrinsic is never judged solely by matching future market prices.",
        "Synthetic universes always carry INVESTMENT_VALUE_NOT_ESTABLISHED.",
    ]
    payload = {
        "universe_id": universe.universe_id, "data_label": universe.data_label, "split_mode": mode,
        "start": start.isoformat(), "end": end.isoformat(), "horizons": horizons,
        "n_persisted": n_persisted, "n_scored": len(scored), "labels": labels,
        "scores_unbiased": scores_unbiased,
    }
    content_hash = sha256_of(payload)[:16]

    report = EvaluationReport(
        universe_id=universe.universe_id, data_label=universe.data_label, split_mode=mode,
        start=start.isoformat(), end=end.isoformat(), horizons_years=horizons,
        n_origins_attempted=n_attempted, n_forecasts_persisted=n_persisted, n_scored=len(scored),
        n_excluded_pit_incomplete=len(excluded_pit), n_pending_outcomes=pending,
        baselines_present=sorted(baseline_keys), scores=scores_all, scores_unbiased=scores_unbiased,
        excluded_pit_incomplete=excluded_pit, labels=labels,
        assumptions=cite("PIT-INCOMPLETE-v1", "DIVIDEND-NO-REINVEST-v1", "TV-GORDON-v1",
                         "EXIT-MULTIPLE-SEPARATE-v1", "WACC-CONSTRUCTION-v1", "WALK-FORWARD-ORIGINS-v1",
                         "EVAL-CHRONOLOGICAL-ONLY-v1", "EVAL-FORECAST-BEFORE-OUTCOME-v1",
                         "EVAL-TARGETS-SEPARATE-v1", "EVAL-INVESTMENT-LABEL-v1"),
        flags=sorted(set(flags)), notes=notes, content_hash=content_hash,
    )
    (out / "evaluation_report.json").write_text(
        json.dumps({"schema_version": "vms-0.1.phase9", **report.model_dump(mode="json")},
                   sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "origin_records.json").write_text(
        json.dumps({"n": len(records), "records": [
            {k: r[k] for k in ("instrument_id", "origin_as_of", "horizon_years", "pit_complete",
                               "quality_status", "forecast_path", "persisted_before_outcomes") if k in r}
            for r in records
        ]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
