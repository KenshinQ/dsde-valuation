"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 8 adds ensemble mixture protocols, calibration checklist,
and disagreement / L1O diagnostics (SPEC §20). Exit-price estimator (P9)
and walk-forward calibration (P11) are not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase8"
IMPLEMENTED_PHASE = "PHASE_8"
"""VMS-0.2 Phase 8: ensemble + model uncertainty (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
