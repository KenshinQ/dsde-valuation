"""Sum-of-the-parts (VMS-0.2 Phase 6, SPEC §12.7)."""

from vms.methods.sotp.math import HoldingDiscount, SegmentLine, SotpResult, compute_sotp
from vms.methods.sotp.plugin import SotpMethod

__all__ = [
    "HoldingDiscount",
    "SegmentLine",
    "SotpResult",
    "compute_sotp",
    "SotpMethod",
]
