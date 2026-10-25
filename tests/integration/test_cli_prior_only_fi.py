"""`vms prior-only-fi` CLI (R8)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.prior_only_fi_bundle import PRIOR_ONLY_FI_STATUS


def test_cli_prior_only_fi_track_b_skip_smoke(tmp_path, capsys):
    out = tmp_path / "pofi"
    rc = main([
        "prior-only-fi",
        "--out", str(out),
        "--seed", "42",
        "--scenario", "track_b_skip",
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
    assert summ["research_mixture"] is True
    assert summ["research_mode"] == "PRIOR_ONLY"
    assert summ["track_b_in_weights"] is False
    assert summ["min_hist_pb_points"] == 12
    assert (out / "ensemble_report.json").is_file()
    assert (out / "method_results" / "residual_income.json").is_file()
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["calibrated_claim"] is False
