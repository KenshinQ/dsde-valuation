"""CLI smoke for `vms calibrate-mature` — MATURE lean WF (INSUFFICIENT-by-default).

Reuses Phase 11 evaluate (operating/CF/multiples). NOT RIM.
NOT CALIBRATION_PASS / NOT ENSEMBLE_CALIBRATED / NOT investment advice.
"""

from __future__ import annotations

import json
from pathlib import Path

from vms import SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.calibrate_mature_bundle import (
    ASSUMPTION_REAL,
    ASSUMPTION_SYN,
    CALIBRATE_MATURE_STATUS,
)

REPO = Path(__file__).resolve().parents[2]


def test_cli_calibrate_mature_synthetic_smoke(tmp_path, capsys):
    out = tmp_path / "calibrate_mature_smoke"
    rc = main([
        "calibrate-mature",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.mature_lean.yaml"),
        "--start", "2018-01-01",
        "--end", "2022-12-31",
        "--seed", "42",
    ])
    assert rc == 0
    summ = json.loads((out / "calibrate_mature_summary.json").read_text())
    rep = json.loads((out / "evaluation_report.json").read_text())

    assert summ["status"] == CALIBRATE_MATURE_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["assumption"] == ASSUMPTION_SYN
    assert summ["data_label"] == "SYNTHETIC"
    assert summ["universe_id"] == "mature_lean_wf_v1"
    assert summ["n_forecasts_persisted"] > 0
    assert summ["not_rim"] is True
    assert summ["methods"] == "phase11_evaluate_operating_cf_multiples"
    assert summ["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert summ["labels"]["CALIBRATION_PASS"] is not True
    assert summ["release_gates"]["CALIBRATION_INSUFFICIENT"] is True
    assert summ["release_gates"]["CALIBRATION_PASS"] is False
    assert summ["prefer_local"] is True
    assert summ.get("materialize_rest_calls") in (0, None)

    assert ASSUMPTION_SYN in rep["assumptions"]
    assert rep["primary_assumption"] == ASSUMPTION_SYN
    assert rep["split_mode"] == "chronological"
    assert (out / "frozen_weights.json").is_file()
    assert (out / "mature_synthetic_materialize.json").is_file()
    assert (out / "forecasts").is_dir()

    # pit_complete=false rows must not inflate scores_unbiased
    n_excl = int(rep.get("n_excluded_pit_incomplete") or 0)
    n_unbiased = int((rep.get("scores_unbiased") or {}).get("n_records") or 0)
    if n_excl:
        # excluded origins are absent from unbiased count contribution
        assert n_unbiased <= int(rep.get("n_scored") or 0)

    captured = json.loads(capsys.readouterr().out)
    assert captured["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert captured["not_rim"] is True


def test_cli_calibrate_mature_real_scaffold_data_gap(tmp_path, capsys):
    """Real scaffold with no data_dir ⇒ DATA_GAP, still INSUFFICIENT, never PASS."""
    out = tmp_path / "calibrate_mature_real"
    rc = main([
        "calibrate-mature",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.mature_lean_real.yaml"),
        "--start", "2018-01-01",
        "--end", "2022-12-31",
        "--seed", "42",
    ])
    assert rc == 0
    summ = json.loads((out / "calibrate_mature_summary.json").read_text())
    mat = json.loads((out / "mature_real_materialize.json").read_text())
    rep = json.loads((out / "evaluation_report.json").read_text())

    assert summ["assumption"] == ASSUMPTION_REAL
    assert "SYNTHETIC" not in summ["data_label"].upper()
    assert summ["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["labels"]["CALIBRATION_PASS"] is not True
    assert summ["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert summ["n_forecasts_persisted"] == 0
    assert mat["rest_calls"] == 0
    assert mat["prefer_local"] is True
    assert mat["n_loaded"] == 0
    assert any(g.get("reason") == "DATA_GAP_NO_DATA_DIR" for g in mat["gaps"])
    assert ASSUMPTION_REAL in rep["assumptions"]
    assert rep["release_gates"]["CALIBRATION_PASS"] is False


def test_cli_calibrate_mature_refuses_fi_universe(tmp_path):
    out = tmp_path / "bad_fi"
    rc = main([
        "calibrate-mature",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.fi_deposit_lean.yaml"),
    ])
    assert rc == 2
