"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 3 delivers operating-company drivers, fundamental regimes,
correlated path sampling, statement projection and capital-allocation policies
(SPEC §20). Method math / ensemble / exit-price estimator are not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase3"
IMPLEMENTED_PHASE = "PHASE_3"
"""VMS-0.2 Phase 3: drivers + regimes + path bundle baseline (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
