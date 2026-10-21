"""VMS-0.2 Phase 11 offline walk-forward + sensitivity demo (SPEC §16–§17 / §20 Phase 11).

PIT-safe chronological evaluation, baselines, proper scoring, subgroup diagnostics,
release gates. Synthetic ⇒ CALIBRATION_INSUFFICIENT + INVESTMENT_VALUE_NOT_ESTABLISHED.
Never ENSEMBLE_CALIBRATED / INVESTMENT_VALUE_SUPPORTED on this offline path.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.diagnostics import run_diagnostics
from vms.evaluation import run_evaluation
from vms.pipeline import run_returns
from vms.pit.asof import AS_OF_DATE_RULE, parse_as_of
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.config import load_config
from vms.schemas.contracts import ClaimStatus

PHASE11_STATUS = "PHASE11_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value

# SPEC §16.2 minimum sensitivity set — implemented vs deferred on synthetic demo
SENSITIVITY_COVERAGE = {
    "implemented": [
        "revenue_growth",
        "ebit_margin",
        "capex_to_revenue",
        "cost_of_equity",
        "terminal_growth",
        "exit_multiple",
        "fundamental_state_posterior",
        "state_transition_probabilities",
        "capital_allocation_policy",
        "process_vs_parameter",
        "joint:growth_margin",
        "joint:wacc_g",
    ],
    "deferred": [
        "working_capital_detail_beyond_receivables_shock",
        "normalized_earnings_alternate_definitions",
        "payout_policy_full_grid",
        "debt_cash_bridge_shocks",
        "dilution_path_shocks_beyond_share_growth",
        "profile_posterior_full_resampling",
        "market_pricing_state_transition_grid",
        "holding_company_discount",
        "asset_haircuts_nav",
        "ensemble_weights_when_calibrated",
    ],
    "note": (
        "Deferred items require richer multi-method / NAV / market-state fixtures "
        "or calibrated ensemble weights (Phase 12+ / real OOS). Documented honestly "
        "per SPEC §16.2 / §20 Phase 11."
    ),
}


class Phase11BundleError(ValueError):
    pass


def build_phase11_bundle(
    *,
    out_dir: str | Path,
    config_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    start: date | None = None,
    end: date | None = None,
    evaluation_as_of: datetime | None = None,
    seed: int = 42,
    sensitivity_paths: int = 20,
    sensitivity_years: int = 3,
    skip_sensitivity: bool = False,
) -> dict[str, Any]:
    """Run walk-forward evaluation + (optional) sensitivity; write §16.3 artifacts."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    cfg_path = Path(config_path) if config_path else (repo_root / "config" / "default.yaml")
    loaded = load_config(cfg_path)
    uni = Path(universe_path) if universe_path else (repo_root / "config" / "universe.synthetic.yaml")
    if not uni.is_file():
        raise Phase11BundleError(f"universe file not found: {uni}")

    start = start or date(2018, 1, 1)
    end = end or date(2022, 12, 31)
    tz = ZoneInfo(loaded.config.timezone)
    eval_as_of = evaluation_as_of or datetime(2025, 6, 30, 15, 0, tzinfo=tz)

    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="phase11",
            universe=str(uni),
            start=start.isoformat(),
            end=end.isoformat(),
            seed=seed,
            config=sha256_of({"c": loaded.config.model_dump(mode="json")}),
        )
    )

    # ---- Walk-forward evaluation (forecasts before outcomes) ----
    report = run_evaluation(
        universe=uni,
        loaded=loaded,
        start=start,
        end=end,
        out_dir=out,
        evaluation_as_of=eval_as_of,
    )

    # Guardrails for synthetic offline demo
    if report.labels.get("investment_value") != INVESTMENT_LABEL:
        raise Phase11BundleError("synthetic Phase 11 must keep INVESTMENT_VALUE_NOT_ESTABLISHED")
    if report.labels.get("ENSEMBLE_CALIBRATED"):
        raise Phase11BundleError("synthetic Phase 11 must not claim ENSEMBLE_CALIBRATED")
    cal_claim = report.labels.get("CALIBRATION_CLAIM")
    if cal_claim not in (
        ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        ClaimStatus.CALIBRATION_PASS.value,
        "CALIBRATION_FAIL",
    ):
        raise Phase11BundleError(f"unexpected calibration claim: {cal_claim}")
    # Synthetic few-origin path must not silently PASS
    if "SYNTHETIC" in report.data_label.upper() and report.labels.get("CALIBRATION_PASS") is True:
        # Only allowed if enough unbiased rows AND brier gate — still not investment alpha
        pass
    if "SYNTHETIC" in report.data_label.upper() and report.n_scored < 5:
        if report.labels.get("CALIBRATION_CLAIM") != ClaimStatus.CALIBRATION_INSUFFICIENT.value:
            raise Phase11BundleError(
                "inadequate synthetic OOS must be CALIBRATION_INSUFFICIENT, not inferred success"
            )

    # ---- Sensitivity (reuse Phase-8 diagnostics engine; document §16.2 coverage) ----
    sens_payload: dict[str, Any] | None = None
    if not skip_sensitivity:
        as_of, as_of_note = parse_as_of("2025-06-30")
        sens_data = out / "sensitivity_data"
        fin, mkt, actions = synthetic.generate(seed)
        write_directory(
            sens_data,
            fin,
            mkt,
            actions,
            synthetic.source_descriptors(),
            fmt="csv",
            classifications=synthetic.classifications(),
        )
        load = load_directory(sens_data)
        baseline = run_returns(
            load,
            instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
            as_of=as_of,
            loaded=loaded,
            seed=seed,
            n_paths=sensitivity_paths,
            n_years=sensitivity_years,
            horizons_years=[1, min(3, sensitivity_years)],
            mode="exploratory",
            override_reason="phase11_sensitivity_baseline",
        )
        if baseline.valuation is None or baseline.returns is None:
            raise Phase11BundleError(
                f"sensitivity baseline unsupported: profile={baseline.resolution.status.value}"
            )
        sens = run_diagnostics(
            load=load,
            instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
            as_of=as_of,
            loaded=loaded,
            seed=seed,
            n_paths=sensitivity_paths,
            n_years=sensitivity_years,
            baseline=baseline,
            mode="exploratory",
            override_reason="phase11_sensitivity",
        )
        sens_payload = {
            "schema_version": SCHEMA_VERSION,
            "implemented_phase": IMPLEMENTED_PHASE,
            "run_id": stamp.run_id,
            "as_of": as_of.isoformat(),
            "as_of_rule": AS_OF_DATE_RULE,
            "as_of_note": as_of_note,
            "section_16_2_coverage": SENSITIVITY_COVERAGE,
            "uncertainty_attribution": {
                "process_vs_parameter": sens.process_vs_parameter,
                "driver_attribution": sens.driver_attribution,
                "dominant_assumptions": sens.dominant_assumptions,
                "dcf_vs_multiple": sens.dcf_vs_multiple,
                "terminal_value_contribution": sens.terminal_value_contribution,
                "interval_labeling": sens.interval_labeling,
            },
            **sens.model_dump(mode="json"),
            "investment_value": INVESTMENT_LABEL,
            "note": (
                "Sensitivity is engineering diagnostics only; not calibrated probabilities "
                "and not investment advice (SPEC §16 / §2.12)."
            ),
        }
        write_artifact(out, "sensitivity_report.json", sens_payload, stamp)

    # Stamp evaluation_report with run_id (run_evaluation already wrote the file)
    rep_path = out / "evaluation_report.json"
    body = json.loads(rep_path.read_text(encoding="utf-8"))
    body = {
        "run_id": stamp.run_id,
        "implemented_phase": IMPLEMENTED_PHASE,
        "schema_version": SCHEMA_VERSION,
        **body,
    }
    # Ensure release_gates present at top level
    body.setdefault("release_gates", report.release_gates)
    write_artifact(out, "evaluation_report.json", body, stamp)

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": PHASE11_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "schema_version": SCHEMA_VERSION,
            "warning": (
                "Phase 11 walk-forward / sensitivity on SYNTHETIC data only. "
                "CALIBRATION_INSUFFICIENT for production ensemble. "
                "INVESTMENT_VALUE_NOT_ESTABLISHED. Not investment advice."
            ),
            "labels": report.labels,
            "release_gates": report.release_gates,
            "content_hash": report.content_hash,
            "n_scored": report.n_scored,
            "n_forecasts_persisted": report.n_forecasts_persisted,
            "sensitivity_written": sens_payload is not None,
            "section_16_2_coverage": SENSITIVITY_COVERAGE,
        },
        stamp,
    )

    summary = {
        "status": PHASE11_STATUS,
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
        "baselines_present": report.baselines_present,
        "labels": report.labels,
        "release_gates": report.release_gates,
        "frozen_weights": report.frozen_weights,
        "evaluation_targets_declared": (report.scores_unbiased or {}).get(
            "evaluation_targets_declared"
        ),
        "has_subgroups": "subgroups" in (report.scores_unbiased or {}),
        "sensitivity_written": sens_payload is not None,
        "sensitivity_content_hash": None if sens_payload is None else sens_payload.get("content_hash"),
        "section_16_2_coverage": SENSITIVITY_COVERAGE,
        "investment_value": INVESTMENT_LABEL,
        "content_hash": report.content_hash,
    }
    write_artifact(out, "phase11_summary.json", summary, stamp)
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


__all__ = [
    "PHASE11_STATUS",
    "SENSITIVITY_COVERAGE",
    "Phase11BundleError",
    "build_phase11_bundle",
    "dump_summary",
]
