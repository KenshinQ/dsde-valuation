"""Residual income method (VMS-0.2 Phase 6, SPEC §12.4) + R1/R2 PIT bridge."""

from vms.methods.rim.from_snapshot import (
    BOOK_EQUITY_COMMON_RULE,
    BOOK_EQUITY_TE_RULE,
    RimBridgeError,
    RimBridgeResult,
    features_from_snapshot,
    rim_inputs_from_snapshot,
)
from vms.methods.rim.math import (
    CleanSurplusReport,
    RimPathResult,
    assess_clean_surplus,
    residual_income_value,
)
from vms.methods.rim.plugin import ResidualIncomeMethod

__all__ = [
    "BOOK_EQUITY_COMMON_RULE",
    "BOOK_EQUITY_TE_RULE",
    "CleanSurplusReport",
    "RimBridgeError",
    "RimBridgeResult",
    "RimPathResult",
    "ResidualIncomeMethod",
    "assess_clean_surplus",
    "features_from_snapshot",
    "residual_income_value",
    "rim_inputs_from_snapshot",
]
