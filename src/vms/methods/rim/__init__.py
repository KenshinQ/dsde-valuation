"""Residual income method (VMS-0.2 Phase 6, SPEC §12.4)."""

from vms.methods.rim.math import (
    CleanSurplusReport,
    RimPathResult,
    assess_clean_surplus,
    residual_income_value,
)
from vms.methods.rim.plugin import ResidualIncomeMethod

__all__ = [
    "CleanSurplusReport",
    "RimPathResult",
    "assess_clean_surplus",
    "residual_income_value",
    "ResidualIncomeMethod",
]
