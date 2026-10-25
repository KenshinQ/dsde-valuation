"""CLI smoke for `vms calibrate-rim` on R7 HiThink/EM lean real universe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms import SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.calibrate_rim_bundle import CALIBRATE_RIM_STATUS

REPO = Path(__file__).resolve().parents[2]
FUND_DB = Path("/workspace/data/hithink_fundamentals.duckdb")
MARKET_DB = Path("/workspace/data/market.duckdb")

pytestmark = pytest.mark.skipif(
    not (FUND_DB.is_file() and MARKET_DB.is_file()),
    reason="local HiThink/market duckdb required",
)


def test_cli_calibrate_rim_real_oos_smoke(tmp_path, capsys):
    out = tmp_path / "calibrate_rim_real"
    rc = main([
        "calibrate-rim",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.fi_deposit_lean_real.yaml"),
        "--start", "2016-01-01",
        "--end", "2022-12-31",
        "--seed", "42",
    ])
    assert rc == 0
    summ = json.loads((out / "calibrate_rim_summary.json").read_text())
    assert summ["status"] == CALIBRATE_RIM_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert "SYNTHETIC" not in summ["data_label"].upper()
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summ["min_hist_pb_points"] == 12
    assert summ["prefer_local"] is True
    assert summ["fi_real_rest_calls"] == 0
    assert summ["assumption"] == "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1"
    assert (out / "fi_real_materialize.json").is_file()
    assert (out / "rim_calibration_report.json").is_file()
    assert (out / "frozen_weights.json").is_file()
    captured = json.loads(capsys.readouterr().out)
    assert captured["fi_real_rest_calls"] == 0
    rep = json.loads((out / "rim_calibration_report.json").read_text())
    assert "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" in rep["assumptions"]
