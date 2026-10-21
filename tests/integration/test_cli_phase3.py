"""`vms phase3` synthetic path-bundle CLI (VMS-0.2 Phase 3)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase3_bundle import PHASE3_STATUS


def test_cli_phase3_artifacts(tmp_path, capsys):
    out = tmp_path / "phase3"
    rc = main(["phase3", "--out", str(out), "--seed", "42", "--paths", "30", "--years", "3"])
    assert rc == 0
    summ = json.loads(capsys.readouterr().out)
    assert summ["status"] == PHASE3_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase4"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_4"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["financial_n_valid"] == 30
    assert summ["market_pricing_status"] == "UNAVAILABLE"
    assert (out / "financial_path_bundle.json").is_file()
    assert (out / "simulation_bundle.json").is_file()
    assert (out / "state_posterior.json").is_file()
    assert (out / "simulation_metadata.json").is_file()
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert meta["schema_version"] == SCHEMA_VERSION
    assert "No FCFF/FCFE/DDM" in meta["warning"] or "no ensemble" in meta["warning"].lower()
    sp = json.loads((out / "state_posterior.json").read_text())
    assert sp["market_pricing_schema"]["kind"] == "MARKET_PRICING"
    assert "COMPRESSED" in sp["market_pricing_state_vocabulary"]
    assert sp["fundamental"]["kind"] == "FUNDAMENTAL"
    # Seed reproducibility of summary hashes
    out2 = tmp_path / "phase3b"
    rc2 = main(["phase3", "--out", str(out2), "--seed", "42", "--paths", "30", "--years", "3"])
    assert rc2 == 0
    s2 = json.loads((out2 / "phase3_summary.json").read_text())
    s1 = json.loads((out / "phase3_summary.json").read_text())
    assert s1["run_id"] == s2["run_id"]
    assert s1["data_hash"] == s2["data_hash"]
