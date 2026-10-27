"""R12 calibrate-rim forecast → MethodDistribution adapter acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
from vms.ensemble import EnsembleMode, build_ensemble
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.fi_method_distribution_adapter import (
    CALIBRATE_RIM_ASSUMPTION,
    CALIBRATE_RIM_DATA_LABEL,
    FiMethodDistributionAdapterError,
    SKIP_TRACK_B_CENTER_NOT_PER_SHARE,
    adapt_calibrate_rim_forecast,
    resolve_calibrate_rim_forecast_path,
)
from vms.reporting.prior_only_fi_bundle import (
    METHOD_PB_COMMON,
    METHOD_RIM_TRACK_A,
    METHOD_TRACK_B_EXIT,
    PRIOR_ONLY_FI_STATUS,
    build_prior_only_fi_bundle,
)
from vms.schemas.contracts import ClaimStatus, OutputBasis, ValuationTarget

TARGET = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
INV = ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SKIP_TB = FIXTURES / "calibrate_rim_forecast_track_a_skip_tb.json"
ELIG_TB = FIXTURES / "calibrate_rim_forecast_eligible_tb_no_exit.json"


def test_ac1_fixture_skip_tb_research_prior_only(tmp_path: Path):
    comps, ledger, meta = adapt_calibrate_rim_forecast(SKIP_TB, seed=7)
    assert meta["data_label"] == CALIBRATE_RIM_DATA_LABEL
    assert meta["source"] == "calibrate_rim"
    assert meta["synthetic"] is False
    assert meta["sample_generation"] == "samples_from_point"
    assert meta["assumption"] == CALIBRATE_RIM_ASSUMPTION
    assert meta["rim_vps_source"] == "forecasts.intrinsic_value.point"
    assert meta["rim_vps"] == pytest.approx(39.016978286598786)
    assert meta["pb_vps"] is None
    assert meta["track_b_in_weights_eligible"] is False
    assert meta["track_b_hist_n"] == 9
    assert meta["track_b_pb_center_used"] == pytest.approx(2.476872029213876)
    assert all(c.diagnostics.get("synthetic") is False for c in comps)
    assert all(
        c.diagnostics.get("sample_generation") == "samples_from_point" for c in comps
    )
    assert all(c.diagnostics.get("source") == "calibrate_rim" for c in comps)
    assert not any(c.method_id == METHOD_PB_COMMON for c in comps)
    assert ledger and ledger[0]["status"] == "SKIP"
    assert ledger[0]["in_weights"] is False
    # Preserve blob skip_reason (INSUFFICIENT_OWN_PB_HISTORY), not forced HIST_PB_BELOW_MIN
    assert ledger[0]["skip_reason"] == "INSUFFICIENT_OWN_PB_HISTORY"

    summary = build_prior_only_fi_bundle(
        tmp_path / "out",
        scenario="live_calibrate_rim_forecast",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=7,
        n_draws=400,
    )
    assert summary["status"] == PRIOR_ONLY_FI_STATUS
    assert summary["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summary["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summary["research_mode"] == EnsembleMode.PRIOR_ONLY.value
    # Only Track A eligible (no pb_common on calibrate-rim blob) → ensemble ≥2
    # gate refuses mixture (same as R8 track_a_only). Still PRIOR_ONLY research path.
    assert summary["research_mixture"] is False
    assert summary["research_weight_method_ids"] == []
    assert summary["research_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert summary["research_calibration_status"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert summary["calibrated_claim"] is False
    assert summary["ENSEMBLE_CALIBRATED"] is False
    assert summary["CALIBRATION_PASS"] is False
    assert summary["investment_value"] == INV
    assert summary["data_label"] == CALIBRATE_RIM_DATA_LABEL
    assert "SYNTHETIC" not in summary["data_label"]
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    assert METHOD_RIM_TRACK_A in [c.method_id for c in comps if c.eligible]
    assert summary["assumption"] == CALIBRATE_RIM_ASSUMPTION
    assert CALIBRATE_RIM_ASSUMPTION in summary["assumptions"]
    body = json.loads((tmp_path / "out" / "ensemble_report.json").read_text())
    assert body["calibrated_claim"] is False
    assert "calibrate-rim forecast" in body["warning"]
    assert body["research_prior"]["ensemble_status"] != "ENSEMBLE_CALIBRATED"


def test_ac2_production_intent_refuses_mixture(tmp_path: Path):
    comps, ledger, meta = adapt_calibrate_rim_forecast(ELIG_TB, seed=3)
    assert meta["track_b_in_weights_eligible"] is False
    summary = build_prior_only_fi_bundle(
        tmp_path / "out2",
        scenario="live_calibrate_rim_forecast",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=3,
        n_draws=200,
    )
    assert summary["production_mixture"] is False
    assert summary["production_mode"] == EnsembleMode.PRODUCTION_REFUSED.value
    body = json.loads((tmp_path / "out2" / "ensemble_report.json").read_text())
    assert body["production_refusal"]["mixture"] is None

    report = build_ensemble(
        comps,
        target=TARGET,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="production",
        n_draws=100,
        seed=3,
        compute_l1o=False,
    )
    assert report.mixture is None


def test_ac3_eligible_hist_median_pb_skips_not_per_share(tmp_path: Path):
    """AC3 / B1: hist_n>=12 + median_pb only → SKIP TRACK_B_CENTER_NOT_PER_SHARE."""
    assert MIN_HIST_PB_POINTS == 12
    comps, ledger, meta = adapt_calibrate_rim_forecast(ELIG_TB, seed=11)
    assert meta["track_b_hist_n"] == 12
    assert meta["track_b_blob_status"] == "ELIGIBLE"
    assert meta["track_b_pb_center_used"] == pytest.approx(2.266002519548162)
    assert meta["track_b_exit_vps_center"] is None
    assert meta["track_b_in_weights_eligible"] is False
    assert ledger[0]["status"] == "SKIP"
    assert ledger[0]["skip_reason"] == SKIP_TRACK_B_CENTER_NOT_PER_SHARE
    assert ledger[0]["in_weights"] is False
    tb = next(c for c in comps if c.method_id == METHOD_TRACK_B_EXIT)
    assert tb.eligible is False
    assert tb.diagnostics["skip_reason"] == SKIP_TRACK_B_CENTER_NOT_PER_SHARE
    assert tb.diagnostics["track_b_pb_center_is_multiple"] is True
    assert tb.diagnostics["track_b_pb_center_used"] == pytest.approx(2.266002519548162)
    assert not tb.samples

    summary = build_prior_only_fi_bundle(
        tmp_path / "out3",
        scenario="live_calibrate_rim_forecast",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=11,
        n_draws=300,
    )
    assert summary["track_b_in_weights"] is False
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    assert summary["calibrated_claim"] is False


def test_ac4_fail_closed_missing_track_a(tmp_path: Path):
    bad = {
        "instrument_id": "X",
        "forecasts": {"intrinsic_value": {"point": None, "status": "INELIGIBLE"}},
        "baselines": {"central_rim": {"vps": None}},
        "track_b": {"status": "SKIP", "hist_n": 3, "min_required": 12},
    }
    with pytest.raises(FiMethodDistributionAdapterError, match="Track A"):
        adapt_calibrate_rim_forecast(bad)


def test_ac4_fail_closed_bad_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not-json", encoding="utf-8")
    with pytest.raises(FiMethodDistributionAdapterError, match="failed to read"):
        adapt_calibrate_rim_forecast(p)


def test_ac4_fail_closed_missing_file(tmp_path: Path):
    with pytest.raises(FiMethodDistributionAdapterError, match="does not exist"):
        adapt_calibrate_rim_forecast(tmp_path / "nope.json")


def test_ac4_resolve_zero_matches(tmp_path: Path):
    root = tmp_path / "cr"
    (root / "forecasts" / "600036.SH").mkdir(parents=True)
    with pytest.raises(FiMethodDistributionAdapterError, match="no calibrate-rim forecast"):
        resolve_calibrate_rim_forecast_path(
            root, instrument_id="600036.SH", origin_as_of="2017-04-20"
        )


def test_ac4_resolve_ambiguous(tmp_path: Path):
    root = tmp_path / "cr"
    d = root / "forecasts" / "600036.SH"
    d.mkdir(parents=True)
    (d / "2017-04-20_h1.json").write_text("{}", encoding="utf-8")
    (d / "2017-04-20_h3.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FiMethodDistributionAdapterError, match="ambiguous"):
        resolve_calibrate_rim_forecast_path(
            root, instrument_id="600036.SH", origin_as_of="2017-04-20"
        )


def test_ac4_resolve_ok(tmp_path: Path):
    root = tmp_path / "cr"
    d = root / "forecasts" / "600036.SH"
    d.mkdir(parents=True)
    target = d / "2017-04-20_h1.json"
    target.write_text(SKIP_TB.read_text(encoding="utf-8"), encoding="utf-8")
    got = resolve_calibrate_rim_forecast_path(
        root, instrument_id="600036.SH", origin_as_of="2017-04-20"
    )
    assert got == target


def test_ac4_not_assessed_not_defaulted_to_hist_below_min():
    payload = json.loads(SKIP_TB.read_text(encoding="utf-8"))
    payload["track_b"] = {
        "status": "NOT_ASSESSED",
        "hist_n": 0,
        "min_required": 12,
        "skip_reason": None,
        "median_pb": None,
    }
    comps, ledger, _meta = adapt_calibrate_rim_forecast(payload, seed=1)
    assert ledger[0]["skip_reason"] == "NOT_ASSESSED"
    assert ledger[0]["skip_reason"] != "HIST_PB_BELOW_MIN"


def test_ac6_schema_package_forbidden_labels(tmp_path: Path):
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    assert __version__ == "0.2.0rc1"
    assert MIN_HIST_PB_POINTS == 12
    assert IMPLEMENTED_PHASE == "PHASE_12"

    from vms.reporting.prior_only_fi_bundle import (
        ALLOWED_CALIBRATION_STATUS,
        ALLOWED_ENSEMBLE_STATUS,
        ALLOWED_INVESTMENT_VALUE,
    )

    comps, ledger, meta = adapt_calibrate_rim_forecast(SKIP_TB, seed=2)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out6",
        scenario="live_calibrate_rim_forecast",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=2,
        n_draws=150,
    )
    assert summary["investment_value"] in ALLOWED_INVESTMENT_VALUE
    assert summary["research_ensemble_status"] in ALLOWED_ENSEMBLE_STATUS
    assert summary["research_calibration_status"] in ALLOWED_CALIBRATION_STATUS
    assert summary["calibrated_claim"] is False
    assert summary["ENSEMBLE_CALIBRATED"] is False
    assert summary["CALIBRATION_PASS"] is False
    body = json.loads((tmp_path / "out6" / "ensemble_report.json").read_text())
    assert body["research_prior"]["ensemble_status"] != "ENSEMBLE_CALIBRATED"
    assert body["research_prior"]["calibration_status"] != "CALIBRATION_PASS"
    assert body["research_prior"]["investment_value"] != "INVESTMENT_VALUE_SUPPORTED"


def test_track_a_fallback_to_central_rim_vps():
    payload = json.loads(SKIP_TB.read_text(encoding="utf-8"))
    payload["forecasts"]["intrinsic_value"] = {
        "point": None,
        "status": "INELIGIBLE",
    }
    # keep baselines.central_rim.vps
    comps, _ledger, meta = adapt_calibrate_rim_forecast(payload, seed=1)
    assert meta["rim_vps_source"] == "baselines.central_rim.vps"
    assert meta["rim_vps"] == pytest.approx(39.016978286598786)
    assert any(c.method_id == METHOD_RIM_TRACK_A and c.eligible for c in comps)


def test_no_track_b_object_no_ledger():
    payload = json.loads(SKIP_TB.read_text(encoding="utf-8"))
    payload.pop("track_b", None)
    comps, ledger, meta = adapt_calibrate_rim_forecast(payload, seed=1)
    assert ledger == []
    assert meta["track_b_hist_n"] == 0
    assert not any(c.method_id == METHOD_TRACK_B_EXIT for c in comps)
