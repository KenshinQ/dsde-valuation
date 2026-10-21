"""Engineering vs investment / calibration labels (SPEC §17.4, Phase 11).

Synthetic never claims investment value supported. Inadequate OOS evidence
yields CALIBRATION_INSUFFICIENT — never an inferred calibration success.
"""

from __future__ import annotations

from typing import Any, Literal

from vms.schemas.contracts import ClaimStatus

InvestmentLabel = Literal["INVESTMENT_VALUE_NOT_ESTABLISHED", "INVESTMENT_VALUE_SUPPORTED"]


def assign_labels(
    *,
    engineering_ok: bool,
    data_quality_ok: bool,
    calibration_ok: bool | None,
    data_label: str,
    predeclared_oos_alpha: bool = False,
    ensemble_calibrated: bool = False,
    min_oos_for_calibration: int = 5,
    n_unbiased_scored: int | None = None,
) -> dict[str, Any]:
    """Always separate engineering success from investment alpha (SPEC §2.12 / §17.4).

    - ``calibration_ok is None`` or too-few OOS rows → ``CALIBRATION_INSUFFICIENT``
      (not an inferred PASS).
    - ``ENSEMBLE_CALIBRATED`` only when caller passes ``ensemble_calibrated=True``
      with real OOS evidence; synthetic Phase 11 demos never set this.
    - ``INVESTMENT_VALUE_SUPPORTED`` only with predeclared leakage-safe OOS alpha
      evidence on non-synthetic data.
    """
    synthetic = "SYNTHETIC" in (data_label or "").upper()
    if synthetic or not predeclared_oos_alpha:
        inv: InvestmentLabel = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value  # type: ignore[assignment]
        inv_reason = (
            "Synthetic or no predeclared leakage-safe OOS alpha evidence "
            "(SPEC §17.4; never claim supported on synthetic demo)"
        )
    else:
        inv = ClaimStatus.INVESTMENT_VALUE_SUPPORTED.value  # type: ignore[assignment]
        inv_reason = "Predeclared leakage-safe OOS evidence supplied by caller"

    # Calibration gate: inadequate sample → INSUFFICIENT, not success.
    if n_unbiased_scored is not None and n_unbiased_scored < min_oos_for_calibration:
        calibration_ok = None
    if calibration_ok is None:
        cal_status = "INSUFFICIENT"
        cal_claim = ClaimStatus.CALIBRATION_INSUFFICIENT.value
        cal_pass: bool | None = None
    elif calibration_ok:
        cal_status = "PASS"
        cal_claim = ClaimStatus.CALIBRATION_PASS.value
        cal_pass = True
    else:
        cal_status = "FAIL"
        cal_claim = "CALIBRATION_FAIL"
        cal_pass = False

    ensemble_claim = (
        ClaimStatus.ENSEMBLE_CALIBRATED.value
        if ensemble_calibrated and not synthetic
        else ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    )
    # Synthetic / Phase 11 offline demos never emit ENSEMBLE_CALIBRATED.
    if synthetic:
        ensemble_claim = ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        ensemble_calibrated = False

    release_gates = {
        ClaimStatus.ENGINEERING_PASS.value: bool(engineering_ok),
        ClaimStatus.DATA_QUALITY_PASS.value: bool(data_quality_ok),
        ClaimStatus.CALIBRATION_PASS.value: cal_pass is True,
        ClaimStatus.CALIBRATION_INSUFFICIENT.value: cal_claim
        == ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        ClaimStatus.ENSEMBLE_CALIBRATED.value: bool(ensemble_calibrated) and not synthetic,
        ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value: inv
        == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value,
    }

    return {
        "ENGINEERING_PASS": bool(engineering_ok),
        "DATA_QUALITY_PASS": bool(data_quality_ok),
        "CALIBRATION_PASS": cal_pass,
        "CALIBRATION_STATUS": cal_status,
        "CALIBRATION_CLAIM": cal_claim,
        "ENSEMBLE_CALIBRATED": bool(ensemble_calibrated) and not synthetic,
        "ENSEMBLE_CLAIM": ensemble_claim,
        "investment_value": inv,
        "investment_value_reason": inv_reason,
        "data_label": data_label,
        "release_gates": release_gates,
    }


__all__ = ["InvestmentLabel", "assign_labels"]
