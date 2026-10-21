"""Method plugin contract and declarative registry (VMS-0.2, SPEC §11).

Phase 4 enables FCFF/FCFE/DDM; Phase 5 enables pe/pb/ev_*; Phase 6 enables
residual_income / nav / sotp. Hard eligibility gates must pass before value_paths;
no default DCF / ensemble.
"""

from vms.methods.eligibility import (
    EligibilityResult,
    GateReason,
    evaluate_hard_gates,
    refuse_unimplemented_run,
)
from vms.methods.protocol import (
    MethodConfig,
    MethodDiagnostics,
    MethodResult,
    ValuationContext,
    ValuationMethod,
)
from vms.methods.registry import MethodRegistry, build_registry_from_config

__all__ = [
    "ValuationMethod",
    "ValuationContext",
    "MethodConfig",
    "MethodResult",
    "MethodDiagnostics",
    "EligibilityResult",
    "GateReason",
    "evaluate_hard_gates",
    "refuse_unimplemented_run",
    "MethodRegistry",
    "build_registry_from_config",
]
