"""Deterministic method router (VMS-0.2 Phase 7, SPEC §11.3–11.4 / §13).

Hard gates + soft suitability diagnostics + comparison/disagreement.
Never fabricates a default DCF. Never builds a calibrated ensemble (Phase 8).
"""

from vms.router.compatibility import (
    CompatibilityIssue,
    CompatibilityReport,
    check_combination_compatibility,
    refuse_uncalibrated_blend,
)
from vms.router.compare import (
    DisagreementReport,
    MethodComparisonReport,
    NormalizedMethodValue,
    compare_methods,
    normalize_method_result,
)
from vms.router.route import (
    MethodConsideration,
    RouteReport,
    method_eligibility_payload,
    route_methods,
)
from vms.router.suitability import (
    SUITABILITY_DIMENSIONS,
    SoftSuitability,
    compute_soft_suitability,
)

__all__ = [
    "RouteReport",
    "MethodConsideration",
    "route_methods",
    "method_eligibility_payload",
    "SUITABILITY_DIMENSIONS",
    "SoftSuitability",
    "compute_soft_suitability",
    "CompatibilityIssue",
    "CompatibilityReport",
    "check_combination_compatibility",
    "refuse_uncalibrated_blend",
    "NormalizedMethodValue",
    "DisagreementReport",
    "MethodComparisonReport",
    "compare_methods",
    "normalize_method_result",
]
