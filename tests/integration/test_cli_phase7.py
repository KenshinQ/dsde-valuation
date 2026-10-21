"""`vms phase7` / `vms compare-methods` CLI (VMS-0.2 Phase 7)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase7_bundle import PHASE7_STATUS


def test_cli_phase7_mature_smoke(tmp_path, capsys):
    out = tmp_path / "phase7_mature"
    rc = main(["phase7", "--out", str(out), "--seed", "42", "--fixture", "mature"])
    assert rc == 0
    summ = json.loads((out / "phase7_summary.json").read_text())
    assert summ["status"] == PHASE7_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase7"
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_7"
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["combined_value"] is None
    assert summ["ensemble_status"] == "ENSEMBLE_UNCALIBRATED"
    assert (out / "method_eligibility.json").is_file()
    assert (out / "method_comparison.json").is_file()
    elig = json.loads((out / "method_eligibility.json").read_text())
    assert "payload" in elig or "methods" in elig.get("payload", elig) or "methods" in elig
    # write_artifact wraps — accept either shape
    body = elig.get("payload", elig)
    methods = body.get("methods") or elig.get("methods")
    assert methods and all("hard_gate_passed" in m for m in methods)
    assert summ["incompatible_demo_compatible"] is False


def test_cli_phase7_force_gap(tmp_path):
    out = tmp_path / "phase7_gap"
    rc = main([
        "phase7", "--out", str(out), "--seed", "7", "--fixture", "mature",
        "--force-no-eligible",
    ])
    assert rc == 0
    summ = json.loads((out / "phase7_summary.json").read_text())
    assert summ["coverage_status"] == "INSUFFICIENT_METHOD_COVERAGE"
    assert summ["eligible_count"] == 0


def test_cli_compare_methods(tmp_path, capsys):
    out = tmp_path / "compare"
    rc = main(["compare-methods", "--out", str(out), "--fixture", "mature", "--seed", "42"])
    assert rc == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ensemble_status"] == "ENSEMBLE_UNCALIBRATED"
    assert (out / "method_comparison.json").is_file()


def test_cli_route_writes_method_eligibility(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    fix = repo / "examples" / "profile_fixtures" / "mature_operating.json"
    out = tmp_path / "route_out"
    rc = main([
        "route", "--fixture", str(fix),
        "--target", "FUNDAMENTAL_VALUE_CURRENT",
        "--out", str(out),
    ])
    assert rc == 0
    assert (out / "route_report.json").is_file()
    assert (out / "method_eligibility.json").is_file()
    elig = json.loads((out / "method_eligibility.json").read_text())
    assert elig.get("coverage_status") or elig.get("methods")
