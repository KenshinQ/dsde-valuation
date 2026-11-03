"""MATURE_OPERATING lean walk-forward calibration harness (non-FI).

Reuses Phase 11 ``run_evaluation`` (operating / CF / multiples baselines) —
NOT RIM. Synthetic lean or real scaffold ⇒ hard
``CALIBRATION_INSUFFICIENT`` + ``INVESTMENT_VALUE_NOT_ESTABLISHED``.
Never ``ENSEMBLE_CALIBRATED`` / ``INVESTMENT_VALUE_SUPPORTED`` /
``CALIBRATION_PASS`` on the default path. SCHEMA stays ``vms-0.2.phase12``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.evaluation import run_evaluation
from vms.evaluation.pass_claim import PassClaimArtifactError, resolve_pass_claim
from vms.evaluation.universe import load_universe
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ClaimStatus

CALIBRATE_MATURE_STATUS = "MATURE_LEAN_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
ASSUMPTION_SYN = "EVAL-MATURE-LEAN-WF-v1"
ASSUMPTION_REAL = "EVAL-MATURE-LEAN-REAL-OOS-v1"


class CalibrateMatureBundleError(ValueError):
    pass


def build_calibrate_mature_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    start: date | None = None,
    end: date | None = None,
    evaluation_as_of: datetime | None = None,
    seed: int = 42,
    prefer_local: bool = True,
    pass_claim_artifact: str | Path | None = None,
) -> dict[str, Any]:
    """Run MATURE lean walk-forward via Phase 11 evaluate; write summary artifacts.

    ``prefer_local=True`` (default): mature_real scaffold makes zero REST.
    ``prefer_local=False`` (CLI ``--refresh``): reserved; scaffold still no invent.

    ``pass_claim_artifact`` optional; default None keeps CALIBRATION_INSUFFICIENT.
    Illegal artifacts raise CalibrateMatureBundleError.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = Path(config_path) if config_path else (repo_root / "config" / "default.yaml")
    loaded = load_config(cfg_path)
    uni = (
        Path(universe_path)
        if universe_path
        else (repo_root / "config" / "universe.mature_lean.yaml")
    )
    if not uni.is_file():
        raise CalibrateMatureBundleError(f"universe file not found: {uni}")

    uni_cfg = load_universe(uni)
    if uni_cfg.bank_synthetic is not None or uni_cfg.fi_real is not None:
        raise CalibrateMatureBundleError(
            "calibrate-mature refuses FI bank_synthetic / fi_real universes "
            "(use vms calibrate-rim)"
        )
    if uni_cfg.mature_synthetic is None and uni_cfg.mature_real is None and uni_cfg.synthetic is None:
        # Allow plain synthetic block only if data_label is SYNTHETIC and instruments set;
        # prefer explicit mature_* kinds.
        raise CalibrateMatureBundleError(
            "calibrate-mature requires mature_synthetic or mature_real "
            f"in universe YAML (got neither in {uni})"
        )

    assumption = ASSUMPTION_REAL if uni_cfg.mature_real is not None else ASSUMPTION_SYN

    start = start or date(2018, 1, 1)
    end = end or date(2022, 12, 31)
    tz = ZoneInfo(loaded.config.timezone)
    eval_as_of = evaluation_as_of or datetime(2025, 6, 30, 15, 0, tzinfo=tz)

    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="calibrate-mature",
            universe=str(uni),
            start=start.isoformat(),
            end=end.isoformat(),
            seed=seed,
            config=sha256_of({"c": loaded.config.model_dump(mode="json")}),
        )
    )

    try:
        report = run_evaluation(
            universe=uni_cfg,
            loaded=loaded,
            start=start,
            end=end,
            out_dir=out,
            evaluation_as_of=eval_as_of,
            prefer_local=prefer_local,
            pass_claim_artifact=pass_claim_artifact,
        )
    except PassClaimArtifactError as e:
        raise CalibrateMatureBundleError(str(e)) from e

    n_unbiased = int((report.scores_unbiased or {}).get("n_records") or 0)
    try:
        pass_claim = resolve_pass_claim(
            pass_claim_artifact,
            run_data_label=report.data_label,
            run_n_unbiased=n_unbiased,
        )
    except PassClaimArtifactError as e:
        raise CalibrateMatureBundleError(str(e)) from e

    if report.labels.get("investment_value") != INVESTMENT_LABEL:
        raise CalibrateMatureBundleError(
            "calibrate-mature must keep INVESTMENT_VALUE_NOT_ESTABLISHED"
        )
    if report.labels.get("ENSEMBLE_CALIBRATED"):
        raise CalibrateMatureBundleError(
            "calibrate-mature must not claim ENSEMBLE_CALIBRATED"
        )
    if report.labels.get("CALIBRATION_PASS") is True and not pass_claim.authorized:
        raise CalibrateMatureBundleError(
            "calibrate-mature must not silently claim CALIBRATION_PASS "
            "without authorized pass-claim artifact"
        )
    if not pass_claim.authorized:
        if report.labels.get("CALIBRATION_CLAIM") != ClaimStatus.CALIBRATION_INSUFFICIENT.value:
            raise CalibrateMatureBundleError(
                f"expected CALIBRATION_INSUFFICIENT without pass-claim auth, "
                f"got {report.labels.get('CALIBRATION_CLAIM')}"
            )

    # Stamp evaluation_report with run_id + mature assumption cite
    rep_path = out / "evaluation_report.json"
    body = json.loads(rep_path.read_text(encoding="utf-8"))
    assumps = list(body.get("assumptions") or [])
    if assumption not in assumps:
        assumps.append(assumption)
    if ASSUMPTION_SYN not in assumps and assumption == ASSUMPTION_REAL:
        # Real-OOS inherits lean-WF protocol cite
        assumps.append(ASSUMPTION_SYN)
    notes = list(body.get("notes") or [])
    notes.append(
        "MATURE lean calibrate-mature reuses Phase 11 operating/CF/multiples "
        "evaluate path (NOT RIM). Hard CALIBRATION_INSUFFICIENT on default."
    )
    body = {
        "run_id": stamp.run_id,
        "implemented_phase": IMPLEMENTED_PHASE,
        "schema_version": SCHEMA_VERSION,
        **body,
        "assumptions": sorted(set(assumps)),
        "notes": notes,
        "calibration_kind": "mature_lean_walk_forward",
        "primary_assumption": assumption,
    }
    body.setdefault("release_gates", report.release_gates)
    write_artifact(out, "evaluation_report.json", body, stamp)

    mat_rest = None
    mat_prefer = prefer_local
    for name in ("mature_real_materialize.json", "mature_synthetic_materialize.json"):
        mat_path = out / name
        if mat_path.is_file():
            mat = json.loads(mat_path.read_text(encoding="utf-8"))
            mat_rest = mat.get("rest_calls", 0)
            mat_prefer = mat.get("prefer_local", prefer_local)
            if prefer_local and int(mat_rest or 0) != 0:
                raise CalibrateMatureBundleError(
                    f"prefer_local=True but materialize rest_calls={mat_rest}"
                )
            break

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": CALIBRATE_MATURE_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "schema_version": SCHEMA_VERSION,
            "warning": (
                "MATURE_OPERATING lean walk-forward (calibrate-mature). "
                "CALIBRATION_INSUFFICIENT for production. "
                "INVESTMENT_VALUE_NOT_ESTABLISHED. Not investment advice. "
                "Reuses Phase 11 evaluate (operating/CF/multiples); not RIM. "
                f"Assumption {assumption}."
            ),
            "labels": report.labels,
            "release_gates": report.release_gates,
            "content_hash": report.content_hash,
            "n_scored": report.n_scored,
            "n_forecasts_persisted": report.n_forecasts_persisted,
            "assumption": assumption,
            "prefer_local": prefer_local,
        },
        stamp,
    )

    summary = {
        "status": CALIBRATE_MATURE_STATUS,
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
        "scores_unbiased_n_records": int((report.scores_unbiased or {}).get("n_records") or 0),
        "baselines_present": report.baselines_present,
        "labels": report.labels,
        "release_gates": report.release_gates,
        "frozen_weights": report.frozen_weights,
        "evaluation_targets_declared": (report.scores_unbiased or {}).get(
            "evaluation_targets_declared"
        ),
        "investment_value": INVESTMENT_LABEL,
        "calibration_claim": report.labels.get("CALIBRATION_CLAIM"),
        "content_hash": report.content_hash,
        "assumption": assumption,
        "prefer_local": prefer_local,
        "materialize_rest_calls": mat_rest,
        "materialize_prefer_local": mat_prefer,
        "methods": "phase11_evaluate_operating_cf_multiples",
        "not_rim": True,
        "pass_claim": pass_claim.as_dict(),
    }
    write_artifact(out, "pass_claim_decision.json", pass_claim.as_dict(), stamp)
    write_artifact(out, "calibrate_mature_summary.json", summary, stamp)
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


__all__ = [
    "ASSUMPTION_REAL",
    "ASSUMPTION_SYN",
    "CALIBRATE_MATURE_STATUS",
    "CalibrateMatureBundleError",
    "build_calibrate_mature_bundle",
    "dump_summary",
]
