"""Property checks for Phase 11 evaluation invariants."""

from __future__ import annotations

from vms.evaluation.labels import assign_labels
from vms.evaluation.metrics import point_errors
from vms.schemas.contracts import ClaimStatus


def test_property_synthetic_never_investment_supported():
    for eng, dq, cal in [
        (True, True, True),
        (True, True, False),
        (True, True, None),
        (False, False, None),
    ]:
        lab = assign_labels(
            engineering_ok=eng,
            data_quality_ok=dq,
            calibration_ok=cal,
            data_label="SYNTHETIC",
            predeclared_oos_alpha=True,  # even if caller tries
            ensemble_calibrated=True,  # even if caller tries
        )
        assert lab["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
        assert lab["ENSEMBLE_CALIBRATED"] is False


def test_property_inadequate_sample_forces_insufficient():
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=True,  # would-be pass
        data_label="REAL_A_SHARE",
        n_unbiased_scored=2,
        min_oos_for_calibration=5,
        predeclared_oos_alpha=False,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["CALIBRATION_PASS"] is not True


def test_property_point_errors_mae_nonnegative():
    err = point_errors([1.0, 2.0, 3.0], [1.5, 1.0, 3.0])
    assert err["n"] == 3
    assert err["mae"] >= 0
    assert err["rmse"] >= 0
