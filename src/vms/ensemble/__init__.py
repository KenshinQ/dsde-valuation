"""Ensemble subsystem (VMS-0.2 Phase 8, SPEC §13.3–13.5 / §17.4).

Distributional mixture with named weight protocols, calibration checklist,
and disagreement / leave-one-method-out diagnostics. Production calibrated
ensemble is refused without OOS evidence; PRIOR_ONLY equal-weight is an
explicitly labeled research baseline only.
"""

from vms.ensemble.build import EnsembleReport, build_ensemble
from vms.ensemble.checklist import (
    CalibrationEvidence,
    EnsembleChecklist,
    evaluate_checklist,
    production_status_from_checklist,
)
from vms.ensemble.disagreement import (
    BetweenMethodDisagreement,
    LeaveOneOutCase,
    LeaveOneOutReport,
    between_method_disagreement,
    leave_one_method_out,
    prior_equal_l1o_demo,
)
from vms.ensemble.mixture import (
    MethodDistribution,
    MixtureDistribution,
    filter_eligible_components,
    mix_distributions,
    samples_from_point,
    diagnostics_with_midcycle_passthrough,
    method_distribution_from_result,
)
from vms.ensemble.protocols import (
    PROTOCOL_VERSIONS,
    EnsembleMode,
    ScoringRule,
    WeightProtocol,
    WeightProtocolId,
    make_intrinsic_protocol,
    make_market_outcome_protocol,
    make_prior_equal_protocol,
)
from vms.ensemble.weights import (
    WEIGHT_SUM_TOL,
    WeightArtifact,
    WeightValidationError,
    equal_prior_weights,
    market_outcome_weight_artifact,
    refuse_reuse_market_as_intrinsic,
    validate_weight_map,
)

__all__ = [
    "PROTOCOL_VERSIONS",
    "EnsembleMode",
    "ScoringRule",
    "WeightProtocol",
    "WeightProtocolId",
    "make_intrinsic_protocol",
    "make_market_outcome_protocol",
    "make_prior_equal_protocol",
    "WEIGHT_SUM_TOL",
    "WeightArtifact",
    "WeightValidationError",
    "equal_prior_weights",
    "market_outcome_weight_artifact",
    "refuse_reuse_market_as_intrinsic",
    "validate_weight_map",
    "CalibrationEvidence",
    "EnsembleChecklist",
    "evaluate_checklist",
    "production_status_from_checklist",
    "MethodDistribution",
    "MixtureDistribution",
    "filter_eligible_components",
    "mix_distributions",
    "samples_from_point",
    "diagnostics_with_midcycle_passthrough",
    "method_distribution_from_result",
    "BetweenMethodDisagreement",
    "LeaveOneOutCase",
    "LeaveOneOutReport",
    "between_method_disagreement",
    "leave_one_method_out",
    "prior_equal_l1o_demo",
    "EnsembleReport",
    "build_ensemble",
]
