"""VMS-0.2 — Adaptive Multi-Method valuation & conditional return engine (A-shares).

VMS-0.1 (tagged ``vms-0.1``) is archived as ``SPEC_VMS-0.1.md``. Master tracks
VMS-0.2; Phase 0 establishes contracts, config validation, run IDs/hashes and a
synthetic offline baseline. Later 0.1 modules remain in-tree until rewritten;
they must not be read as completed 0.2 adaptive routing.
"""

__version__ = "0.2.0a0"

SCHEMA_VERSION = "vms-0.2.phase0"
IMPLEMENTED_PHASE = "PHASE_0"
"""VMS-0.2 Phase 0: contracts + deterministic baseline only (SPEC §20)."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
