"""CLI smoke for `vms calibrate-rim` (R6)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.calibrate_rim_bundle import CALIBRATE_RIM_STATUS

REPO = Path(__file__).resolve().parents[2]


def test_cli_calibrate_rim_smoke(tmp_path, capsys):
    out = tmp_path / "calibrate_rim_smoke"
    rc = main([
        "calibrate-rim",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.fi_deposit_lean.yaml"),
        "--start", "2016-01-01",
        "--end", "2022-12-31",
        "--seed", "42",
    ])
    assert rc == 0
    summ = json.loads((out / "calibrate_rim_summary.json").read_text())
    assert summ["status"] == CALIBRATE_RIM_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summ["min_hist_pb_points"] == 12
    assert summ["includes_000001"] is True
    assert summ["n_track_b_skipped"] >= 1
    assert summ["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert (out / "rim_calibration_report.json").is_file()
    assert (out / "frozen_weights.json").is_file()
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == CALIBRATE_RIM_STATUS
    assert captured["split_mode"] == "chronological"
    rep = json.loads((out / "rim_calibration_report.json").read_text())
    assert "EVAL-RIM-BANK-WF-v1" in rep["assumptions"]
    assert rep["n_track_b_skipped"] >= 1
