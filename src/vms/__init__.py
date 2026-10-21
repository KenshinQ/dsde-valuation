"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 5 delivers relative multiples (P/E, P/B, EV/*) + Phase 4 cash-flow
plugins under the registry/router (SPEC §20). RIM/NAV/SOTP / ensemble / exit-price
estimator are not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase5"
IMPLEMENTED_PHASE = "PHASE_5"
"""VMS-0.2 Phase 4: core cash-flow methods FCFF/FCFE/DDM (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
