"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 6 delivers RIM / NAV / SOTP under the registry/router (SPEC §20),
retaining Phase 4 cash-flow and Phase 5 multiples. Ensemble / exit-price
estimator are not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase6"
IMPLEMENTED_PHASE = "PHASE_6"
"""VMS-0.2 Phase 6: residual income, asset NAV, SOTP (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
