"""`vms phase10` CLI (VMS-0.2 Phase 10)."""

from __future__ import annotations

import json

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase10_bundle import PHASE10_STATUS


def test_cli_phase10_smoke(tmp_path, capsys):
    out = tmp_path / "phase10_smoke"
    rc = main([
        "phase10", "--out", str(out), "--seed", "42", "--paths", "20", "--years", "3",
        "--horizons", "1,3", "--metric", "ev_ebitda", "--spot", "10.0",
        "--entry-prices", "9.0,11.0",
    ])
    assert rc == 0
    summ = json.loads((out / "phase10_summary.json").read_text())
    assert summ["status"] == PHASE10_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["pathwise_higher_p0_cannot_improve"] is True
    assert summ["dsde_present"] is False
    assert summ["dsde_required_for_core"] is False
    assert (out / "return_distribution_summary.json").is_file()
    assert (out / "exit_price_summary.json").is_file()
    assert (out / "dsde_export.json").is_file()
    ret = json.loads((out / "return_distribution_summary.json").read_text())
    assert ret["compounding_convention"] == "DIVIDEND-NO-REINVEST-v1"
    assert ret["pathwise_higher_p0_cannot_improve"] is True
    assert "TRACK-B-EXIT-RETURN-v1" in ret["assumptions"]
    dsde = json.loads((out / "dsde_export.json").read_text())
    assert dsde["availability"]["required_for_core"] is False
    assert dsde["return_export"]["schema_kind"] == "ReturnDistributionExport"
    captured = json.loads(capsys.readouterr().out)
    assert captured["schema_version"] == SCHEMA_VERSION
