"""Method plugin contract and declarative registry (VMS-0.2 Phase 2, SPEC §11).

Phase 2 registers declared methods as NOT_IMPLEMENTED. Hard eligibility gates
must refuse running them; no default DCF is fabricated.
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
