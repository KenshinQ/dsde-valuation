"""`vms phase9` CLI (VMS-0.2 Phase 9)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase9_bundle import PHASE9_STATUS


def test_cli_phase9_smoke(tmp_path, capsys):
    out = tmp_path / "phase9_smoke"
    rc = main([
        "phase9", "--out", str(out), "--seed", "42", "--paths", "20", "--years", "3",
        "--horizons", "1,3", "--metric", "ev_ebitda",
    ])
    assert rc == 0
    summ = json.loads((out / "phase9_summary.json").read_text())
    assert summ["status"] == PHASE9_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase9"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_9"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["default_forbids_intrinsic_copy"] is True
    assert summ["default_silent_intrinsic_copy_detected"] is False
    assert summ["fundamental_regimes_used_for_estimation"] is False
    assert summ["persistence_baseline_model"] == "CONSTANT_STATE_PERSISTENCE"
    assert summ["mean_reversion_estimation_status"] == "UNSUPPORTED"
    assert (out / "market_pricing_report.json").is_file()
    assert (out / "exit_price_summary.json").is_file()
    assert (out / "exit_price_path_lineage.json").is_file()
    lineage = json.loads((out / "exit_price_path_lineage.json").read_text())
    assert lineage["n_rows"] >= 1
    row = lineage["rows"][0]
    for key in ("metric_id", "terminal_multiple", "diluted_shares", "lineage"):
        assert key in row
    captured = json.loads(capsys.readouterr().out)
    assert captured["schema_version"] == SCHEMA_VERSION
