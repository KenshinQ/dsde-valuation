"""CLI smoke for `vms calibrate-rim` (R6) — engineering golden counts.

Locked on master @ 0459ab7 by re-running the fixed CLI (Asia/Shanghai 2026-10-27):
  vms calibrate-rim --out <tmp> --universe config/universe.fi_deposit_lean.yaml \
    --start 2016-01-01 --end 2022-12-31 --seed 42

These G_* counts are an engineering regression golden for protocol smoke.
They are NOT CALIBRATION_PASS / NOT ENSEMBLE_CALIBRATED / NOT investment advice.
"""

from __future__ import annotations

import json
from pathlib import Path

from vms import SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.calibrate_rim_bundle import CALIBRATE_RIM_STATUS

REPO = Path(__file__).resolve().parents[2]

# Engineering golden — fail closed on drift (do not skip/xfail).
# Re-run 2026-10-27 Asia/Shanghai on 0459ab7 matched prior /tmp candidate 21/15/6
# (ledger-only semantics already on master; no panel delta).
R6_SMOKE_GOLDEN = {
    "G_ORIGINS": 21,
    "G_FORECASTS": 21,
    "G_PIT_EXCLUDED": 21,
    "G_TB_SKIP": 15,
    "G_TB_ELIGIBLE": 6,
}


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
    rep = json.loads((out / "rim_calibration_report.json").read_text())
    g = R6_SMOKE_GOLDEN

    # AC1 — origins / forecasts
    assert rep["n_origins_attempted"] == g["G_ORIGINS"]
    assert summ["n_forecasts_persisted"] == g["G_FORECASTS"]
    assert rep["n_forecasts_persisted"] == g["G_FORECASTS"]
    assert g["G_ORIGINS"] == g["G_FORECASTS"]

    # AC2 — PIT exclusion (synthetic: all persisted excluded)
    assert summ["n_excluded_pit_incomplete"] == g["G_PIT_EXCLUDED"]
    assert rep["n_excluded_pit_incomplete"] == g["G_PIT_EXCLUDED"]
    assert len(rep["excluded_pit_incomplete"]) == g["G_PIT_EXCLUDED"]
    assert g["G_PIT_EXCLUDED"] == g["G_FORECASTS"]

    # AC3 — unbiased empty after full PIT exclusion
    assert rep["scores_unbiased"]["n_records"] == 0

    # AC4 — Track B skip / eligible counts + sum check
    assert summ["n_track_b_skipped"] == g["G_TB_SKIP"]
    assert summ["n_track_b_eligible"] == g["G_TB_ELIGIBLE"]
    assert rep["n_track_b_skipped"] == g["G_TB_SKIP"]
    assert rep["n_track_b_eligible"] == g["G_TB_ELIGIBLE"]
    tb = rep["scores"]["track_b"]
    assert tb["n_skipped"] == g["G_TB_SKIP"]
    assert tb["n_eligible"] == g["G_TB_ELIGIBLE"]
    assert g["G_TB_SKIP"] + g["G_TB_ELIGIBLE"] == g["G_FORECASTS"]

    # AC5 — Track B ledger: SKIP-only rows; 000001 present; anti-disguise
    # (replaces tautology `reason != HIST_PB_BELOW_MIN or instrument_id`)
    assert len(rep["track_b_skips"]) == g["G_TB_SKIP"]
    assert len(tb["skips"]) == g["G_TB_SKIP"]
    assert any(s.get("instrument_id") == "000001.SZ" for s in rep["track_b_skips"])
    for ledger in (rep["track_b_skips"], tb["skips"]):
        for s in ledger:
            reason = s.get("skip_reason")
            assert reason, "skip_reason must be non-empty on track_b_skips"
            assert reason != "NOT_ASSESSED", (
                "NOT_ASSESSED must not appear as skip_reason on the skips ledger"
            )
            # If status ever leaks onto a ledger row, it must be SKIP — never NOT_ASSESSED
            if "status" in s:
                assert s["status"] == "SKIP"
            assert s.get("instrument_id"), "skip ledger row needs instrument_id"
            # Depth fields exist on golden/emission payload — prove short-hist SKIP shape
            assert s.get("hist_n") is not None
            assert s.get("min_required") is not None
            assert s["hist_n"] < s["min_required"]

    # AC6 — hard labels / gates (never PASS / never calibrated ensemble)
    assert summ["status"] == CALIBRATE_RIM_STATUS
    assert summ["status"] == "R6_BANK_RIM_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE"
    assert summ["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert summ["release_gates"]["CALIBRATION_PASS"] is False
    assert summ["release_gates"]["CALIBRATION_INSUFFICIENT"] is True
    assert summ["release_gates"]["ENSEMBLE_CALIBRATED"] is False
    assert summ["release_gates"]["INVESTMENT_VALUE_NOT_ESTABLISHED"] is True

    # AC7 — metadata contract (guards against accidentally running R7 universe)
    assert summ["min_hist_pb_points"] == 12
    assert summ["includes_000001"] is True
    assert summ["split_mode"] == "chronological"
    assert summ["data_label"] == "SYNTHETIC_BANK_FI"
    assert summ["assumption"] == "EVAL-RIM-FI-DEPOSIT-WF-v1"
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["schema_version"] == "vms-0.2.phase12"
    assert summ["universe_id"] == "fi_deposit_lean_r6_v1"
    assert "EVAL-RIM-FI-DEPOSIT-WF-v1" in rep["assumptions"]
    assert rep["data_label"] == "SYNTHETIC_BANK_FI"
    assert rep["schema_version"] == "vms-0.2.phase12"

    assert (out / "rim_calibration_report.json").is_file()
    assert (out / "frozen_weights.json").is_file()
    captured = json.loads(capsys.readouterr().out)
    assert captured["status"] == CALIBRATE_RIM_STATUS
    assert captured["split_mode"] == "chronological"
    assert captured["n_forecasts_persisted"] == g["G_FORECASTS"]
    assert captured["n_track_b_skipped"] == g["G_TB_SKIP"]
