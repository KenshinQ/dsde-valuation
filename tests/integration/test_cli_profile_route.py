"""CLI: vms profile / vms route (Phase 2)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "examples" / "profile_fixtures"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "vms.cli.main", *args],
        cwd=REPO, capture_output=True, text=True, check=False,
    )


def test_cli_profile_mature():
    p = _run(["profile", "--fixture", str(FIX / "mature_operating.json")])
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["primary_profile"] == "MATURE_OPERATING"
    assert out["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert out["schema_version"].startswith("vms-0.2.phase")
    assert out["rule_hit_ids"]


def test_cli_route_insufficient_coverage(tmp_path):
    p = _run([
        "route", "--fixture", str(FIX / "bank.json"),
        "--target", "FUNDAMENTAL_VALUE_CURRENT",
        "--attempt-stubs", "--out", str(tmp_path / "route_out"),
    ])
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["coverage_status"] == "INSUFFICIENT_METHOD_COVERAGE"
    assert out["eligible_count"] == 0
    assert (tmp_path / "route_out" / "route_report.json").is_file()
    bundle = json.loads((tmp_path / "route_out" / "route_report.json").read_text())
    for run in bundle.get("attempted_runs", []):
        assert run.get("values") in ({}, None) or run["values"] == {}
