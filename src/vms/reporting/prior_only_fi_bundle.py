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

# Allow-list (not deny-list) for R8 runtime claim labels.
ALLOWED_ENSEMBLE_STATUS = frozenset(
    {
        ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
        "NOT_COMBINED_INCOMPATIBLE",
    }
)
ALLOWED_CALIBRATION_STATUS = frozenset(
    {
        ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        # Production path may surface ENSEMBLE_UNCALIBRATED as calibration_status
        # when evidence.adequate_for_production is True but Phase 8 still refuses
        # the calibrated ensemble label (build.py production branch).
        ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
    }
)
ALLOWED_INVESTMENT_VALUE = frozenset({INVESTMENT_LABEL})

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


def _finite_positive_sample(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) == float("inf") or f <= 0:
        return None
    return f


def _samples_or_point(
    center: float,
    *,
    live: Sequence[float] | None,
    n: int,
    seed: int,
) -> tuple[tuple[float, ...], str, int | None]:
    """Prefer live path samples when present (len >= 1); else samples_from_point.

    Live arrays are **re-filtered** to finite positive floats (SF3) before use;
    if nothing remains after filtering, fall back to ``samples_from_point``.

    Returns ``(samples, sample_generation, n_live_samples_or_None)``.
    """
    if live is not None and len(live) >= 1:
        xs_list: list[float] = []
        for x in live:
            got = _finite_positive_sample(x)
            if got is not None:
                xs_list.append(got)
        if xs_list:
            xs = tuple(xs_list)
            return xs, "live_paths", len(xs)
    return samples_from_point(float(center), n=n, seed=seed), "samples_from_point", None


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
    rim_samples: Sequence[float] | None = None,
    pb_samples: Sequence[float] | None = None,
    track_b_samples: Sequence[float] | None = None,
) -> tuple[list[MethodDistribution], list[dict[str, Any]]]:
    """Build FI-compatible MethodDistributions for PRIOR_ONLY research mixture.

    Track A (``residual_income``) is required. ``pb_common`` joins when ``pb_vps``
    is provided. Track B joins **only** when ``track_b_hist_n >= MIN_HIST_PB_POINTS``
    **and** ``track_b_exit_center`` is provided; otherwise SKIP (no invented OEI /
    no default PB / not in weights).

    Optional ``rim_samples`` / ``pb_samples`` / ``track_b_samples`` (R10 live paths)
    replace ``samples_from_point`` when length >= 1.
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

    rim_xs, rim_gen, rim_n_live = _samples_or_point(
        float(rim_vps), live=rim_samples, n=n_samples, seed=seed
    )
    rim_diag: dict[str, Any] = {
        "center": float(rim_vps),
        "channel": "track_a_rim",
        "synthetic": rim_gen != "live_paths",
        "sample_generation": rim_gen,
        "assumption": "ENSEMBLE-PRIOR-ONLY-FI-v1",
    }
    if rim_n_live is not None:
        rim_diag["n_live_samples"] = rim_n_live
    components.append(
        MethodDistribution(
            method_id=METHOD_RIM_TRACK_A,
            samples=rim_xs,
            status=MethodEligibilityStatus.VALID,
            target=target,
            output_basis=basis,
            eligible=True,
            diagnostics=rim_diag,
        )
    )

    if pb_vps is not None:
        if not (pb_vps > 0) or not _finite(pb_vps):
            raise PriorOnlyFiBundleError("pb_vps must be finite positive when provided")
        pb_xs, pb_gen, pb_n_live = _samples_or_point(
            float(pb_vps), live=pb_samples, n=n_samples, seed=seed + 17
        )
        pb_diag: dict[str, Any] = {
            "center": float(pb_vps),
            "channel": "pb_roe_relative",
            "synthetic": pb_gen != "live_paths",
            "sample_generation": pb_gen,
        }
        if pb_n_live is not None:
            pb_diag["n_live_samples"] = pb_n_live
        components.append(
            MethodDistribution(
                method_id=METHOD_PB_COMMON,
                samples=pb_xs,
                status=MethodEligibilityStatus.VALID,
                target=target,
                output_basis=basis,
                eligible=True,
                diagnostics=pb_diag,
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
        tb_xs, tb_gen, tb_n_live = _samples_or_point(
            float(track_b_exit_center),
            live=track_b_samples,
            n=n_samples,
            seed=seed + 34,
        )
        tb_diag: dict[str, Any] = {
            "center": float(track_b_exit_center),
            "channel": "track_b_exit",
            "hist_n": hist_n,
            "min_required": MIN_HIST_PB_POINTS,
            "synthetic": tb_gen != "live_paths",
            "sample_generation": tb_gen,
            "note": (
                "Exit-price channel on declared basis; research PRIOR_ONLY only. "
                "Not intrinsic ground truth (EVAL-IV-NOT-PRICE-TRUTH-v1)."
            ),
        }
        if tb_n_live is not None:
            tb_diag["n_live_samples"] = tb_n_live
        components.append(
            MethodDistribution(
                method_id=METHOD_TRACK_B_EXIT,
                samples=tb_xs,
                status=MethodEligibilityStatus.VALID,
                target=target,
                output_basis=basis,
                eligible=True,
                diagnostics=tb_diag,
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



def _track_b_hist_n(component: MethodDistribution) -> int:
    """Read hist_n from diagnostics; missing → 0 (fail closed)."""
    raw = component.diagnostics.get("hist_n", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _demote_track_b(
    component: MethodDistribution,
    *,
    hist_n: int,
    skip_reason: str,
) -> MethodDistribution:
    """Force Track B out of weights when hist gate fails (immutable rebuild)."""
    diag = dict(component.diagnostics)
    diag.update(
        {
            "channel": "track_b_exit",
            "hist_n": hist_n,
            "min_required": MIN_HIST_PB_POINTS,
            "skip_reason": skip_reason,
            "in_weights": False,
            "sanitized_on_inject": True,
        }
    )
    return MethodDistribution(
        method_id=METHOD_TRACK_B_EXIT,
        samples=(),
        status=MethodEligibilityStatus.INELIGIBLE,
        target=component.target,
        output_basis=component.output_basis,
        eligible=False,
        diagnostics=diag,
    )


def sanitize_injected_components(
    components: Sequence[MethodDistribution],
    *,
    track_b_ledger: Sequence[dict[str, Any]] | None = None,
) -> tuple[list[MethodDistribution], list[dict[str, Any]]]:
    """Re-check Track B ``hist_n >= MIN_HIST_PB_POINTS`` on injected ``components=``.

    Callers may pass MethodDistribution objects that look eligible. R8 must not
    trust that: any ``rim_track_b_exit`` with hist_n below MIN (or missing hist_n)
    is demoted to SKIP / ineligible and kept out of weights.
    """
    out: list[MethodDistribution] = []
    ledger: list[dict[str, Any]] = list(track_b_ledger or [])
    saw_track_b = False
    for c in components:
        if c.method_id != METHOD_TRACK_B_EXIT:
            out.append(c)
            continue
        saw_track_b = True
        hist_n = _track_b_hist_n(c)
        if c.eligible and hist_n >= MIN_HIST_PB_POINTS and c.samples:
            out.append(c)
            if not any(e.get("method_id") == METHOD_TRACK_B_EXIT for e in ledger):
                ledger.append(
                    {
                        "method_id": METHOD_TRACK_B_EXIT,
                        "status": "ELIGIBLE",
                        "hist_n": hist_n,
                        "min_required": MIN_HIST_PB_POINTS,
                        "in_weights": True,
                    }
                )
            continue
        # Already SKIP / ineligible: preserve caller skip_reason (R9 B1 /
        # R12 calibrate-rim blob reasons). Do not wipe TRACK_B_CENTER_NOT_PER_SHARE
        # or explicit calibrate-rim skip_reason into a generic inject label.
        if not c.eligible:
            out.append(c)
            existing = c.diagnostics.get("skip_reason")
            if not any(e.get("method_id") == METHOD_TRACK_B_EXIT for e in ledger):
                ledger.append(
                    {
                        "method_id": METHOD_TRACK_B_EXIT,
                        "status": "SKIP",
                        "hist_n": hist_n,
                        "min_required": MIN_HIST_PB_POINTS,
                        "skip_reason": existing
                        or (
                            "HIST_PB_BELOW_MIN"
                            if hist_n < MIN_HIST_PB_POINTS
                            else "TRACK_B_INJECT_INELIGIBLE"
                        ),
                        "in_weights": False,
                    }
                )
            continue
        # Eligible-looking but hist/samples gate failed → demote.
        skip_reason = (
            "HIST_PB_BELOW_MIN"
            if hist_n < MIN_HIST_PB_POINTS
            else "TRACK_B_INJECT_INELIGIBLE"
        )
        demoted = _demote_track_b(c, hist_n=hist_n, skip_reason=skip_reason)
        out.append(demoted)
        # Replace or append ledger entry for Track B
        ledger = [e for e in ledger if e.get("method_id") != METHOD_TRACK_B_EXIT]
        ledger.append(
            {
                "method_id": METHOD_TRACK_B_EXIT,
                "status": "SKIP",
                "hist_n": hist_n,
                "min_required": MIN_HIST_PB_POINTS,
                "skip_reason": skip_reason,
                "in_weights": False,
                "sanitized_on_inject": True,
            }
        )
    if not saw_track_b:
        # Preserve caller ledger if any; no Track B to sanitize.
        pass
    return out, ledger


def build_prior_only_fi_bundle(
    out: Path,
    *,
    scenario: DemoScenario | str = "track_b_skip",
    seed: int = 42,
    n_draws: int = 1000,
    target: ValuationTarget | None = None,
    components: Sequence[MethodDistribution] | None = None,
    track_b_ledger: Sequence[dict[str, Any]] | None = None,
    data_label: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write R8 PRIOR_ONLY FI artifacts: method_results/, ensemble_report, summary.

    When ``components`` are injected (e.g. R9/R10 live value-rim or R12
    calibrate-rim forecast adapter), pass ``data_label`` so artifacts are
    not stamped SYNTHETIC. Demo path (components is None) keeps the
    synthetic label.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tgt = target or ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    src = source_meta.get("source") if source_meta else None
    is_live = src == "value_rim"
    is_calibrate_rim = src == "calibrate_rim"
    has_live_samples = bool(
        source_meta
        and (
            source_meta.get("sample_generation") == "live_paths"
            or source_meta.get("assumption")
            == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"
        )
    )
    if is_calibrate_rim:
        primary_assumption = "ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1"
    elif is_live and has_live_samples:
        primary_assumption = "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"
    elif is_live:
        primary_assumption = "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
    else:
        primary_assumption = "ENSEMBLE-PRIOR-ONLY-FI-v1"
    cite_ids = [
        "ENSEMBLE-PRIOR-ONLY-FI-v1",
        "EVAL-IV-NOT-PRICE-TRUTH-v1",
        "EVAL-RIM-FI-DEPOSIT-WF-v1",
    ]
    if is_calibrate_rim:
        # Parallel research ingest from calibrate-rim forecast blob (extends LIVE-MD).
        cite_ids.insert(0, "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1")
        cite_ids.insert(0, "ENSEMBLE-PRIOR-ONLY-FI-CALIBRATE-RIM-MD-v1")
    elif is_live:
        # Live path: stamp LIVE-MD; R10 LIVE-SAMPLES when path samples present.
        cite_ids.insert(0, "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1")
        if has_live_samples:
            cite_ids.insert(0, "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1")
    assumptions = cite(*cite_ids)

    if components is None:
        comps, ledger = demo_components(scenario, target=tgt, seed=seed)
    else:
        comps, ledger = sanitize_injected_components(
            components, track_b_ledger=track_b_ledger
        )
        if not any(c.method_id == METHOD_RIM_TRACK_A and c.eligible for c in comps):
            raise PriorOnlyFiBundleError(
                "FI PRIOR_ONLY requires eligible residual_income (Track A)"
            )

    if data_label is None:
        if components is None:
            effective_data_label = "SYNTHETIC_FI_PRIOR_ONLY — not real market data"
        else:
            effective_data_label = (
                "INJECTED_FI_PRIOR_ONLY — research path; not calibrated"
            )
    else:
        effective_data_label = data_label

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

    # Hard guards — allow-list only (never rely on deny-list of bad labels)
    for label, report in (("production", prod), ("research", research)):
        if report.ensemble_status not in ALLOWED_ENSEMBLE_STATUS:
            raise PriorOnlyFiBundleError(
                f"{label} ensemble_status={report.ensemble_status!r} "
                f"not in allow-list {sorted(ALLOWED_ENSEMBLE_STATUS)}"
            )
        if report.calibration_status not in ALLOWED_CALIBRATION_STATUS:
            raise PriorOnlyFiBundleError(
                f"{label} calibration_status={report.calibration_status!r} "
                f"not in allow-list {sorted(ALLOWED_CALIBRATION_STATUS)}"
            )
        if report.investment_value not in ALLOWED_INVESTMENT_VALUE:
            raise PriorOnlyFiBundleError(
                f"{label} investment_value={report.investment_value!r} "
                f"not in allow-list {sorted(ALLOWED_INVESTMENT_VALUE)}"
            )

    if incompat.ensemble_status not in ALLOWED_ENSEMBLE_STATUS:
        raise PriorOnlyFiBundleError(
            f"incompatible demo ensemble_status={incompat.ensemble_status!r} "
            f"not in allow-list {sorted(ALLOWED_ENSEMBLE_STATUS)}"
        )
    if incompat.investment_value not in ALLOWED_INVESTMENT_VALUE:
        raise PriorOnlyFiBundleError(
            f"incompatible demo investment_value={incompat.investment_value!r} "
            f"not in allow-list {sorted(ALLOWED_INVESTMENT_VALUE)}"
        )

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
            "data_label": effective_data_label,
            "source_meta": dict(source_meta) if source_meta else None,
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
            (
                (
                    f"calibrate-rim forecast → PRIOR_ONLY research mixture "
                    f"({primary_assumption}). "
                    if is_calibrate_rim
                    else (
                        (
                            f"R10 live value-rim path samples → PRIOR_ONLY research mixture "
                            f"({primary_assumption}). "
                            if has_live_samples
                            else (
                                f"R9 live value-rim → PRIOR_ONLY research mixture "
                                f"({primary_assumption}). "
                            )
                        )
                        if is_live
                        else "R8 FI PRIOR_ONLY research mixture (SPEC §13.3). "
                    )
                )
            )
            + "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED. "
            + "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
            + f"Track B requires hist_n>={MIN_HIST_PB_POINTS} and a PER_SHARE "
            + "exit center (never raw pb_center_used P/B multiple)."
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
                (
                    (
                        f"calibrate-rim forecast PRIOR_ONLY ingest "
                        f"({primary_assumption}). Research path only. "
                        if is_calibrate_rim
                        else (
                            (
                                f"R10 live value-rim path samples PRIOR_ONLY ingest "
                                f"({primary_assumption}). Research path only. "
                                if has_live_samples
                                else (
                                    f"R9 live value-rim PRIOR_ONLY ingest "
                                    f"({primary_assumption}). Research path only. "
                                )
                            )
                            if is_live
                            else "R8 deposit-taking FI PRIOR_ONLY wiring. Research path only. "
                        )
                    )
                )
                + "Not investment advice. INVESTMENT_VALUE_NOT_ESTABLISHED. "
                + (
                    "Does not lift industry.unsupported "
                    f"(see {primary_assumption}). "
                )
                + f"Track B hist_n < {MIN_HIST_PB_POINTS} or missing PER_SHARE "
                + "exit center → SKIP, not in weights."
            ),
            "data_label": effective_data_label,
            "source_meta": dict(source_meta) if source_meta else None,
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
        "assumption": primary_assumption,
        "assumptions": assumptions,
        "data_label": effective_data_label,
        "source_meta": dict(source_meta) if source_meta else None,
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
    "ALLOWED_CALIBRATION_STATUS",
    "ALLOWED_ENSEMBLE_STATUS",
    "ALLOWED_INVESTMENT_VALUE",
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
    "sanitize_injected_components",
]
