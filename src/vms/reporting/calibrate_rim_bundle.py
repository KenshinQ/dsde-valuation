"""Deposit-taking FI RIM walk-forward calibration offline emitter (R6/R7).

Reuses Phase 11 evaluation protocol. Synthetic lean panel (R6) or HiThink/EM
real lean panel (R7) ⇒ CALIBRATION_INSUFFICIENT + INVESTMENT_VALUE_NOT_ESTABLISHED.
Never ENSEMBLE_CALIBRATED / INVESTMENT_VALUE_SUPPORTED / CALIBRATION_PASS on the
default path. SCHEMA stays vms-0.2.phase12 (no bump to claim PASS).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.evaluation.rim_run import run_rim_calibration
from vms.methods.rim.bank_peers import LEAN_CURATED_DEPOSIT_TAKING_FI
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ClaimStatus

CALIBRATE_RIM_STATUS = "R6_BANK_RIM_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value


class CalibrateRimBundleError(ValueError):
    pass


def build_calibrate_rim_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    start: date | None = None,
    end: date | None = None,
    evaluation_as_of: datetime | None = None,
    seed: int = 42,
    prefer_local: bool = True,
) -> dict[str, Any]:
    """Run deposit-taking FI RIM walk-forward; write rim_calibration_report + summary.

    ``prefer_local=True`` (default): fi_real universes make zero REST.
    ``prefer_local=False`` (CLI ``--refresh``): allow Recipe E / EM upsert.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = Path(config_path) if config_path else (repo_root / "config" / "default.yaml")
    loaded = load_config(cfg_path)
    uni = (
        Path(universe_path)
        if universe_path
        else (repo_root / "config" / "universe.fi_deposit_lean.yaml")
    )
    if not uni.is_file():
        raise CalibrateRimBundleError(f"universe file not found: {uni}")

    start = start or date(2016, 1, 1)
    end = end or date(2022, 12, 31)
    tz = ZoneInfo(loaded.config.timezone)
    eval_as_of = evaluation_as_of or datetime(2025, 6, 30, 15, 0, tzinfo=tz)

    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="calibrate-rim",
            universe=str(uni),
            start=start.isoformat(),
            end=end.isoformat(),
            seed=seed,
            config=sha256_of({"c": loaded.config.model_dump(mode="json")}),
        )
    )

    report = run_rim_calibration(
        universe=uni,
        loaded=loaded,
        start=start,
        end=end,
        out_dir=out,
        evaluation_as_of=eval_as_of,
        prefer_local=prefer_local,
    )

    if report.labels.get("investment_value") != INVESTMENT_LABEL:
        raise CalibrateRimBundleError("calibrate-rim must keep INVESTMENT_VALUE_NOT_ESTABLISHED")
    if report.labels.get("ENSEMBLE_CALIBRATED"):
        raise CalibrateRimBundleError("calibrate-rim must not claim ENSEMBLE_CALIBRATED")
    if report.labels.get("CALIBRATION_PASS") is True:
        raise CalibrateRimBundleError(
            "calibrate-rim default must not silently claim CALIBRATION_PASS "
            "(expected CALIBRATION_INSUFFICIENT without predeclared OOS protocol)"
        )
    if report.labels.get("CALIBRATION_CLAIM") != ClaimStatus.CALIBRATION_INSUFFICIENT.value:
        raise CalibrateRimBundleError(
            f"expected CALIBRATION_INSUFFICIENT, got {report.labels.get('CALIBRATION_CLAIM')}"
        )
    if report.min_hist_pb_points != MIN_HIST_PB_POINTS:
        raise CalibrateRimBundleError("MIN_HIST_PB_POINTS must remain 12")

    # Stamp report
    rep_path = out / "rim_calibration_report.json"
    body = json.loads(rep_path.read_text(encoding="utf-8"))
    body = {
        "run_id": stamp.run_id,
        "implemented_phase": IMPLEMENTED_PHASE,
        "schema_version": SCHEMA_VERSION,
        **body,
    }
    body.setdefault("release_gates", report.release_gates)
    write_artifact(out, "rim_calibration_report.json", body, stamp)

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": CALIBRATE_RIM_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "schema_version": SCHEMA_VERSION,
            "warning": (
                "Deposit-taking FI RIM walk-forward (R6/R7). CALIBRATION_INSUFFICIENT for production. "
                "INVESTMENT_VALUE_NOT_ESTABLISHED. Not investment advice. "
                "Does not lift industry.unsupported (see EVAL-RIM-FI-DEPOSIT-WF-v1 / EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1). "
                f"Track B requires hist_n>={MIN_HIST_PB_POINTS}."
            ),
            "labels": report.labels,
            "release_gates": report.release_gates,
            "content_hash": report.content_hash,
            "n_scored": report.n_scored,
            "n_forecasts_persisted": report.n_forecasts_persisted,
            "n_track_b_skipped": report.n_track_b_skipped,
            "n_track_b_eligible": report.n_track_b_eligible,
            "min_hist_pb_points": MIN_HIST_PB_POINTS,
            "lean_curated_size": len(LEAN_CURATED_DEPOSIT_TAKING_FI),
            "declared_instruments": report.declared_instruments,
        },
        stamp,
    )

    summary = {
        "status": CALIBRATE_RIM_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "out": str(out),
        "universe_id": report.universe_id,
        "data_label": report.data_label,
        "split_mode": report.split_mode,
        "n_forecasts_persisted": report.n_forecasts_persisted,
        "n_scored": report.n_scored,
        "n_excluded_pit_incomplete": report.n_excluded_pit_incomplete,
        "n_track_b_skipped": report.n_track_b_skipped,
        "n_track_b_eligible": report.n_track_b_eligible,
        "min_hist_pb_points": MIN_HIST_PB_POINTS,
        "baselines_present": report.baselines_present,
        "labels": report.labels,
        "release_gates": report.release_gates,
        "frozen_weights": report.frozen_weights,
        "evaluation_targets_declared": (report.scores_unbiased or {}).get(
            "evaluation_targets_declared"
        ),
        "track_b_skips_sample": report.track_b_skips[:5],
        "declared_instruments": report.declared_instruments,
        "includes_000001": "000001.SZ" in report.declared_instruments,
        "investment_value": INVESTMENT_LABEL,
        "calibration_claim": report.labels.get("CALIBRATION_CLAIM"),
        "content_hash": report.content_hash,
        "assumption": (
            "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1"
            if "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" in report.assumptions
            else "EVAL-RIM-FI-DEPOSIT-WF-v1"
        ),
        "prefer_local": prefer_local,
        "fi_real_rest_calls": None,
    }
    mat_path = out / "fi_real_materialize.json"
    if mat_path.is_file():
        import json as _json
        mat = _json.loads(mat_path.read_text(encoding="utf-8"))
        summary["fi_real_rest_calls"] = mat.get("rest_calls")
        summary["fi_real_prefer_local"] = mat.get("prefer_local")
        if prefer_local and int(mat.get("rest_calls") or 0) != 0:
            raise CalibrateRimBundleError(
                f"prefer_local=True but fi_real rest_calls={mat.get('rest_calls')}"
            )
    write_artifact(out, "calibrate_rim_summary.json", summary, stamp)
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


__all__ = [
    "CALIBRATE_RIM_STATUS",
    "CalibrateRimBundleError",
    "build_calibrate_rim_bundle",
    "dump_summary",
]
