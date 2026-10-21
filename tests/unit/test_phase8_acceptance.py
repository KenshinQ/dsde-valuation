"""VMS-0.2 Phase 8 acceptance (SPEC §20 Phase 8 / §13.3–13.5 / §17.4 / §24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.ensemble import (
    CalibrationEvidence,
    EnsembleMode,
    MethodDistribution,
    WeightProtocolId,
    WeightValidationError,
    build_ensemble,
    equal_prior_weights,
    evaluate_checklist,
    make_prior_equal_protocol,
    market_outcome_weight_artifact,
    mix_distributions,
    refuse_reuse_market_as_intrinsic,
    samples_from_point,
    validate_weight_map,
)
from vms.reporting.phase8_bundle import PHASE8_STATUS, build_phase8_bundle
from vms.schemas.contracts import (
    ClaimStatus,
    MethodEligibilityStatus,
    OutputBasis,
    ValuationTarget,
)

TARGET = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT


def _comps(n: int = 3) -> list[MethodDistribution]:
    centers = [1000.0, 900.0, 700.0][:n]
    ids = ["fcff_dcf", "fcfe_dcf", "ddm"][:n]
    out = []
    for i, (mid, c) in enumerate(zip(ids, centers)):
        out.append(
            MethodDistribution(
                method_id=mid,
                samples=samples_from_point(c, n=64, seed=10 + i),
                status=MethodEligibilityStatus.VALID,
                target=TARGET,
                output_basis=OutputBasis.EQUITY,
            )
        )
    return out


# ---- AC1: Uncalibrated / incompatible cannot form production ensemble ----
def test_ac1_uncalibrated_cannot_form_production_ensemble():
    comps = _comps()
    report = build_ensemble(comps, target=TARGET, intent="production", seed=42)
    assert report.mixture is None
    assert report.combined_value is None
    assert report.ensemble_status == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert report.calibration_status in {
        ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        ClaimStatus.ENSEMBLE_UNCALIBRATED.value,
    }
    assert report.investment_value == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert report.mode is EnsembleMode.PRODUCTION_REFUSED
    # method-specific retained
    assert len(report.method_distributions) == 3


def test_ac1_incompatible_cannot_form_ensemble():
    comps = [
        MethodDistribution(
            method_id="ev_only",
            samples=samples_from_point(500.0, n=32, seed=1),
            status=MethodEligibilityStatus.VALID,
            target=TARGET,
            output_basis=OutputBasis.EV,
        ),
        MethodDistribution(
            method_id="equity_only",
            samples=samples_from_point(400.0, n=32, seed=2),
            status=MethodEligibilityStatus.VALID,
            target=TARGET,
            output_basis=OutputBasis.EQUITY,
        ),
    ]
    report = build_ensemble(
        comps, target=TARGET, intent="research_prior", seed=1, compute_l1o=False,
    )
    assert report.compatibility.compatible is False
    assert report.mixture is None
    assert report.ensemble_status == "NOT_COMBINED_INCOMPATIBLE"


# ---- AC2: weights ≥0, sum to 1, named protocol ----
def test_ac2_weights_nonneg_sum_one_named_protocol():
    art = equal_prior_weights(["a", "b", "c"], target=TARGET)
    assert art.protocol.protocol_id is WeightProtocolId.PRIOR_ONLY_EQUAL_WEIGHT
    assert art.protocol.protocol_version
    assert art.protocol.target is TARGET
    assert art.protocol.scoring_rule.value == "NONE_PRIOR"
    s = sum(art.weights.values())
    assert abs(s - 1.0) < 1e-9
    assert all(w >= 0 for w in art.weights.values())
    validate_weight_map(art.weights)


def test_ac2_invalid_weights_rejected():
    with pytest.raises(WeightValidationError):
        validate_weight_map({"a": 0.5, "b": 0.6})
    with pytest.raises(WeightValidationError):
        validate_weight_map({"a": -0.1, "b": 1.1})


# ---- AC3: equal-weight not exposed as calibrated ----
def test_ac3_equal_weight_not_calibrated():
    comps = _comps()
    report = build_ensemble(
        comps, target=TARGET, intent="research_prior", n_draws=400, seed=7,
    )
    assert report.mode is EnsembleMode.PRIOR_ONLY
    assert report.ensemble_status == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert report.mixture is not None
    assert report.mixture.status_label != ClaimStatus.ENSEMBLE_CALIBRATED.value
    assert report.weight_artifact is not None
    assert report.weight_artifact.protocol.is_prior_only
    assert report.weight_artifact.oos_evaluated is False
    assert "PRIOR_ONLY" in (report.weight_artifact.note or "")
    # Explicit: never ENSEMBLE_CALIBRATED
    assert ClaimStatus.ENSEMBLE_CALIBRATED.value not in {
        report.ensemble_status,
        report.calibration_status,
        report.mixture.status_label,
    }


# ---- AC4: ensemble and method-specific both saved ----
def test_ac4_both_distributions_persisted(tmp_path: Path):
    summary = build_phase8_bundle(tmp_path, seed=42, fixture="mature", n_draws=300)
    assert summary["status"] == PHASE8_STATUS
    assert (tmp_path / "ensemble_report.json").is_file()
    mr = tmp_path / "method_results"
    assert mr.is_dir()
    files = sorted(p.name for p in mr.glob("*.json"))
    assert "fcff_dcf.json" in files
    assert "fcfe_dcf.json" in files
    assert "ddm.json" in files
    ens = json.loads((tmp_path / "ensemble_report.json").read_text())
    body = ens.get("payload", ens)
    assert "research_prior" in body
    assert body["research_prior"]["mixture"] is not None
    assert body["production_refusal"]["mixture"] is None


# ---- AC5: intrinsic vs market-outcome weights separate ----
def test_ac5_intrinsic_and_market_outcome_separate_artifacts():
    comps = _comps()
    report = build_ensemble(
        comps,
        target=TARGET,
        intent="research_prior",
        n_draws=200,
        seed=3,
        market_outcome_weights={"fcff_dcf": 0.5, "fcfe_dcf": 0.3, "ddm": 0.2},
        compute_l1o=False,
    )
    assert report.weight_artifact is not None
    assert report.weight_artifact.artifact_kind == "intrinsic_value_weights"
    assert report.market_outcome_weight_artifact is not None
    assert report.market_outcome_weight_artifact.artifact_kind == "MARKET_OUTCOME_WEIGHTING"
    assert (
        report.weight_artifact.artifact_kind
        != report.market_outcome_weight_artifact.artifact_kind
    )
    # Cannot reuse market as intrinsic
    with pytest.raises(WeightValidationError):
        refuse_reuse_market_as_intrinsic(report.market_outcome_weight_artifact)
    # market artifact constructor
    m = market_outcome_weight_artifact(
        {"fcff_dcf": 0.5, "fcfe_dcf": 0.5}, target=TARGET,
    )
    assert m.protocol.protocol_id is WeightProtocolId.MARKET_OUTCOME_WEIGHTING


def test_ac5_artifacts_written_separately(tmp_path: Path):
    build_phase8_bundle(tmp_path, seed=42, fixture="mature", n_draws=200)
    intrinsic = json.loads((tmp_path / "intrinsic_value_weights.json").read_text())
    market = json.loads((tmp_path / "market_outcome_weights.json").read_text())
    ib = intrinsic.get("payload", intrinsic)
    mb = market.get("payload", market)
    assert ib["artifact_kind"] == "intrinsic_value_weights"
    assert mb["artifact_kind"] == "MARKET_OUTCOME_WEIGHTING"


# ---- AC6: L1O and between-method disagreement on synthetic ----
def test_ac6_l1o_and_disagreement_synthetic():
    comps = _comps()
    report = build_ensemble(
        comps, target=TARGET, intent="research_prior", n_draws=500, seed=42,
    )
    assert report.disagreement.n_methods == 3
    assert report.disagreement.range is not None and report.disagreement.range > 0
    assert report.leave_one_out is not None
    assert len(report.leave_one_out.cases) == 3
    assert report.leave_one_out.max_abs_delta_median is not None
    left_ids = {c.left_out for c in report.leave_one_out.cases}
    assert left_ids == {"fcff_dcf", "fcfe_dcf", "ddm"}


# ---- Checklist: evidence-less production gate ----
def test_checklist_without_oos_not_production_eligible():
    proto = make_prior_equal_protocol(TARGET)
    # prior protocol → prior_only_research_ok, not production
    cl = evaluate_checklist(
        target=TARGET,
        compatible=True,
        protocol=proto,
        evidence=None,
        disagreement_reported=True,
        n_eligible_components=3,
    )
    assert cl.prior_only_research_ok
    assert not cl.production_eligible

    evidence = CalibrationEvidence(
        target=TARGET,
        sample_size=0,
        oos_evaluated=False,
    )
    from vms.ensemble import make_intrinsic_protocol

    proto2 = make_intrinsic_protocol(TARGET, calibrated=False)
    cl2 = evaluate_checklist(
        target=TARGET,
        compatible=True,
        protocol=proto2,
        evidence=evidence,
        disagreement_reported=True,
        n_eligible_components=3,
    )
    assert not cl2.production_eligible
    assert "adequate_calibration_evidence" in cl2.failed_items or not cl2.out_of_sample_evaluation


def test_ineligible_method_never_enters_mixture():
    comps = _comps(2)
    bad = MethodDistribution(
        method_id="broken",
        samples=samples_from_point(1.0, n=8, seed=9),
        status=MethodEligibilityStatus.INELIGIBLE,
        target=TARGET,
        output_basis=OutputBasis.EQUITY,
        eligible=False,
    )
    art = equal_prior_weights(["fcff_dcf", "fcfe_dcf", "broken"], target=TARGET)
    with pytest.raises(WeightValidationError):
        mix_distributions(comps + [bad], art, n_draws=50, seed=1)


def test_schema_version_phase8_contract():
    assert SCHEMA_VERSION == "vms-0.2.phase10"
    assert IMPLEMENTED_PHASE == "PHASE_10"
