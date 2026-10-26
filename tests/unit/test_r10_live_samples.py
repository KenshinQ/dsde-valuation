"""R10 live sample paths for PRIOR_ONLY FI adapter acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
from vms.ensemble import EnsembleMode, build_ensemble
from vms.methods.rim.distribution import LIVE_SAMPLE_CAP
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.fi_method_distribution_adapter import (
    ARTIFACT_METHOD_RESULT,
    ARTIFACT_RIM_DISTRIBUTION,
    ARTIFACT_RIM_PB_ROE,
    ARTIFACT_RIM_TRACK_B,
    LIVE_DATA_LABEL,
    SKIP_TRACK_B_CENTER_NOT_PER_SHARE,
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


def _fixture_with_live(
    root: Path,
    *,
    rim_vps: float = 12.0,
    rim_live: list[float] | None = None,
    pb_vps: float | None = 10.5,
    track_b_hist_n: int = 12,
    track_b_pb_multiple: float = 0.9,
    track_b_exit_vps: float | None = 11.0,
    track_b_live: list[float] | None = None,
    track_b_exit_horizon: str = "1",
) -> Path:
    """value-rim fixture; pass rim_live/track_b_live to stamp path samples."""
    dist_cell: dict = {
        "cost_of_equity": 0.09,
        "vps_p05": rim_vps * 0.9,
        "vps_p50": rim_vps,
        "vps_p95": rim_vps * 1.1,
    }
    if rim_live is not None:
        dist_cell["vps_samples"] = list(rim_live)
        dist_cell["n_vps_samples"] = len(rim_live)
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
    _write(root, ARTIFACT_RIM_DISTRIBUTION, {"ke_grid": [dist_cell], "ok": True})
    if pb_vps is not None:
        _write(
            root,
            ARTIFACT_RIM_PB_ROE,
            {"ok": True, "status": "VALID", "relative_vps": pb_vps},
        )
    tb: dict = {
        "ok": track_b_hist_n >= MIN_HIST_PB_POINTS and track_b_exit_vps is not None,
        "status": (
            "VALID"
            if track_b_hist_n >= MIN_HIST_PB_POINTS and track_b_exit_vps is not None
            else "INELIGIBLE"
        ),
        "hist_pb": {"n": track_b_hist_n, "median": track_b_pb_multiple},
        "pb_center_used": track_b_pb_multiple,
    }
    if track_b_exit_vps is not None:
        cell: dict = {
            "n_valid": 32,
            "mean": float(track_b_exit_vps),
            "p50": float(track_b_exit_vps),
            "p05": float(track_b_exit_vps) * 0.9,
            "p95": float(track_b_exit_vps) * 1.1,
        }
        if track_b_live is not None:
            cell["exit_vps_samples"] = list(track_b_live)
            cell["n_exit_vps_samples"] = len(track_b_live)
        tb["exit_prices"] = {
            "metric_id": "pb",
            "summaries": {track_b_exit_horizon: cell},
        }
    _write(root, ARTIFACT_RIM_TRACK_B, tb)
    _write(root, "value_rim_summary.json", {"instrument_id": "000001.SZ", "status": "ok"})
    return root


def test_ac1_live_samples_stamp_live_paths(tmp_path: Path):
    rim_live = [11.0, 11.5, 12.0, 12.5, 13.0]
    tb_live = [10.0, 10.5, 11.0, 11.5, 12.0]
    vr = _fixture_with_live(
        tmp_path / "vr_live",
        rim_live=rim_live,
        track_b_live=tb_live,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=7)
    assert meta["data_label"] == LIVE_DATA_LABEL
    assert meta["synthetic"] is False
    assert meta["sample_generation"] == "live_paths"
    assert meta["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"
    assert meta["rim_live_samples"] is True
    assert meta["track_b_live_samples"] is True
    assert meta["n_rim_live_samples"] == len(rim_live)
    assert meta["n_track_b_live_samples"] == len(tb_live)

    rim = next(c for c in comps if c.method_id == METHOD_RIM_TRACK_A)
    assert rim.diagnostics["sample_generation"] == "live_paths"
    assert rim.diagnostics["synthetic"] is False
    assert rim.diagnostics["n_live_samples"] == len(rim_live)
    assert list(rim.samples) == rim_live

    tb = next(c for c in comps if c.method_id == METHOD_TRACK_B_EXIT)
    assert tb.eligible is True
    assert tb.diagnostics["sample_generation"] == "live_paths"
    assert list(tb.samples) == tb_live

    # pb_common: point-only → samples_from_point (honest)
    pb = next(c for c in comps if c.method_id == METHOD_PB_COMMON)
    assert pb.diagnostics["sample_generation"] == "samples_from_point"
    assert pb.diagnostics["synthetic"] is False

    summary = build_prior_only_fi_bundle(
        tmp_path / "out_live",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=7,
        n_draws=400,
    )
    assert summary["status"] == PRIOR_ONLY_FI_STATUS
    assert summary["research_mode"] == EnsembleMode.PRIOR_ONLY.value
    assert summary["research_mixture"] is True
    assert summary["calibrated_claim"] is False
    assert summary["ENSEMBLE_CALIBRATED"] is False
    assert summary["CALIBRATION_PASS"] is False
    assert summary["investment_value"] == INV
    assert summary["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1"
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" in summary["assumptions"]
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1" in summary["assumptions"]
    assert METHOD_TRACK_B_EXIT in summary["research_weight_method_ids"]


def test_ac2_compat_without_live_arrays(tmp_path: Path):
    """Legacy R9 fixture (no vps_samples / exit_vps_samples) → samples_from_point."""
    vr = _fixture_with_live(
        tmp_path / "vr_compat",
        rim_live=None,
        track_b_live=None,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=3)
    assert meta["sample_generation"] == "samples_from_point"
    assert meta["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
    assert meta["rim_live_samples"] is False
    assert meta["track_b_live_samples"] is False
    assert all(
        c.diagnostics.get("sample_generation") == "samples_from_point" for c in comps
    )
    assert all(c.diagnostics.get("synthetic") is False for c in comps)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out_compat",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=3,
        n_draws=200,
    )
    assert summary["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-LIVE-MD-v1"
    assert summary["calibrated_claim"] is False
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" not in summary["assumptions"]


def test_ac3_production_intent_refuses_mixture(tmp_path: Path):
    rim_live = [11.0, 12.0, 13.0]
    tb_live = [10.0, 11.0, 12.0]
    vr = _fixture_with_live(
        tmp_path / "vr_prod",
        rim_live=rim_live,
        track_b_live=tb_live,
    )
    comps, ledger, meta = adapt_value_rim_dir(vr, seed=5)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out_prod",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=5,
        n_draws=200,
    )
    assert summary["production_mixture"] is False
    assert summary["production_mode"] == EnsembleMode.PRODUCTION_REFUSED.value
    report = build_ensemble(
        comps,
        target=TARGET,
        requested_output_basis=OutputBasis.PER_SHARE,
        intent="production",
        n_draws=100,
        seed=5,
        compute_l1o=False,
    )
    assert report.mixture is None


def test_ac4_track_b_gates_unchanged(tmp_path: Path):
    assert MIN_HIST_PB_POINTS == 12
    # hist below min even with live exit samples → SKIP
    vr_low = _fixture_with_live(
        tmp_path / "vr_low",
        track_b_hist_n=5,
        track_b_exit_vps=11.0,
        track_b_live=[10.0, 11.0, 12.0],
        rim_live=[11.0, 12.0, 13.0],
    )
    comps, ledger, meta = adapt_value_rim_dir(vr_low, seed=9)
    assert meta["track_b_in_weights_eligible"] is False
    assert ledger[0]["skip_reason"] == "HIST_PB_BELOW_MIN"
    tb = next(c for c in comps if c.method_id == METHOD_TRACK_B_EXIT)
    assert tb.eligible is False
    assert not tb.samples

    # hist ok but no PER_SHARE center → SKIP NOT_PER_SHARE
    vr_np = _fixture_with_live(
        tmp_path / "vr_np",
        track_b_hist_n=12,
        track_b_exit_vps=None,
        track_b_live=None,
        rim_live=[11.0, 12.0],
    )
    comps2, ledger2, meta2 = adapt_value_rim_dir(vr_np, seed=10)
    assert meta2["track_b_in_weights_eligible"] is False
    assert ledger2[0]["skip_reason"] == SKIP_TRACK_B_CENTER_NOT_PER_SHARE


def test_ac5_forbidden_labels_schema_package(tmp_path: Path):
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    assert __version__ == "0.2.0rc1"
    assert IMPLEMENTED_PHASE == "PHASE_12"
    assert LIVE_SAMPLE_CAP == 96
    assert MIN_HIST_PB_POINTS == 12

    from vms.reporting.prior_only_fi_bundle import (
        ALLOWED_CALIBRATION_STATUS,
        ALLOWED_ENSEMBLE_STATUS,
        ALLOWED_INVESTMENT_VALUE,
    )

    vr = _fixture_with_live(
        tmp_path / "vr5",
        rim_live=[11.0, 12.0, 13.0],
        track_b_live=[10.0, 11.0, 12.0],
    )
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


def test_ac6_persist_distribution_primary_ke_samples(repo: Path):
    """run_rim_distribution retains capped vps_samples on primary ke cell."""
    from tests.unit.methods.test_rim_r2_distribution import _multi_year_snap

    from vms.methods.rim.distribution import run_rim_distribution
    from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
    from vms.schemas.config import load_config

    loaded = load_config(repo / "config/default.yaml")
    snap = _multi_year_snap()
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    dist = run_rim_distribution(
        snap,
        loaded=loaded,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(bridge.book_equity_year),
        dps=float(bridge.last_fy_dps),
        diluted_shares=float(bridge.rim_inputs["diluted_shares"]),
        years=5,
        n_paths=100,
        seed=7,
        ke_grid=(0.09, 0.10),
        p1_common_ni=float(bridge.last_fy_ni),
        goodwill=bridge.goodwill_0,
        oci_constant=-0.2e9,
    )
    assert dist.ok and dist.ke_grid
    primary = dist.ke_grid[0]
    assert primary.vps_samples is not None
    assert primary.n_vps_samples == len(primary.vps_samples)
    assert 2 <= primary.n_vps_samples <= min(LIVE_SAMPLE_CAP, 100)
    assert all(v > 0 for v in primary.vps_samples)
    assert dist.ke_grid[1].vps_samples is None
    assert dist.ke_grid[1].n_vps_samples == 0
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" in dist.assumption_ids


def test_ac6_persist_track_b_exit_samples(tmp_path: Path, repo: Path):
    """Track B exit_prices.summaries carry capped exit_vps_samples when paths run."""
    from tests.unit.methods.test_rim_r2cd_track_b import _build_years

    from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
    from vms.methods.rim.track_b_exit import run_rim_track_b
    from vms.schemas.config import load_config

    loaded = load_config(repo / "config/default.yaml")
    snap = _build_years(14)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    tb = run_rim_track_b(
        snap,
        bridge=bridge,
        loaded=loaded,
        years=3,
        n_paths=40,
        seed=7,
        horizons_years=(1, 3),
    )
    assert tb.ok and tb.exit_prices is not None
    summaries = tb.exit_prices["summaries"]
    assert "1" in summaries
    cell = summaries["1"]
    assert "exit_vps_samples" in cell
    assert cell["n_exit_vps_samples"] == len(cell["exit_vps_samples"])
    assert 2 <= cell["n_exit_vps_samples"] <= LIVE_SAMPLE_CAP
    assert all(float(v) > 0 for v in cell["exit_vps_samples"])
    # p50 still present
    assert "p50" in cell
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" in tb.assumption_ids


def test_single_live_sample_still_used(tmp_path: Path):
    """Prefer ≥2; single sample still used with n_live_samples stamp."""
    vr = _fixture_with_live(
        tmp_path / "vr_one",
        rim_live=[12.0],
        track_b_live=[11.0],
    )
    comps, _, meta = adapt_value_rim_dir(vr, seed=1)
    assert meta["sample_generation"] == "live_paths"
    rim = next(c for c in comps if c.method_id == METHOD_RIM_TRACK_A)
    assert list(rim.samples) == [12.0]
    assert rim.diagnostics["n_live_samples"] == 1


def test_sf1_center_horizon_missing_samples_no_steal(tmp_path: Path):
    """SF1: center horizon lacks samples → samples_from_point; never steal other h."""
    root = tmp_path / "vr_sf1"
    # Center will be horizon "1" (first finite p50); only horizon "3" has live samples.
    _write(
        root,
        ARTIFACT_METHOD_RESULT,
        {
            "method_id": "residual_income",
            "status": "VALID",
            "values": {"value_per_share": {"p50": 12.0, "mean": 12.0}},
            "diagnostics": {},
        },
    )
    _write(
        root,
        ARTIFACT_RIM_DISTRIBUTION,
        {
            "ke_grid": [
                {
                    "cost_of_equity": 0.09,
                    "vps_p50": 12.0,
                    "vps_samples": [11.0, 12.0, 13.0],
                    "n_vps_samples": 3,
                }
            ]
        },
    )
    _write(
        root,
        ARTIFACT_RIM_TRACK_B,
        {
            "ok": True,
            "status": "VALID",
            "hist_pb": {"n": 12, "median": 0.9},
            "pb_center_used": 0.9,
            "exit_prices": {
                "metric_id": "pb",
                "summaries": {
                    "1": {
                        "n_valid": 10,
                        "p50": 11.0,
                        "p05": 10.0,
                        "p95": 12.0,
                        # deliberately NO exit_vps_samples on center horizon
                    },
                    "3": {
                        "n_valid": 10,
                        "p50": 15.0,
                        "p05": 14.0,
                        "p95": 16.0,
                        "exit_vps_samples": [14.0, 15.0, 16.0],
                        "n_exit_vps_samples": 3,
                    },
                },
            },
        },
    )
    _write(root, "value_rim_summary.json", {"instrument_id": "000001.SZ"})
    comps, _, meta = adapt_value_rim_dir(root, seed=21)
    assert meta["track_b_exit_vps_source"] == "exit_prices.summaries[1].p50"
    assert meta["track_b_exit_vps_center"] == pytest.approx(11.0)
    assert meta["track_b_in_weights_eligible"] is True
    tb = next(c for c in comps if c.method_id == METHOD_TRACK_B_EXIT)
    assert tb.eligible is True
    assert tb.diagnostics["sample_generation"] == "samples_from_point"
    # Must NOT have stolen [14,15,16] from horizon 3
    assert list(tb.samples) != [14.0, 15.0, 16.0]
    assert "n_live_samples" not in tb.diagnostics or tb.diagnostics.get("n_live_samples") is None
    # Track A still live
    rim = next(c for c in comps if c.method_id == METHOD_RIM_TRACK_A)
    assert rim.diagnostics["sample_generation"] == "live_paths"
    # Meta is live_paths because Track A (or any) has live — Track B is point
    assert meta["sample_generation"] == "live_paths"
    assert meta["track_b_live_samples"] is False


def test_sf2_warning_says_r10_when_live_samples(tmp_path: Path):
    """SF2: live-path ingest warning cites R10 (compat without samples stays R9)."""
    vr_live = _fixture_with_live(
        tmp_path / "vr_sf2_live",
        rim_live=[11.0, 12.0, 13.0],
        track_b_live=[10.0, 11.0, 12.0],
    )
    comps, ledger, meta = adapt_value_rim_dir(vr_live, seed=1)
    summary = build_prior_only_fi_bundle(
        tmp_path / "out_sf2_live",
        scenario="live_value_rim",
        components=comps,
        track_b_ledger=ledger,
        data_label=meta["data_label"],
        source_meta=meta,
        seed=1,
        n_draws=100,
    )
    body = json.loads((tmp_path / "out_sf2_live" / "ensemble_report.json").read_text())
    assert "R10 live value-rim" in body["warning"]
    assert "ENSEMBLE-PRIOR-ONLY-FI-LIVE-SAMPLES-v1" in body["warning"]
    sim = json.loads((tmp_path / "out_sf2_live" / "simulation_metadata.json").read_text())
    assert "R10 live value-rim" in sim["warning"]

    vr_compat = _fixture_with_live(
        tmp_path / "vr_sf2_compat",
        rim_live=None,
        track_b_live=None,
    )
    comps2, ledger2, meta2 = adapt_value_rim_dir(vr_compat, seed=2)
    build_prior_only_fi_bundle(
        tmp_path / "out_sf2_compat",
        scenario="live_value_rim",
        components=comps2,
        track_b_ledger=ledger2,
        data_label=meta2["data_label"],
        source_meta=meta2,
        seed=2,
        n_draws=100,
    )
    body2 = json.loads((tmp_path / "out_sf2_compat" / "ensemble_report.json").read_text())
    assert "R9 live value-rim" in body2["warning"]
    assert "R10 live value-rim" not in body2["warning"]


def test_sf3_samples_or_point_refilters_non_positive(tmp_path: Path):
    """SF3: non-finite / non-positive live values are dropped before use."""
    from vms.reporting.prior_only_fi_bundle import _samples_or_point

    xs, gen, n = _samples_or_point(
        12.0,
        live=[11.0, float("nan"), -1.0, 0.0, float("inf"), 13.0, "bad", None],
        n=32,
        seed=0,
    )
    assert gen == "live_paths"
    assert list(xs) == [11.0, 13.0]
    assert n == 2

    # All junk → fall back to samples_from_point
    xs2, gen2, n2 = _samples_or_point(
        12.0,
        live=[float("nan"), -5.0, 0.0, float("inf")],
        n=16,
        seed=3,
    )
    assert gen2 == "samples_from_point"
    assert n2 is None
    assert len(xs2) == 16
    assert all(x == x and abs(x) != float("inf") for x in xs2)


def test_sf4_prefix_cap_is_first_n_in_path_order(repo: Path):
    """SF4: documented known gap — cap keeps path-order prefix, not a random subsample."""
    from tests.unit.methods.test_rim_r2_distribution import _multi_year_snap

    from vms.methods.rim.distribution import LIVE_SAMPLE_CAP, run_rim_distribution
    from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
    from vms.schemas.config import load_config

    loaded = load_config(repo / "config/default.yaml")
    snap = _multi_year_snap()
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    n_paths = LIVE_SAMPLE_CAP + 20
    dist = run_rim_distribution(
        snap,
        loaded=loaded,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(bridge.book_equity_year),
        dps=float(bridge.last_fy_dps),
        diluted_shares=float(bridge.rim_inputs["diluted_shares"]),
        years=5,
        n_paths=n_paths,
        seed=7,
        ke_grid=(0.09,),
        p1_common_ni=float(bridge.last_fy_ni),
        goodwill=bridge.goodwill_0,
        oci_constant=-0.2e9,
    )
    assert dist.ok
    primary = dist.ke_grid[0]
    assert primary.n_valid > LIVE_SAMPLE_CAP
    assert primary.n_vps_samples == LIVE_SAMPLE_CAP
    # Prefix property: capped list equals first LIVE_SAMPLE_CAP of the retained bank
    # (we only persist the prefix; n_valid counts the full set used for percentiles).
    assert primary.vps_samples is not None
    assert len(primary.vps_samples) == LIVE_SAMPLE_CAP
    assert primary.vps_p50 is not None  # full-set percentile still present
