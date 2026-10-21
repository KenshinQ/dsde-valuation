"""`vms phase4` cash-flow methods CLI (VMS-0.2 Phase 4)."""

from __future__ import annotations

import json

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase4_bundle import PHASE4_STATUS


def test_cli_phase4_smoke(tmp_path, capsys):
    out = tmp_path / "phase4"
    rc = main(["phase4", "--out", str(out), "--seed", "42", "--paths", "20", "--years", "3"])
    assert rc == 0
    summ = json.loads((out / "phase4_summary.json").read_text())
    assert summ["status"] == PHASE4_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase10"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_10"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["ensemble"] is None
    assert "fcff_dcf" in summ["eligible_run"] or any(
        m["method_id"] == "fcff_dcf" for m in summ["method_statuses"]
    )
    methods = {m["method_id"]: m for m in summ["method_statuses"]}
    assert "fcff_dcf" in methods
    # Artifacts
    assert (out / "method_results.json").is_file()
    assert (out / "route_report.json").is_file()
    mr = json.loads((out / "method_results.json").read_text())
    assert mr["ensemble"] is None
    assert mr["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    # No averaging of method medians into a single blended fair value
    assert "blended_fair_value" not in mr
    captured = capsys.readouterr()
    assert "PHASE4_CASHFLOW_METHODS" in captured.out or PHASE4_STATUS in captured.out
