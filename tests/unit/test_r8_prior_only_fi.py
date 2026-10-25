"""R8 FI PRIOR_ONLY ensemble wiring acceptance (ENSEMBLE-PRIOR-ONLY-FI-v1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.ensemble import EnsembleMode, build_ensemble
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.prior_only_fi_bundle import (
    METHOD_PB_COMMON,
    METHOD_RIM_TRACK_A,
    METHOD_TRACK_B_EXIT,
    PRIOR_ONLY_FI_STATUS,
    PriorOnlyFiBundleError,
    build_fi_method_components,
    build_prior_only_fi_bundle,
    demo_components,
)
from vms.schemas.contracts import ClaimStatus, OutputBasis, ValuationTarget

TARGET = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
INV = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value


def test_ac1_research_prior_mixture_labeled_prior_only(tmp_path: Path):
    summary = build_prior_only_fi_bundle(
        tmp_path / "r8",
        scenario="track_a_pb",
        seed=7,
        n_draws=400,
    )
    assert summary["status"] == PRIOR_ONLY_FI_STATUS
    assert summary["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summary["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summary["research_mode"] == EnsembleMode.PRIOR_ONLY.value
    assert summary["research_mixture"] is True
    assert summary["research_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert summary["research_calibration_status"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert summary["calibrated_claim"] is False
    assert summary["ENSEMBLE_CALIBRATED"] is False
    assert summary["CALIBRATION_PASS"] is False
    assert summary["investment_value"] == INV
    assert summary["equal_weight_labeled_prior_only"] is True
    assert summary["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-v1"
    assert METHOD_RIM_TRACK_A in summary["research_weight_method_ids"]
    assert METHOD_PB_COMMON in summary["research_weight_method_ids"]
    body = json.loads((tmp_path / "r8" / "ensemble_report.json").read_text())
    assert body["calibrated_claim"] is False
    assert "ENSEMBLE_CALIBRATED" not in body["research_prior"]["ensemble_status"]
    assert body["research_prior"]["ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert body["research_prior"]["mixture"] is not None
    assert body["research_prior"]["mode"] == EnsembleMode.PRIOR_ONLY.value


def test_ac2_production_intent_refuses_mixture(tmp_path: Path):
    summary = build_prior_only_fi_bundle(
        tmp_path / "r8p",
        scenario="track_a_pb",
        seed=3,
        n_draws=200,
    )
    assert summary["production_mixture"] is False
    assert summary["production_mode"] == EnsembleMode.PRODUCTION_REFUSED.value
    assert summary["production_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    body = json.loads((tmp_path / "r8p" / "ensemble_report.json").read_text())
    assert body["production_refusal"]["mixture"] is None
    assert body["production_refusal"]["combined_value"] is None


def test_ac3_incompatible_bases_refused(tmp_path: Path):
    summary = build_prior_only_fi_bundle(
        tmp_path / "r8i",
        scenario="incompatible",
        seed=1,
        n_draws=100,
    )
    assert summary["research_mixture"] is False
    assert summary["incompatible_demo_status"] == "NOT_COMBINED_INCOMPATIBLE"
    assert summary["incompatible_demo_mixture"] is False
    comps, _ = demo_components("incompatible", target=TARGET)
    report = build_ensemble(
        comps,
        target=TARGET,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="research_prior",
        compute_l1o=False,
        seed=1,
    )
    assert report.compatibility.compatible is False
    assert report.mixture is None


def test_ac3_track_b_below_min_not_in_weights(tmp_path: Path):
    assert MIN_HIST_PB_POINTS == 12
    comps, ledger = build_fi_method_components(
        rim_vps=12.0,
        pb_vps=10.0,
        track_b_hist_n=5,
        track_b_exit_center=None,
        include_track_b_skip_record=True,
    )
    assert ledger[0]["status"] == "SKIP"
    assert ledger[0]["in_weights"] is False
    summary = build_prior_only_fi_bundle(
        tmp_path / "r8skip",
        scenario="track_b_skip",
        seed=9,
        n_draws=300,
    )
    assert summary["track_b_in_weights"] is False
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    assert summary["min_hist_pb_points"] == 12
    tb = json.loads((tmp_path / "r8skip" / "method_results" / f"{METHOD_TRACK_B_EXIT}.json").read_text())
    assert tb["eligible"] is False
    assert tb["n_samples"] == 0


def test_ac3_track_b_eligible_enters_weights(tmp_path: Path):
    summary = build_prior_only_fi_bundle(
        tmp_path / "r8el",
        scenario="track_b_eligible",
        seed=11,
        n_draws=300,
    )
    assert summary["track_b_in_weights"] is True
    assert METHOD_TRACK_B_EXIT in summary["research_weight_method_ids"]
    assert summary["research_mixture"] is True
    assert summary["calibrated_claim"] is False


def test_ac4_forbidden_labels_never_emitted(tmp_path: Path):
    """Hard-assert status fields stay on the R8 allow-list (not string deny-list)."""
    from vms.reporting.prior_only_fi_bundle import (
        ALLOWED_CALIBRATION_STATUS,
        ALLOWED_ENSEMBLE_STATUS,
        ALLOWED_INVESTMENT_VALUE,
    )

    for scenario in ("track_a_only", "track_a_pb", "track_b_skip", "track_b_eligible"):
        summary = build_prior_only_fi_bundle(
            tmp_path / scenario,
            scenario=scenario,
            seed=2,
            n_draws=150,
        )
        # Hard status-field assertions (allow-list)
        assert summary["status"] == PRIOR_ONLY_FI_STATUS
        assert summary["investment_value"] in ALLOWED_INVESTMENT_VALUE
        assert summary["investment_value"] == INV
        assert summary["research_ensemble_status"] in ALLOWED_ENSEMBLE_STATUS
        assert summary["production_ensemble_status"] in ALLOWED_ENSEMBLE_STATUS
        assert summary["research_calibration_status"] in ALLOWED_CALIBRATION_STATUS
        assert summary["production_calibration_status"] in ALLOWED_CALIBRATION_STATUS
        assert summary["research_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        assert summary["research_calibration_status"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
        assert summary["production_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        assert summary["calibrated_claim"] is False
        assert summary["ENSEMBLE_CALIBRATED"] is False
        assert summary["CALIBRATION_PASS"] is False

        body = json.loads((tmp_path / scenario / "ensemble_report.json").read_text())
        assert body["calibrated_claim"] is False
        assert body["investment_value"] == INV
        rp = body["research_prior"]
        assert rp["ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        assert rp["calibration_status"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
        assert rp["investment_value"] == INV
        pr = body["production_refusal"]
        assert pr["ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
        assert pr["investment_value"] == INV
        assert pr["mixture"] is None


def test_ac4_requires_track_a(tmp_path: Path):
    with pytest.raises(PriorOnlyFiBundleError, match="residual_income"):
        build_prior_only_fi_bundle(tmp_path / "empty", components=[])


def test_ac3_injected_components_track_b_hist_recheck(tmp_path: Path):
    """Injected components= must re-check Track B hist_n; below MIN stays out of weights."""
    from vms.ensemble import MethodDistribution, samples_from_point
    from vms.schemas.contracts import MethodEligibilityStatus

    # Craft an "eligible-looking" Track B with hist_n=5 (< MIN=12)
    bad_tb = MethodDistribution(
        method_id=METHOD_TRACK_B_EXIT,
        samples=samples_from_point(11.0, n=32, seed=99),
        status=MethodEligibilityStatus.VALID,
        target=TARGET,
        output_basis=OutputBasis.PER_SHARE,
        eligible=True,
        diagnostics={"channel": "track_b_exit", "hist_n": 5, "synthetic": True},
    )
    rim = MethodDistribution(
        method_id=METHOD_RIM_TRACK_A,
        samples=samples_from_point(12.0, n=32, seed=1),
        status=MethodEligibilityStatus.VALID,
        target=TARGET,
        output_basis=OutputBasis.PER_SHARE,
        eligible=True,
        diagnostics={"channel": "track_a_rim", "synthetic": True},
    )
    pb = MethodDistribution(
        method_id=METHOD_PB_COMMON,
        samples=samples_from_point(10.0, n=32, seed=2),
        status=MethodEligibilityStatus.VALID,
        target=TARGET,
        output_basis=OutputBasis.PER_SHARE,
        eligible=True,
        diagnostics={"channel": "pb_roe_relative", "synthetic": True},
    )
    summary = build_prior_only_fi_bundle(
        tmp_path / "inject_tb",
        scenario="track_a_pb",
        components=[rim, pb, bad_tb],
        seed=5,
        n_draws=200,
    )
    assert summary["track_b_in_weights"] is False
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    assert summary["calibrated_claim"] is False
    ledger = summary["track_b_ledger"]
    assert ledger and ledger[0]["status"] == "SKIP"
    assert ledger[0]["hist_n"] == 5
    assert ledger[0].get("sanitized_on_inject") is True
    tb = json.loads(
        (tmp_path / "inject_tb" / "method_results" / f"{METHOD_TRACK_B_EXIT}.json").read_text()
    )
    assert tb["eligible"] is False
    assert tb["n_samples"] == 0


def test_schema_and_package_unchanged():
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    from vms import __version__

    assert __version__ == "0.2.0rc1"
    assert MIN_HIST_PB_POINTS == 12


def test_track_a_only_keeps_method_no_forced_mixture(tmp_path: Path):
    """Single eligible method cannot form a mixture (Phase 8 checklist ≥2)."""
    summary = build_prior_only_fi_bundle(
        tmp_path / "a_only",
        scenario="track_a_only",
        seed=4,
        n_draws=100,
    )
    assert summary["research_mixture"] is False
    assert summary["calibrated_claim"] is False
    assert summary["production_mixture"] is False
    assert (tmp_path / "a_only" / "method_results" / f"{METHOD_RIM_TRACK_A}.json").is_file()
