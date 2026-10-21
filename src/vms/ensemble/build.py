"""Ensemble build orchestration (SPEC §13.3–13.5 / §17.4).

Production calibrated ensemble is refused unless the full checklist passes AND
``allow_calibrated_claim`` is explicitly True (reserved for Phase 11+ with real
OOS evidence). Phase 8 default: PRIOR_ONLY research mixture (labeled) or
ENSEMBLE_UNCALIBRATED / CALIBRATION_INSUFFICIENT with method-specific results kept.
"""

from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vms.ensemble.checklist import (
    CalibrationEvidence,
    EnsembleChecklist,
    evaluate_checklist,
    production_status_from_checklist,
)
from vms.ensemble.disagreement import (
    BetweenMethodDisagreement,
    LeaveOneOutReport,
    between_method_disagreement,
    leave_one_method_out,
)
from vms.ensemble.mixture import (
    MethodDistribution,
    MixtureDistribution,
    filter_eligible_components,
    mix_distributions,
)
from vms.ensemble.protocols import (
    EnsembleMode,
    WeightProtocol,
    make_prior_equal_protocol,
)
from vms.ensemble.weights import (
    WeightArtifact,
    WeightValidationError,
    equal_prior_weights,
    market_outcome_weight_artifact,
    refuse_reuse_market_as_intrinsic,
    validate_weight_map,
)
from vms.router.compatibility import (
    CompatibilityReport,
    check_combination_compatibility,
)
from vms.schemas.contracts import (
    ClaimStatus,
    OutputBasis,
    ValuationTarget,
)

INVESTMENT_LABEL = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value


class EnsembleReport(BaseModel):
    """Full ensemble artifact: method-specific retained + optional mixture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: ValuationTarget
    requested_output_basis: OutputBasis
    horizon: int | None = None
    mode: EnsembleMode
    ensemble_status: str
    calibration_status: str
    checklist: EnsembleChecklist
    compatibility: CompatibilityReport
    weight_artifact: WeightArtifact | None = None
    # Separate market-outcome artifact when requested (SPEC §13.4 / AC5)
    market_outcome_weight_artifact: WeightArtifact | None = None
    mixture: MixtureDistribution | None = None
    method_distributions: list[MethodDistribution] = Field(default_factory=list)
    disagreement: BetweenMethodDisagreement
    leave_one_out: LeaveOneOutReport | None = None
    combined_value: None = None  # never a single blended point presented as truth
    investment_value: str = INVESTMENT_LABEL
    notes: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


def _refuse(
    *,
    target: ValuationTarget,
    basis: OutputBasis,
    horizon: int | None,
    mode: EnsembleMode,
    status: str,
    calibration_status: str,
    checklist: EnsembleChecklist,
    compatibility: CompatibilityReport,
    components: list[MethodDistribution],
    disagreement: BetweenMethodDisagreement,
    notes: list[str],
    weight_artifact: WeightArtifact | None = None,
    market_outcome_weight_artifact: WeightArtifact | None = None,
    leave_one_out: LeaveOneOutReport | None = None,
) -> EnsembleReport:
    return EnsembleReport(
        target=target,
        requested_output_basis=basis,
        horizon=horizon,
        mode=mode,
        ensemble_status=status,
        calibration_status=calibration_status,
        checklist=checklist,
        compatibility=compatibility,
        weight_artifact=weight_artifact,
        market_outcome_weight_artifact=market_outcome_weight_artifact,
        mixture=None,
        method_distributions=components,
        disagreement=disagreement,
        leave_one_out=leave_one_out,
        combined_value=None,
        investment_value=INVESTMENT_LABEL,
        notes=notes,
    )


def build_ensemble(
    components: Sequence[MethodDistribution],
    *,
    target: ValuationTarget,
    requested_output_basis: OutputBasis = OutputBasis.EQUITY,
    horizon: int | None = None,
    protocol: WeightProtocol | None = None,
    weights: dict[str, float] | None = None,
    evidence: CalibrationEvidence | None = None,
    # research | production — production never emits ENSEMBLE_CALIBRATED in Phase 8
    # without allow_calibrated_claim (which still requires full checklist).
    intent: Literal["research_prior", "production"] = "production",
    allow_calibrated_claim: bool = False,
    n_draws: int = 2000,
    seed: int = 42,
    compute_l1o: bool = True,
    # Optional separate market-outcome weights (AC5); never used as intrinsic.
    market_outcome_weights: dict[str, float] | None = None,
    method_results_for_compat: list[Any] | None = None,
) -> EnsembleReport:
    """Build or refuse an ensemble under §13.3 / §17.4 rules.

    - ``intent=production`` without adequate evidence → CALIBRATION_INSUFFICIENT /
      ENSEMBLE_UNCALIBRATED; method-specific distributions retained; no mixture.
    - ``intent=research_prior`` with equal (or supplied) weights → PRIOR_ONLY
      mixture labeled ENSEMBLE_UNCALIBRATED; never ENSEMBLE_CALIBRATED.
    - Incompatible components → NOT_COMBINED; no mixture.
    - ``allow_calibrated_claim`` is False by default; Phase 8 tests must not set it
      unless simulating a future gate with injected evidence.
    """
    notes: list[str] = []
    all_components = list(components)
    eligible = filter_eligible_components(all_components)
    disagreement = between_method_disagreement(eligible)

    # Compatibility: prefer MethodResult list when provided; else synthesize check
    # from MethodDistribution targets/bases.
    if method_results_for_compat is not None:
        compatibility = check_combination_compatibility(
            method_results_for_compat,
            target=target,
            horizon=horizon,
            requested_output_basis=requested_output_basis,
        )
    else:
        compatibility = _compat_from_distributions(
            eligible, target=target, horizon=horizon, basis=requested_output_basis,
        )

    # Resolve protocol
    if intent == "research_prior":
        proto = protocol or make_prior_equal_protocol(target)
        if not proto.is_prior_only:
            # Force prior labeling — cannot smuggle calibrated claim via research path
            proto = make_prior_equal_protocol(target)
            notes.append(
                "research_prior intent forced PRIOR_ONLY_EQUAL_WEIGHT protocol label"
            )
        mode = EnsembleMode.PRIOR_ONLY
    else:
        proto = protocol
        mode = EnsembleMode.PRODUCTION_REFUSED

    checklist = evaluate_checklist(
        target=target,
        compatible=compatibility.compatible,
        protocol=proto,
        evidence=evidence,
        disagreement_reported=disagreement.n_methods >= 1,
        n_eligible_components=len(eligible),
    )

    # Separate market-outcome artifact (AC5) — never fed into intrinsic mixture here
    market_art: WeightArtifact | None = None
    if market_outcome_weights is not None:
        market_art = market_outcome_weight_artifact(
            market_outcome_weights,
            target=target,
            calibration_sample_size=(evidence.sample_size if evidence else 0),
            oos_evaluated=bool(evidence and evidence.oos_evaluated),
        )
        notes.append(
            "market_outcome_weight_artifact persisted separately; "
            "not used as intrinsic reliability weights (SPEC §13.4)"
        )

    # --- Incompatible: hard refuse ---
    if not compatibility.compatible:
        notes.append("incompatible methods cannot form an ensemble (SPEC §13.2)")
        return _refuse(
            target=target,
            basis=requested_output_basis,
            horizon=horizon,
            mode=mode,
            status="NOT_COMBINED_INCOMPATIBLE",
            calibration_status=ClaimStatus.CALIBRATION_INSUFFICIENT.value,
            checklist=checklist,
            compatibility=compatibility,
            components=all_components,
            disagreement=disagreement,
            notes=notes,
            market_outcome_weight_artifact=market_art,
        )

    # --- Production path ---
    # Phase 8 NEVER emits ENSEMBLE_CALIBRATED (no real OOS walk-forward yet; P11).
    # allow_calibrated_claim is accepted for forward-compat but still refuses the
    # calibrated label here; checklist.production_eligible is reported for diagnostics.
    if intent == "production":
        _ = allow_calibrated_claim  # reserved; Phase 8 ignores authorization
        _ = production_status_from_checklist(checklist)
        cal = (
            ClaimStatus.CALIBRATION_INSUFFICIENT.value
            if not (evidence and evidence.adequate_for_production)
            else ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        )
        if checklist.production_eligible and allow_calibrated_claim:
            notes.append(
                "checklist.production_eligible=True but Phase 8 build still refuses "
                "ENSEMBLE_CALIBRATED (no walk-forward release; SPEC §17.4 / Phase 11)."
            )
            cal = ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        notes.append(
            "production ensemble refused: uncalibrated or checklist incomplete "
            "(SPEC §13.3 / §17.4). Method-specific distributions retained."
        )
        return _refuse(
            target=target,
            basis=requested_output_basis,
            horizon=horizon,
            mode=EnsembleMode.PRODUCTION_REFUSED,
            status=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
            calibration_status=cal,
            checklist=checklist,
            compatibility=compatibility,
            components=all_components,
            disagreement=disagreement,
            notes=notes,
            market_outcome_weight_artifact=market_art,
        )

    # --- Research PRIOR_ONLY path: may compute labeled mixture ---
    if not checklist.prior_only_research_ok:
        notes.append(
            "PRIOR_ONLY research mixture also refused "
            f"(failed={checklist.failed_items})"
        )
        return _refuse(
            target=target,
            basis=requested_output_basis,
            horizon=horizon,
            mode=EnsembleMode.PRIOR_ONLY,
            status=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
            calibration_status=ClaimStatus.CALIBRATION_INSUFFICIENT.value,
            checklist=checklist,
            compatibility=compatibility,
            components=all_components,
            disagreement=disagreement,
            notes=notes,
            market_outcome_weight_artifact=market_art,
        )

    # Build equal (or supplied) prior weights — never labeled calibrated
    if weights is not None:
        cleaned = validate_weight_map(weights)
        # Ensure only eligible ids
        eligible_ids = {c.method_id for c in eligible}
        for mid in cleaned:
            if mid not in eligible_ids:
                raise WeightValidationError(
                    f"ineligible method {mid} in research weights"
                )
        art = WeightArtifact(
            artifact_kind="intrinsic_value_weights",
            protocol=proto,
            weights=cleaned,
            method_ids=sorted(cleaned.keys()),
            calibration_sample_size=0,
            oos_evaluated=False,
            note="PRIOR_ONLY research weights (caller-supplied); not calibrated",
        )
    else:
        art = equal_prior_weights([c.method_id for c in eligible], target=target)

    refuse_reuse_market_as_intrinsic(art)

    mixture = mix_distributions(
        eligible,
        art,
        n_draws=n_draws,
        seed=seed,
        status_label=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
        note=(
            "PRIOR_ONLY research mixture (SPEC §13.3). "
            "Equal-weight / exploratory baseline — NOT ENSEMBLE_CALIBRATED."
        ),
    )
    l1o = None
    if compute_l1o and len(eligible) >= 2:
        l1o = leave_one_method_out(
            eligible, art, n_draws=max(200, n_draws // 2), seed=seed,
            status_label=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
        )
    notes.append(
        "research PRIOR_ONLY mixture computed; investment_value remains "
        "INVESTMENT_VALUE_NOT_ESTABLISHED; not a production calibrated ensemble"
    )
    return EnsembleReport(
        target=target,
        requested_output_basis=requested_output_basis,
        horizon=horizon,
        mode=EnsembleMode.PRIOR_ONLY,
        ensemble_status=ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
        calibration_status=ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        checklist=checklist,
        compatibility=compatibility,
        weight_artifact=art,
        market_outcome_weight_artifact=market_art,
        mixture=mixture,
        method_distributions=all_components,
        disagreement=disagreement,
        leave_one_out=l1o,
        combined_value=None,
        investment_value=INVESTMENT_LABEL,
        notes=notes,
    )


def _compat_from_distributions(
    eligible: list[MethodDistribution],
    *,
    target: ValuationTarget,
    horizon: int | None,
    basis: OutputBasis,
) -> CompatibilityReport:
    """Lightweight compatibility when MethodResult objects are unavailable."""
    from vms.methods.protocol import MethodResult
    from vms.schemas.contracts import MethodEligibilityStatus

    results: list[MethodResult] = []
    result_targets: dict[str, ValuationTarget] = {}
    result_horizons: dict[str, int | None] = {}
    for c in eligible:
        # Map basis → scalar field name for checker
        field = {
            OutputBasis.EQUITY: "equity_value",
            OutputBasis.EV: "enterprise_value",
            OutputBasis.NAV: "nav",
            OutputBasis.PER_SHARE: "value_per_share",
            OutputBasis.MARKET_PRICE: "market_price",
        }[c.output_basis]
        med = c.median if c.median is not None else 0.0
        results.append(
            MethodResult(
                method_id=c.method_id,
                status=c.status,
                output_basis=[c.output_basis],
                values={field: {"p50": med}},
            )
        )
        result_targets[c.method_id] = c.target
        result_horizons[c.method_id] = horizon
    return check_combination_compatibility(
        results,
        target=target,
        horizon=horizon,
        requested_output_basis=basis,
        result_targets=result_targets,
        result_horizons=result_horizons,
    )


__all__ = [
    "INVESTMENT_LABEL",
    "EnsembleReport",
    "build_ensemble",
]
