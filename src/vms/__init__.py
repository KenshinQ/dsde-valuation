"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 7 hardens deterministic routing, soft suitability diagnostics,
normalization and method disagreement (SPEC §20). Ensemble / exit-price
estimator are not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase7"
IMPLEMENTED_PHASE = "PHASE_7"
"""VMS-0.2 Phase 7: router hardening + method comparison (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
