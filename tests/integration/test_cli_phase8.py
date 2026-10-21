"""`vms phase8` CLI (VMS-0.2 Phase 8)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase8_bundle import PHASE8_STATUS


def test_cli_phase8_mature_smoke(tmp_path, capsys):
    out = tmp_path / "phase8_mature"
    rc = main(["phase8", "--out", str(out), "--seed", "42", "--fixture", "mature", "--n-draws", "300"])
    assert rc == 0
    summ = json.loads((out / "phase8_summary.json").read_text())
    assert summ["status"] == PHASE8_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase8"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_8"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["calibrated_claim"] is False
    assert summ["production_mixture"] is False
    assert summ["research_mixture"] is True
    assert summ["research_mode"] == "PRIOR_ONLY"
    assert summ["equal_weight_labeled_prior_only"] is True
    assert summ["production_ensemble_status"] == "ENSEMBLE_UNCALIBRATED"
    assert summ["research_ensemble_status"] == "ENSEMBLE_UNCALIBRATED"
    assert (out / "ensemble_report.json").is_file()
    assert (out / "intrinsic_value_weights.json").is_file()
    assert (out / "market_outcome_weights.json").is_file()
    assert (out / "method_results" / "fcff_dcf.json").is_file()
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["schema_version"] == SCHEMA_VERSION
