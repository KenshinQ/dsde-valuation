"""`vms phase6` RIM/NAV/SOTP CLI (VMS-0.2 Phase 6)."""

from __future__ import annotations

import json

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase6_bundle import PHASE6_STATUS


def test_cli_phase6_financial_smoke(tmp_path, capsys):
    out = tmp_path / "phase6_financial"
    rc = main(["phase6", "--out", str(out), "--seed", "42", "--fixture", "financial"])
    assert rc == 0
    summ = json.loads((out / "phase6_summary.json").read_text())
    assert summ["status"] == PHASE6_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["ensemble"] is None
    assert summ["profile_primary"] == "FINANCIAL_INSTITUTION"
    assert "residual_income" in summ["eligible_run"]
    assert summ["industrial_fcff_disabled"]["fcff_dcf_eligible"] is False
    mr = json.loads((out / "method_results.json").read_text())
    assert mr["ensemble"] is None
    rim = next(r for r in mr["results"] if r["method_id"] == "residual_income")
    assert rim["status"] == "VALID"
    assert rim["values"]["ev_bridge_applied"] is False
    captured = capsys.readouterr()
    assert "PHASE6_RIM_NAV_SOTP" in captured.out or PHASE6_STATUS in captured.out


def test_cli_phase6_holding_and_gap(tmp_path):
    out_ok = tmp_path / "holding"
    rc = main(["phase6", "--out", str(out_ok), "--seed", "7", "--fixture", "holding"])
    assert rc == 0
    summ = json.loads((out_ok / "phase6_summary.json").read_text())
    assert summ["profile_primary"] == "HOLDING_OR_CONGLOMERATE"
    assert "nav" in summ["eligible_run"] and "sotp" in summ["eligible_run"]

    out_gap = tmp_path / "holding_gap"
    rc2 = main(["phase6", "--out", str(out_gap), "--seed", "7", "--fixture", "holding_gap"])
    assert rc2 == 0
    gap = json.loads((out_gap / "phase6_summary.json").read_text())
    assert gap["eligible_run"] == []
    statuses = {m["method_id"]: m for m in gap["method_statuses"]}
    assert statuses["nav"]["unsupported"] is True
    assert statuses["sotp"]["unsupported"] is True
    assert statuses["nav"]["status"] == "INELIGIBLE"
