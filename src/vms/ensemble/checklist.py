"""§13.3 ensemble production checklist and calibration metadata.

A production ensemble requires all checklist items, including OOS evaluation.
Inadequate evidence → CALIBRATION_INSUFFICIENT / ENSEMBLE_UNCALIBRATED; keep
method-specific results (SPEC §13.3 / §17.4). Phase 8 has no real walk-forward
sample — OOS remains False unless a caller injects explicit evidence (tests only).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vms.ensemble.protocols import EnsembleMode, WeightProtocol
from vms.schemas.contracts import ClaimStatus, ValuationTarget


class CalibrationEvidence(BaseModel):
    """Declared calibration support for a stated target (SPEC §13.3.4–13.3.5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: ValuationTarget
    sample_size: int = 0
    oos_evaluated: bool = False
    baselines_compared: bool = False
    leakage_clear: bool = False
    weights_frozen_before_test: bool = False
    subgroup_instability_reported: bool = False
    note: str = ""

    @property
    def adequate_for_production(self) -> bool:
        return (
            self.sample_size > 0
            and self.oos_evaluated
            and self.baselines_compared
            and self.leakage_clear
            and self.weights_frozen_before_test
        )


class EnsembleChecklist(BaseModel):
    """All six §13.3 requirements, evaluated for a candidate ensemble."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    same_defined_target: bool
    eligible_and_compatible: bool
    documented_weight_protocol: bool
    adequate_calibration_or_prior_only: bool
    out_of_sample_evaluation: bool
    disagreement_reported: bool
    prior_only_mode: bool = False
    evidence: CalibrationEvidence | None = None
    failed_items: list[str] = Field(default_factory=list)
    note: str = ""

    @property
    def production_eligible(self) -> bool:
        """True only when every production gate passes and mode is not PRIOR_ONLY."""
        return (
            self.same_defined_target
            and self.eligible_and_compatible
            and self.documented_weight_protocol
            and self.adequate_calibration_or_prior_only
            and self.out_of_sample_evaluation
            and self.disagreement_reported
            and not self.prior_only_mode
            and self.evidence is not None
            and self.evidence.adequate_for_production
        )

    @property
    def prior_only_research_ok(self) -> bool:
        """Research mixture may proceed when labeled PRIOR_ONLY (not calibrated)."""
        return (
            self.prior_only_mode
            and self.same_defined_target
            and self.eligible_and_compatible
            and self.documented_weight_protocol
            and self.disagreement_reported
        )


def evaluate_checklist(
    *,
    target: ValuationTarget,
    compatible: bool,
    protocol: WeightProtocol | None,
    evidence: CalibrationEvidence | None,
    disagreement_reported: bool,
    n_eligible_components: int,
) -> EnsembleChecklist:
    """Evaluate §13.3 gates. Does not authorize ENSEMBLE_CALIBRATED by itself."""
    prior = bool(protocol is not None and protocol.is_prior_only)
    failed: list[str] = []

    same_target = protocol is not None and protocol.target is target
    if not same_target:
        failed.append("same_defined_target")

    eligible_ok = compatible and n_eligible_components >= 2
    if not eligible_ok:
        failed.append("eligible_and_compatible")

    documented = protocol is not None and bool(protocol.protocol_version)
    if not documented:
        failed.append("documented_weight_protocol")

    oos = bool(evidence is not None and evidence.oos_evaluated and evidence.sample_size > 0)
    if prior:
        adequate = True  # prior-only is the transparent alternative to OOS
    else:
        adequate = bool(evidence is not None and evidence.adequate_for_production)
        if not adequate:
            failed.append("adequate_calibration_evidence")
        if not oos:
            failed.append("out_of_sample_evaluation")

    if not disagreement_reported:
        failed.append("disagreement_reported")

    note = (
        "PRIOR_ONLY research mode — mixture may be computed but is not "
        "ENSEMBLE_CALIBRATED (SPEC §13.3)."
        if prior
        else (
            "Production checklist incomplete; refuse calibrated blend "
            "(SPEC §13.3 / §17.4)."
            if failed
            else "Production checklist satisfied (requires separate release gate)."
        )
    )
    return EnsembleChecklist(
        same_defined_target=same_target,
        eligible_and_compatible=eligible_ok,
        documented_weight_protocol=documented,
        adequate_calibration_or_prior_only=adequate if not prior else True,
        out_of_sample_evaluation=oos if not prior else False,
        disagreement_reported=disagreement_reported,
        prior_only_mode=prior,
        evidence=evidence,
        failed_items=failed,
        note=note,
    )


def production_status_from_checklist(checklist: EnsembleChecklist) -> str:
    """Map checklist → ClaimStatus string. Never returns ENSEMBLE_CALIBRATED in Phase 8
    without evidence; even then callers must still refuse unless explicitly authorized.
    """
    if checklist.production_eligible:
        # Phase 8 build layer still refuses to emit ENSEMBLE_CALIBRATED without an
        # explicit allow_calibrated_claim flag (see build.py) — default here is PASS
        # path reserved for Phase 11.
        return ClaimStatus.ENSEMBLE_CALIBRATED.value
    if checklist.prior_only_research_ok:
        return ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    if not checklist.out_of_sample_evaluation and not checklist.prior_only_mode:
        return ClaimStatus.CALIBRATION_INSUFFICIENT.value
    return ClaimStatus.ENSEMBLE_UNCALIBRATED.value


__all__ = [
    "CalibrationEvidence",
    "EnsembleChecklist",
    "evaluate_checklist",
    "production_status_from_checklist",
]
