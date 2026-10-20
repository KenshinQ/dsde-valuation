"""VMS-0.1 — standalone valuation & conditional return engine for China A-shares.

Phases 0–10 complete (release-ready packaging). Optional DSDE adapter lives in
``vms.adapters.dsde``; core never requires DSDE installed.
"""

__version__ = "0.1.0"

SCHEMA_VERSION = "vms-0.1.0"
IMPLEMENTED_PHASE = "PHASE_10"
"""§17 package layout; Phase 10 = DSDE adapter + release readiness."""

from vms.engine import ValuationEngine
from vms.result import ValuationRunResult

__all__ = [
    "SCHEMA_VERSION",
    "IMPLEMENTED_PHASE",
    "ValuationEngine",
    "ValuationRunResult",
    "__version__",
]
