"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 11 adds PIT-safe walk-forward evaluation, baselines, proper scoring,
sensitivity/uncertainty attribution and release gates (SPEC §16–§17 / §20). Phase 12
docs/examples release polish is not claimed done.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase11"
IMPLEMENTED_PHASE = "PHASE_11"
"""VMS-0.2 Phase 11: walk-forward calibration + sensitivity (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
