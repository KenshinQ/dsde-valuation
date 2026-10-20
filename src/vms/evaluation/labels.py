"""Engineering vs investment labels (SPEC §15.3). Synthetic never claims investment value supported."""

from __future__ import annotations

from typing import Any, Literal


InvestmentLabel = Literal["INVESTMENT_VALUE_NOT_ESTABLISHED", "INVESTMENT_VALUE_SUPPORTED"]


def assign_labels(*, engineering_ok: bool, data_quality_ok: bool, calibration_ok: bool | None,
                  data_label: str, predeclared_oos_alpha: bool = False) -> dict[str, Any]:
    """Always separate engineering success from investment alpha.

    VMS-0.1 synthetic / unlabeled OOS evidence => INVESTMENT_VALUE_NOT_ESTABLISHED.
    INVESTMENT_VALUE_SUPPORTED only if predeclared_oos_alpha and non-synthetic evidence.
    """
    synthetic = "SYNTHETIC" in (data_label or "").upper()
    if synthetic or not predeclared_oos_alpha:
        inv: InvestmentLabel = "INVESTMENT_VALUE_NOT_ESTABLISHED"
        inv_reason = ("Synthetic or no predeclared leakage-safe OOS alpha evidence "
                      "(SPEC §15.3; never claim supported on synthetic demo)")
    else:
        inv = "INVESTMENT_VALUE_SUPPORTED"
        inv_reason = "Predeclared leakage-safe OOS evidence supplied by caller"
    return {
        "ENGINEERING_PASS": bool(engineering_ok),
        "DATA_QUALITY_PASS": bool(data_quality_ok),
        "CALIBRATION_PASS": None if calibration_ok is None else bool(calibration_ok),
        "CALIBRATION_STATUS": (
            "INCONCLUSIVE" if calibration_ok is None else ("PASS" if calibration_ok else "FAIL")
        ),
        "investment_value": inv,
        "investment_value_reason": inv_reason,
        "data_label": data_label,
    }
