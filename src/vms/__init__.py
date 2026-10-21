"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 12 completes documentation, five offline examples, result-bundle
validation and release packaging (SPEC §19–§20 / §23). Engineering pass ≠ investment alpha.
Engineering pass ≠ investment alpha.
"""

__version__ = "0.2.0rc1"

SCHEMA_VERSION = "vms-0.2.phase12"
IMPLEMENTED_PHASE = "PHASE_12"
"""VMS-0.2 Phase 12: docs / examples / bundle validation release (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
