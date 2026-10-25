"""R9 live value-rim → MethodDistribution adapter acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
from vms.ensemble import EnsembleMode, build_ensemble
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.fi_method_distribution_adapter import (
    ARTIFACT_METHOD_RESULT,
    ARTIFACT_RIM_DISTRIBUTION,
    ARTIFACT_RIM_PB_ROE,
    ARTIFACT_RIM_TRACK_B,
    FiMethodDistributionAdapterError,
    LIVE_DATA_LABEL,
    adapt_value_rim_dir,
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


def _write(dir_path: Path, name: str, payload: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / name).write_text(json.dumps(payload), encoding="utf-8")


def _fixture_value_rim(
    root: Path,
    *,
    rim_vps: float = 12.0,
    use_method_result: bool = True,
    pb_vps: float | None = 10.5,
    pb_ok: bool = True,
    track_b_hist_n: int | None = 5,
    track_b_center: float | None = 0.85,
) -> Path:
    """Minimal value-rim out-dir fixture covering Track A / pb / Track B pins."""
    if use_method_result:
        _write(
            root,
            ARTIFACT_METHOD_RESULT,
            {
                "method_id": "residual_income",
                "status": "VALID",
                "values": {
                    "value_per_share": {
                        "mean": rim_vps,
                        "p50": rim_vps,
                        "p05": rim_vps * 0.9,
                        "p95": rim_vps * 1.1,
                        "n": 1,
                    }
                },
                "diagnostics": {},
            },
        )
    else:
        _write(
            root,
            ARTIFACT_RIM_DISTRIBUTION,
            {
                "ke_grid": [
                    {"ke": 0.09, "vps_p05": rim_vps * 0.9, "vps_p50": rim_vps, "vps_p95": rim_vps * 1.1}
                ]
            },
        )
    if pb_vps is not None:
        _write(
            root,
            ARTIFACT_RIM_PB_ROE,
            {
                "ok": pb_ok,
                "status": "VALID" if pb_ok else "INELIGIBLE",
                "relative_vps": pb_vps if pb_ok else None,
            },
        )
    if track_b_hist_n is not None:
        _write(
            root,
            ARTIFACT_RIM_TRACK_B,
            {
                "ok": track_b_hist_n >= MIN_HIST_PB_POINTS and track_b_center is not None,
                "status": "VALID" if track_b_hist_n >= MIN_HIST_PB_POINTS else "INELIGIBLE",
                "hist_pb": {"n": track_b_hist_n, "median": track_b_center},
                "pb_center_used": track_b_center,
            },
        )
    _write(root, "value_rim_summary.json", {"instrument_id": "000001.SZ", "status": "ok"})
    return root


def test_ac1_fixture_value_rim_research_prior_only(tmp_path: Path):
    vr = _fixture_value_rim(
        tmp_path / "vr",
        track_b_hist_n=5,
        track_b_center=0.85,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=7)
    assert meta["data_label"] == LIVE_DATA_LABEL
    assert meta["synthetic"] is False
    assert meta["rim_vps"] == 12.0
    assert meta["pb_vps"] == 10.5
    assert all(c.diagnostics.get("synthetic") is False for c in comps)
    assert ARTIFACT_METHOD_RESULT in meta["source_artifacts"]
    assert ARTIFACT_RIM_PB_ROE in meta["source_artifacts"]
    assert ARTIFACT_RIM_TRACK_B in meta["source_artifacts"]
    assert ledger and ledger[0]["status"] == "SKIP"
    assert ledger[0]["in_weights"] is False

    summary = build_prior_only_fi_bundle(
        tmp_path / "out",
        scenario="live_value_rim",
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
    assert summary["research_mixture"] is True
    assert summary["research_ensemble_status"] == ClaimStatus.ENSEMBLE_UNCALIBRATED.value
    assert summary["research_calibration_status"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert summary["calibrated_claim"] is False
    assert summary["ENSEMBLE_CALIBRATED"] is False
    assert summary["CALIBRATION_PASS"] is False
    assert summary["investment_value"] == INV
    assert summary["data_label"] == LIVE_DATA_LABEL
    assert "SYNTHETIC" not in summary["data_label"]
    assert METHOD_RIM_TRACK_A in summary["research_weight_method_ids"]
    assert METHOD_PB_COMMON in summary["research_weight_method_ids"]
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1" in summary["assumptions"]
    body = json.loads((tmp_path / "out" / "ensemble_report.json").read_text())
    assert body["calibrated_claim"] is False
    assert body["research_prior"]["mode"] == EnsembleMode.PRIOR_ONLY.value
    cfg = json.loads((tmp_path / "out" / "config_snapshot.json").read_text())
    assert cfg["data_label"] == LIVE_DATA_LABEL


def test_ac2_production_intent_refuses_mixture(tmp_path: Path):
    vr = _fixture_value_rim(tmp_path / "vr2", track_b_hist_n=12, track_b_center=0.9)
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=3)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out2",
        scenario="live_value_rim",
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

    # Same components via build_ensemble production directly
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


def test_ac3_track_b_hist_below_min_skipped(tmp_path: Path):
    assert MIN_HIST_PB_POINTS == 12
    vr = _fixture_value_rim(
        tmp_path / "vr3",
        track_b_hist_n=5,
        track_b_center=0.85,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=9)
    assert meta["track_b_in_weights_eligible"] is False
    assert ledger[0]["status"] == "SKIP"
    assert ledger[0]["hist_n"] == 5
    summary = build_prior_only_fi_bundle(
        tmp_path / "out3",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=9,
        n_draws=300,
    )
    assert summary["track_b_in_weights"] is False
    assert METHOD_TRACK_B_EXIT not in summary["research_weight_method_ids"]
    tb = json.loads(
        (tmp_path / "out3" / "method_results" / f"{METHOD_TRACK_B_EXIT}.json").read_text()
    )
    assert tb["eligible"] is False
    assert tb["n_samples"] == 0
    assert tb["diagnostics"]["synthetic"] is False


def test_ac3_track_b_eligible_enters_weights(tmp_path: Path):
    vr = _fixture_value_rim(
        tmp_path / "vr3b",
        track_b_hist_n=12,
        track_b_center=11.0,  # research disagreement center on declared basis
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=11)
    assert meta["track_b_in_weights_eligible"] is True
    assert ledger[0]["status"] == "ELIGIBLE"
    summary = build_prior_only_fi_bundle(
        tmp_path / "out3b",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=11,
        n_draws=300,
    )
    assert summary["track_b_in_weights"] is True
    assert METHOD_TRACK_B_EXIT in summary["research_weight_method_ids"]
    assert summary["calibrated_claim"] is False


def test_ac4_demo_path_unchanged_without_from_value_rim(tmp_path: Path):
    """R8 synthetic demo behavior unchanged when components is None."""
    summary = build_prior_only_fi_bundle(
        tmp_path / "demo",
        scenario="track_b_skip",
        seed=42,
        n_draws=300,
    )
    assert summary["data_label"].startswith("SYNTHETIC_FI_PRIOR_ONLY")
    assert summary["research_mixture"] is True
    assert summary["track_b_in_weights"] is False
    assert summary["calibrated_claim"] is False
    rim = json.loads(
        (tmp_path / "demo" / "method_results" / f"{METHOD_RIM_TRACK_A}.json").read_text()
    )
    assert rim["diagnostics"]["synthetic"] is True


def test_ac5_schema_package_and_forbidden_labels(tmp_path: Path):
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    assert __version__ == "0.2.0rc1"
    assert MIN_HIST_PB_POINTS == 12
    assert IMPLEMENTED_PHASE == "PHASE_12"

    from vms.reporting.prior_only_fi_bundle import (
        ALLOWED_CALIBRATION_STATUS,
        ALLOWED_ENSEMBLE_STATUS,
        ALLOWED_INVESTMENT_VALUE,
    )

    vr = _fixture_value_rim(tmp_path / "vr5", track_b_hist_n=12, track_b_center=11.0)
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=2)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out5",
        scenario="live_value_rim",
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
    body = json.loads((tmp_path / "out5" / "ensemble_report.json").read_text())
    assert body["research_prior"]["ensemble_status"] != "ENSEMBLE_CALIBRATED"
    assert body["research_prior"]["calibration_status"] != "CALIBRATION_PASS"
    assert body["research_prior"]["investment_value"] != "INVESTMENT_VALUE_SUPPORTED"


def test_track_a_from_rim_distribution_fallback(tmp_path: Path):
    vr = _fixture_value_rim(
        tmp_path / "vr_dist",
        use_method_result=False,
        pb_vps=None,
        track_b_hist_n=None,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=1)
    assert meta["rim_vps_source"] == ARTIFACT_RIM_DISTRIBUTION
    assert meta["rim_vps"] == 12.0
    assert any(c.method_id == METHOD_RIM_TRACK_A and c.eligible for c in comps)
    assert ledger == []


def test_missing_track_a_raises(tmp_path: Path):
    root = tmp_path / "empty_vr"
    root.mkdir()
    _write(root, ARTIFACT_RIM_PB_ROE, {"ok": True, "status": "VALID", "relative_vps": 10.0})
    with pytest.raises(FiMethodDistributionAdapterError, match="Track A"):
        adapt_value_rim_dir(root)


def test_pb_ineligible_not_included(tmp_path: Path):
    vr = _fixture_value_rim(
        tmp_path / "vr_pb_bad",
        pb_vps=10.5,
        pb_ok=False,
        track_b_hist_n=None,
    )
    comps, _, meta = adapt_value_rim_dir(vr, seed=1)
    assert meta["pb_vps"] is None
    assert not any(c.method_id == METHOD_PB_COMMON for c in comps)
