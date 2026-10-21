"""`vms phase12` / `vms validate-bundle` CLI (VMS-0.2 Phase 12)."""

from __future__ import annotations

import json
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase12_bundle import PHASE12_STATUS

REPO = Path(__file__).resolve().parents[2]


def test_cli_phase12_cyclical(tmp_path, capsys):
    out = tmp_path / "cyc"
    rc = main([
        "phase12", "--out", str(out), "--pattern", "cyclical",
        "--seed", "42", "--paths", "8", "--years", "2",
    ])
    assert rc == 0
    summ = json.loads((out / "phase12_summary.json").read_text())
    assert summ["status"] == PHASE12_STATUS
    assert summ["schema_version"] == SCHEMA_VERSION
    assert summ["implemented_phase"] == IMPLEMENTED_PHASE
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["labels"]["INVESTMENT_VALUE_SUPPORTED"] is False
    captured = json.loads(capsys.readouterr().out)
    assert captured["pattern"] == "cyclical"


def test_cli_validate_bundle(tmp_path, capsys):
    out = tmp_path / "cyc"
    assert main([
        "phase12", "--out", str(out), "--pattern", "cyclical",
        "--paths", "8", "--years", "2",
    ]) == 0
    capsys.readouterr()
    rc = main(["validate-bundle", "--path", str(out), "--subset", "phase12"])
    assert rc == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True


def test_cli_phase12_release_subset(tmp_path, capsys):
    out = tmp_path / "rel"
    rc = main([
        "phase12", "--out", str(out),
        "--patterns", "financial_institution,cyclical",
        "--paths", "8", "--years", "2",
    ])
    assert rc == 0
    assert (out / "financial_institution" / "phase12_summary.json").is_file()
    assert (out / "cyclical" / "phase12_summary.json").is_file()
    release = json.loads((out / "phase12_release_summary.json").read_text())
    assert release["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
