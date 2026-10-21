"""`vms phase11` / `vms evaluate` CLI (VMS-0.2 Phase 11)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase11_bundle import PHASE11_STATUS

REPO = Path(__file__).resolve().parents[2]


def test_cli_phase11_smoke(tmp_path, capsys):
    out = tmp_path / "phase11_smoke"
    rc = main([
        "phase11",
        "--out", str(out),
        "--universe", str(REPO / "config" / "universe.synthetic.yaml"),
        "--start", "2018-01-01",
        "--end", "2022-12-31",
        "--seed", "42",
        "--paths", "15",
        "--years", "3",
    ])
    assert rc == 0
    summ = json.loads((out / "phase11_summary.json").read_text())
    assert summ["status"] == PHASE11_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert (out / "evaluation_report.json").is_file()
    assert (out / "sensitivity_report.json").is_file()
    assert (out / "frozen_weights.json").is_file()
    captured = json.loads(capsys.readouterr().out)
    assert captured["schema_version"] == SCHEMA_VERSION
    assert captured["split_mode"] == "chronological"


def test_cli_evaluate_phase11_labels(tmp_path):
    out = tmp_path / "eval"
    rc = main([
        "evaluate",
        "--universe", str(REPO / "config" / "universe.synthetic.yaml"),
        "--start", "2018-01-01",
        "--end", "2022-12-31",
        "--out", str(out),
    ])
    assert rc == 0
    rep = json.loads((out / "evaluation_report.json").read_text())
    assert rep["labels"]["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert "release_gates" in rep or "CALIBRATION_CLAIM" in rep["labels"]
    assert "current_multiple_persistence" in rep.get("baselines_present", [])
