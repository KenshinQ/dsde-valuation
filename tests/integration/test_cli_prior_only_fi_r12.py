"""`vms prior-only-fi --from-calibrate-rim-forecast` CLI (R12)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.fi_method_distribution_adapter import CALIBRATE_RIM_ASSUMPTION, CALIBRATE_RIM_DATA_LABEL
from vms.reporting.prior_only_fi_bundle import PRIOR_ONLY_FI_STATUS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SKIP_TB = FIXTURES / "calibrate_rim_forecast_track_a_skip_tb.json"


def test_cli_from_calibrate_rim_forecast_smoke(tmp_path, capsys):
    out = tmp_path / "pofi_cr"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim-forecast", str(SKIP_TB),
        "--seed", "42",
        "--n-draws", "300",
    ])
    assert rc == 0
    summ = json.loads((out / "prior_only_fi_summary.json").read_text())
    assert summ["status"] == PRIOR_ONLY_FI_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["calibrated_claim"] is False
    assert summ["ENSEMBLE_CALIBRATED"] is False
    assert summ["production_mixture"] is False
    # Single eligible method (Track A only) → mixture refused by ≥2 gate; still PRIOR_ONLY.
    assert summ["research_mixture"] is False
    assert summ["research_mode"] == "PRIOR_ONLY"
    assert summ["track_b_in_weights"] is False
    assert summ["data_label"] == CALIBRATE_RIM_DATA_LABEL
    assert summ["scenario"] == "live_calibrate_rim_forecast"
    assert summ["assumption"] == CALIBRATE_RIM_ASSUMPTION
    assert (out / "ensemble_report.json").is_file()
    rim = json.loads((out / "method_results" / "residual_income.json").read_text())
    assert rim["diagnostics"]["synthetic"] is False
    assert rim["diagnostics"]["sample_generation"] == "samples_from_point"
    assert rim["diagnostics"]["source"] == "calibrate_rim"
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["calibrated_claim"] is False
    assert payload["data_label"] == CALIBRATE_RIM_DATA_LABEL
    # source cite in summary / config
    cfg = json.loads((out / "config_snapshot.json").read_text())
    assert cfg["data_label"] == CALIBRATE_RIM_DATA_LABEL
    sm = json.loads((out / "simulation_metadata.json").read_text())
    assert sm["source_meta"]["source"] == "calibrate_rim"
    assert "calibrate-rim forecast" in sm["warning"]


def test_cli_from_calibrate_rim_convenience(tmp_path, capsys):
    root = tmp_path / "cr_out"
    dest = root / "forecasts" / "600036.SH"
    dest.mkdir(parents=True)
    shutil.copy(SKIP_TB, dest / "2017-04-20_h1.json")
    out = tmp_path / "pofi_conv"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim", str(root),
        "--instrument", "600036.SH",
        "--origin-as-of", "2017-04-20",
        "--seed", "7",
        "--n-draws", "200",
    ])
    assert rc == 0
    summ = json.loads((out / "prior_only_fi_summary.json").read_text())
    assert summ["data_label"] == CALIBRATE_RIM_DATA_LABEL
    assert summ["assumption"] == CALIBRATE_RIM_ASSUMPTION
    assert summ["calibrated_claim"] is False


def test_cli_mutually_exclusive_with_scenario(tmp_path, capsys):
    out = tmp_path / "conflict"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim-forecast", str(SKIP_TB),
        "--scenario", "track_b_skip",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_cli_mutually_exclusive_with_value_rim(tmp_path, capsys):
    out = tmp_path / "conflict2"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim-forecast", str(SKIP_TB),
        "--from-value-rim", str(tmp_path / "vr"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "mutually exclusive" in err


def test_cli_demo_without_calibrate_rim_unchanged(tmp_path, capsys):
    """AC5: R8 demo path unchanged when calibrate-rim flags omitted."""
    out = tmp_path / "demo"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--seed", "42",
        "--scenario", "track_b_skip",
        "--n-draws", "300",
    ])
    assert rc == 0
    summ = json.loads((out / "prior_only_fi_summary.json").read_text())
    assert summ["data_label"].startswith("SYNTHETIC_FI_PRIOR_ONLY")
    assert summ["assumption"] == "ENSEMBLE-PRIOR-ONLY-FI-v1"
    rim = json.loads((out / "method_results" / "residual_income.json").read_text())
    assert rim["diagnostics"]["synthetic"] is True


def test_cli_convenience_requires_instrument_origin(tmp_path, capsys):
    out = tmp_path / "need_args"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim", str(tmp_path / "cr"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--instrument" in err or "origin-as-of" in err


def test_cli_fail_closed_missing_forecast(tmp_path, capsys):
    out = tmp_path / "missing"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--from-calibrate-rim-forecast", str(tmp_path / "nope.json"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "does not exist" in err or "error:" in err
