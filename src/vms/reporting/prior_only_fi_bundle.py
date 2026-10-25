"""R8: deposit-taking FI PRIOR_ONLY research ensemble wiring (SPEC §13.3 / §17.4).

Wires FI-compatible method distributions (RIM Track A required; pb_common optional;
Track B only when hist_n >= MIN_HIST_PB_POINTS) into Phase 8 ``build_ensemble``
with ``intent=research_prior``. Production intent on the same components still
refuses mixture.

Hard labels: PRIOR_ONLY / ENSEMBLE_UNCALIBRATED / CALIBRATION_INSUFFICIENT /
INVESTMENT_VALUE_NOT_ESTABLISHED. Never ENSEMBLE_CALIBRATED / CALIBRATION_PASS /
INVESTMENT_VALUE_SUPPORTED. Does not replace synthetic ``phase8`` path.
SCHEMA stays vms-0.2.phase12; package 0.2.0rc1.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.assumptions import cite
from vms.ensemble import (
    MethodDistribution,
    build_ensemble,
    samples_from_point,
)
from vms.ensemble.protocols import EnsembleMode
from vms.methods.protocol import MethodResult
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.metadata import ArtifactStamp, content_run_id, sha256_of, write_artifact
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)

PRIOR_ONLY_FI_STATUS = "R8_PRIOR_ONLY_FI_ENSEMBLE_NOT_INVESTMENT_ADVICE"
INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
CST = timezone(timedelta(hours=8))

METHOD_RIM_TRACK_A = "residual_income"
METHOD_PB_COMMON = "pb_common"
METHOD_TRACK_B_EXIT = "rim_track_b_exit"

DemoScenario = Literal[
    "track_a_only",
    "track_a_pb",
    "track_b_skip",
    "track_b_eligible",
    "incompatible",
]


class PriorOnlyFiBundleError(ValueError):
    pass


def _basis_field(basis: OutputBasis) -> str:
    return {
        OutputBasis.EQUITY: "equity_value",
        OutputBasis.EV: "enterprise_value",
        OutputBasis.NAV: "nav",
        OutputBasis.PER_SHARE: "value_per_share",
        OutputBasis.MARKET_PRICE: "market_price",
    }[basis]


def method_results_from_components(
    components: Sequence[MethodDistribution],
) -> list[MethodResult]:
    results: list[MethodResult] = []
    for c in components:
        field = _basis_field(c.output_basis)
        med = c.median if c.median is not None else 0.0
        results.append(
            MethodResult(
                method_id=c.method_id,
                status=c.status,
                detail="r8 FI PRIOR_ONLY component",
                output_basis=[c.output_basis],
                values={field: {"p50": med, "mean": c.mean}},
                diagnostics=dict(c.diagnostics),
            )
        )
    return results


def build_fi_method_components(
    *,
    rim_vps: float,
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    basis: OutputBasis = OutputBasis.PER_SHARE,
    seed: int = 42,
    n_samples: int = 96,
    pb_vps: float | None = None,
    track_b_exit_center: float | None = None,
    track_b_hist_n: int = 0,
    include_track_b_skip_record: bool = True,
) -> tuple[list[MethodDistribution], list[dict[str, Any]]]:
    """Build FI-compatible MethodDistributions for PRIOR_ONLY research mixture.

    Track A (``residual_income``) is required. ``pb_common`` joins when ``pb_vps``
    is provided. Track B joins **only** when ``track_b_hist_n >= MIN_HIST_PB_POINTS``
    **and** ``track_b_exit_center`` is provided; otherwise SKIP (no invented OEI /
    no default PB / not in weights).
    """
    if not (rim_vps > 0) or not _finite(rim_vps):
        raise PriorOnlyFiBundleError("rim_vps (Track A) must be a finite positive center")
    if basis is OutputBasis.EV:
        raise PriorOnlyFiBundleError(
            "FI PRIOR_ONLY research path refuses EV basis for deposit-taking RIM "
            "(equity / per-share only)"
        )

    components: list[MethodDistribution] = []
    track_b_ledger: list[dict[str, Any]] = []

    components.append(
        MethodDistribution(
            method_id=METHOD_RIM_TRACK_A,
            samples=samples_from_point(float(rim_vps), n=n_samples, seed=seed),
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=basis,
            eligible=True,
            diagnostics={
                "center": float(rim_vps),
                "channel": "track_a_rim",
                "synthetic": True,
                "assumption": "ENSEMBLE-PRIOR-ONLY-FI-v1",
            },
        )
    )

    if pb_vps is not None:
        if not (pb_vps > 0) or not _finite(pb_vps):
            raise PriorOnlyFiBundleError("pb_vps must be finite positive when provided")
        components.append(
            MethodDistribution(
                method_id=METHOD_PB_COMMON,
                samples=samples_from_point(float(pb_vps), n=n_samples, seed=seed + 17),
                status=MethodEligibilityStatus.VALID,
                target=target,
                output_basis=basis,
                eligible=True,
                diagnostics={
                    "center": float(pb_vps),
                    "channel": "pb_roe_relative",
                    "synthetic": True,
                },
            )
        )

    hist_n = int(track_b_hist_n)
    track_b_ok = (
        hist_n >= MIN_HIST_PB_POINTS
        and track_b_exit_center is not None
        and _finite(track_b_exit_center)
        and float(track_b_exit_center) > 0
    )
    if track_b_ok:
        components.append(
            MethodDistribution(
                method_id=METHOD_TRACK_B_EXIT,
                samples=samples_from_point(
                    float(track_b_exit_center), n=n_samples, seed=seed + 34
                ),
                status=MethodEligibilityStatus.VALID,
                target=target,
                output_basis=basis,
                eligible=True,
                diagnostics={
                    "center": float(track_b_exit_center),
                    "channel": "track_b_exit",
                    "hist_n": hist_n,
                    "min_required": MIN_HIST_PB_POINTS,
                    "synthetic": True,
                    "note": (
                        "Exit-price channel on declared basis; research PRIOR_ONLY only. "
                        "Not intrinsic ground truth (EVAL-IV-NOT-PRICE-TRUTH-v1)."
                    ),
                },
            )
        )
        track_b_ledger.append(
            {
                "method_id": METHOD_TRACK_B_EXIT,
                "status": "ELIGIBLE",
                "hist_n": hist_n,
                "min_required": MIN_HIST_PB_POINTS,
                "in_weights": True,
            }
        )
    elif include_track_b_skip_record:
        # Honest SKIP record — ineligible component never enters mixture weights.
        skip_reason = (
            "HIST_PB_BELOW_MIN"
            if hist_n < MIN_HIST_PB_POINTS
            else "TRACK_B_EXIT_CENTER_MISSING"
        )
        components.append(
            MethodDistribution(
                method_id=METHOD_TRACK_B_EXIT,
                samples=(),
                status=MethodEligibilityStatus.INELIGIBLE,
                target=target,
                output_basis=basis,
                eligible=False,
                diagnostics={
                    "channel": "track_b_exit",
                    "hist_n": hist_n,
                    "min_required": MIN_HIST_PB_POINTS,
                    "skip_reason": skip_reason,
                    "in_weights": False,
                    "synthetic": True,
                },
            )
        )
        track_b_ledger.append(
            {
                "method_id": METHOD_TRACK_B_EXIT,
                "status": "SKIP",
                "hist_n": hist_n,
                "min_required": MIN_HIST_PB_POINTS,
                "skip_reason": skip_reason,
                "in_weights": False,
            }
        )

    return components, track_b_ledger


def _finite(x: float) -> bool:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf")


def _incompatible_components(target: ValuationTarget) -> list[MethodDistribution]:
    """EV vs PER_SHARE — must refuse when requested_basis=PER_SHARE."""
    return [
        MethodDistribution(
            method_id="ev_only_stub",
            samples=samples_from_point(500.0, n=32, seed=1),
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=OutputBasis.EV,
            eligible=True,
        ),
        MethodDistribution(
            method_id=METHOD_RIM_TRACK_A,
            samples=samples_from_point(12.0, n=32, seed=2),
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=OutputBasis.PER_SHARE,
            eligible=True,
        ),
    ]


def demo_components(
    scenario: DemoScenario,
    *,
    target: ValuationTarget = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
    seed: int = 42,
) -> tuple[list[MethodDistribution], list[dict[str, Any]]]:
    """Synthetic FI-shaped demos for offline wiring / tests (not real market data)."""
    if scenario == "incompatible":
        return _incompatible_components(target), []
    if scenario == "track_a_only":
        return build_fi_method_components(
            rim_vps=12.0,
            target=target,
            seed=seed,
            include_track_b_skip_record=False,
        )
    if scenario == "track_a_pb":
        return build_fi_method_components(
            rim_vps=12.0,
            pb_vps=10.5,
            target=target,
            seed=seed,
            include_track_b_skip_record=False,
        )
    if scenario == "track_b_skip":
        return build_fi_method_components(
            rim_vps=12.0,
            pb_vps=10.5,
            track_b_hist_n=5,
            track_b_exit_center=None,
            target=target,
            seed=seed,
            include_track_b_skip_record=True,
        )
    if scenario == "track_b_eligible":
        return build_fi_method_components(
            rim_vps=12.0,
            pb_vps=10.5,
            track_b_hist_n=MIN_HIST_PB_POINTS,
            track_b_exit_center=11.0,
            target=target,
            seed=seed,
            include_track_b_skip_record=True,
        )
    raise PriorOnlyFiBundleError(f"unknown demo scenario: {scenario}")


def build_prior_only_fi_bundle(
    out: Path,
    *,
    scenario: DemoScenario = "track_b_skip",
    seed: int = 42,
    n_draws: int = 1000,
    target: ValuationTarget | None = None,
    components: Sequence[MethodDistribution] | None = None,
    track_b_ledger: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write R8 PRIOR_ONLY FI artifacts: method_results/, ensemble_report, summary."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    assumptions = cite(
        "ENSEMBLE-PRIOR-ONLY-FI-v1",
        "EVAL-IV-NOT-PRICE-TRUTH-v1",
        "EVAL-RIM-FI-DEPOSIT-WF-v1",
    )

    if components is None:
        comps, ledger = demo_components(scenario, target=tgt, seed=seed)
    else:
        comps = list(components)
        ledger = list(track_b_ledger or [])
        if not any(c.method_id == METHOD_RIM_TRACK_A and c.eligible for c in comps):
            raise PriorOnlyFiBundleError(
                "FI PRIOR_ONLY requires eligible residual_income (Track A)"
            )

    method_results = method_results_from_components(
        [c for c in comps if c.eligible and c.samples]
    )

    # Production refusal (default) — mixture must stay null
    prod = build_ensemble(
        comps,
        target=tgt,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="production",
        n_draws=n_draws,
        seed=seed,
        method_results_for_compat=method_results or None,
        compute_l1o=False,
    )

    # PRIOR_ONLY research mixture (labeled exploratory)
    research = build_ensemble(
        comps,
        target=tgt,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="research_prior",
        n_draws=n_draws,
        seed=seed,
        method_results_for_compat=method_results or None,
    )

    incompat = build_ensemble(
        _incompatible_components(tgt),
        target=tgt,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="research_prior",
        n_draws=200,
        seed=seed,
        compute_l1o=False,
    )

    # Hard guards — never emit forbidden labels
    for label, report in (("production", prod), ("research", research)):
        blob = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
        if "ENSEMBLE_CALIBRATED" in blob and report.ensemble_status == "ENSEMBLE_CALIBRATED":
            raise PriorOnlyFiBundleError(f"{label} must not claim ENSEMBLE_CALIBRATED")
        if report.investment_value != INVESTMENT_LABEL:
            raise PriorOnlyFiBundleError(f"{label} must keep INVESTMENT_VALUE_NOT_ESTABLISHED")
        if report.calibration_status == ClaimStatus.CALIBRATION_PASS.value:
            raise PriorOnlyFiBundleError(f"{label} must not claim CALIBRATION_PASS")

    if prod.mixture is not None:
        raise PriorOnlyFiBundleError("production intent must refuse mixture")
    if scenario != "incompatible":
        # Phase 8 checklist needs ≥2 eligible components to combine.
        eligible_ids = {
            c.method_id
            for c in comps
            if c.eligible and c.status in {
                MethodEligibilityStatus.VALID,
                MethodEligibilityStatus.LOW_CONFIDENCE,
            } and c.samples
        }
        if (
            len(eligible_ids) >= 2
            and research.compatibility.compatible
            and research.mixture is None
        ):
            raise PriorOnlyFiBundleError(
                "research_prior with ≥2 compatible FI components expected a PRIOR_ONLY mixture"
            )
        if research.weight_artifact is not None:
            for mid in research.weight_artifact.weights:
                if mid == METHOD_TRACK_B_EXIT and mid not in eligible_ids:
                    raise PriorOnlyFiBundleError("Track B SKIP must not appear in weights")
            for c in comps:
                if (
                    c.method_id == METHOD_TRACK_B_EXIT
                    and not c.eligible
                    and c.method_id in (research.weight_artifact.weights or {})
                ):
                    raise PriorOnlyFiBundleError("ineligible Track B entered weights")

    stamp = ArtifactStamp(
        run_id=content_run_id(
            kind="prior-only-fi",
            scenario=scenario,
            seed=seed,
            target=tgt.value,
            n_draws=n_draws,
            config=sha256_of({"scenario": scenario, "n_comps": len(comps)}),
        ),
    )

    write_artifact(
        out,
        "config_snapshot.json",
        {
            "scenario": scenario,
            "n_draws": n_draws,
            "seed": seed,
            "target": tgt.value,
            "requested_output_basis": OutputBasis.PER_SHARE.value,
            "min_hist_pb_points": MIN_HIST_PB_POINTS,
            "assumptions": assumptions,
            "schema_version": SCHEMA_VERSION,
            "implemented_phase": IMPLEMENTED_PHASE,
            "data_label": "SYNTHETIC_FI_PRIOR_ONLY — not real market data",
        },
        stamp,
    )

    mr_dir = out / "method_results"
    mr_dir.mkdir(parents=True, exist_ok=True)
    for c in comps:
        write_artifact(
            mr_dir,
            f"{c.method_id}.json",
            {
                **c.model_dump(mode="json"),
                "n_samples": len(c.samples),
                "schema_version": SCHEMA_VERSION,
                "implemented_phase": IMPLEMENTED_PHASE,
            },
            stamp,
        )

    if research.weight_artifact is not None:
        write_artifact(
            out,
            "intrinsic_value_weights.json",
            research.weight_artifact.model_dump(mode="json"),
            stamp,
        )

    ensemble_payload = {
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "run_id": stamp.run_id,
        "production_refusal": prod.model_dump(mode="json"),
        "research_prior": research.model_dump(mode="json"),
        "incompatible_demo": incompat.model_dump(mode="json"),
        "track_b_ledger": list(ledger),
        "investment_value": INVESTMENT_LABEL,
        "calibrated_claim": False,
        "warning": (
            "R8 FI PRIOR_ONLY research mixture (SPEC §13.3). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            f"Track B requires hist_n>={MIN_HIST_PB_POINTS}."
        ),
    }
    write_artifact(out, "ensemble_report.json", ensemble_payload, stamp)

    write_artifact(
        out,
        "simulation_metadata.json",
        {
            "status": PRIOR_ONLY_FI_STATUS,
            "implemented_phase": IMPLEMENTED_PHASE,
            "schema_version": SCHEMA_VERSION,
            "investment_value": INVESTMENT_LABEL,
            "calibrated_claim": False,
            "warning": (
                "R8 deposit-taking FI PRIOR_ONLY wiring. Research path only. "
                "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
                "Does not lift industry.unsupported (银行/非银). "
                f"Track B hist_n < {MIN_HIST_PB_POINTS} → SKIP, not in weights."
            ),
            "data_label": "SYNTHETIC_FI_PRIOR_ONLY — not real market data",
            "seed": seed,
            "scenario": scenario,
            "assumptions": assumptions,
            "min_hist_pb_points": MIN_HIST_PB_POINTS,
            "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        },
        stamp,
    )

    weight_ids = (
        sorted(research.weight_artifact.weights.keys())
        if research.weight_artifact is not None
        else []
    )
    summary = {
        "status": PRIOR_ONLY_FI_STATUS,
        "schema_version": SCHEMA_VERSION,
        "implemented_phase": IMPLEMENTED_PHASE,
        "investment_value": INVESTMENT_LABEL,
        "run_id": stamp.run_id,
        "out": str(out),
        "seed": seed,
        "scenario": scenario,
        "target": tgt.value,
        "requested_output_basis": OutputBasis.PER_SHARE.value,
        "production_ensemble_status": prod.ensemble_status,
        "production_calibration_status": prod.calibration_status,
        "production_mixture": prod.mixture is not None,
        "production_mode": (
            prod.mode.value if isinstance(prod.mode, EnsembleMode) else str(prod.mode)
        ),
        "research_ensemble_status": research.ensemble_status,
        "research_calibration_status": research.calibration_status,
        "research_mode": (
            research.mode.value
            if isinstance(research.mode, EnsembleMode)
            else str(research.mode)
        ),
        "research_mixture": research.mixture is not None,
        "research_protocol": (
            research.weight_artifact.protocol.protocol_id.value
            if research.weight_artifact
            else None
        ),
        "research_weight_method_ids": weight_ids,
        "equal_weight_labeled_prior_only": True,
        "calibrated_claim": False,
        "ENSEMBLE_CALIBRATED": False,
        "CALIBRATION_PASS": False,
        "incompatible_demo_status": incompat.ensemble_status,
        "incompatible_demo_mixture": incompat.mixture is not None,
        "track_b_ledger": list(ledger),
        "track_b_in_weights": METHOD_TRACK_B_EXIT in weight_ids,
        "min_hist_pb_points": MIN_HIST_PB_POINTS,
        "assumption": "ENSEMBLE-PRIOR-ONLY-FI-v1",
        "assumptions": assumptions,
        "artifacts": [
            "ensemble_report.json",
            "method_results/",
            "simulation_metadata.json",
        ],
    }
    write_artifact(out, "prior_only_fi_summary.json", summary, stamp)
    return summary


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "PRIOR_ONLY_FI_STATUS",
    "METHOD_RIM_TRACK_A",
    "METHOD_PB_COMMON",
    "METHOD_TRACK_B_EXIT",
    "PriorOnlyFiBundleError",
    "build_fi_method_components",
    "build_prior_only_fi_bundle",
    "demo_components",
    "dump_summary",
    "method_results_from_components",
]
