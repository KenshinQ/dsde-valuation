"""VMS-0.2 Phase 0 offline demo + reproducibility (SPEC §20 Phase 0)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.cli.main import main
from vms.reporting.phase0_bundle import PHASE0_DETERMINISTIC, PHASE0_STATUS


REPO = Path(__file__).resolve().parents[2]


def _hashes(root: Path) -> dict[str, str]:
    out = {}
    for name in PHASE0_DETERMINISTIC:
        p = root / name
        out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted((root / "data").rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_phase0_via_console_script(tmp_path):
    out = tmp_path / "run"
    p = subprocess.run(
        [sys.executable, "-m", "vms.cli.main", "phase0", "--out", str(out), "--seed", "42", "--paths", "50"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert p.returncode == 0, p.stderr
    summary = json.loads(p.stdout)
    assert summary["status"] == PHASE0_STATUS
    assert summary["schema_version"] == SCHEMA_VERSION == "vms-0.2.phase12"
    assert summary["implemented_phase"] == IMPLEMENTED_PHASE == "PHASE_12"
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summary["enabled_methods"] == 11
    for name in [*PHASE0_DETERMINISTIC, "run_context.json"]:
        art = json.loads((out / name).read_text())
        assert art["run_id"] == summary["run_id"]
        assert art["schema_version"] == SCHEMA_VERSION
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert meta["status"] == PHASE0_STATUS
    assert meta["labels"]["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert meta["metadata"]["seed"] == 42
    elig = json.loads((out / "method_eligibility.json").read_text())
    assert elig["enabled_method_count"] == 11
    assert elig["methods"] and all(m["status"] == "NOT_RUN" for m in elig["methods"])
    val = json.loads((out / "validation_report.json").read_text())
    assert val["status"] == "PASS"
    assert (out / "data" / "financial_observations.csv").exists() or (out / "data" / "financial_observations.parquet").exists()


def test_phase0_same_seed_reproduces(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    assert main(["phase0", "--out", str(a), "--seed", "7", "--paths", "40"]) == 0
    assert main(["phase0", "--out", str(b), "--seed", "7", "--paths", "40"]) == 0
    assert _hashes(a) == _hashes(b)
    assert main(["phase0", "--out", str(c), "--seed", "8", "--paths", "40"]) == 0
    assert _hashes(c)["data/financial_observations.csv"] != _hashes(a)["data/financial_observations.csv"]
    assert json.loads((a / "simulation_metadata.json").read_text())["metadata"]["run_id"] != \
        json.loads((c / "simulation_metadata.json").read_text())["metadata"]["run_id"]


def test_phase0_invalid_target_exit_2(tmp_path, capsys):
    assert main(["phase0", "--out", str(tmp_path / "o"), "--target", "FAIR_GUESS"]) == 2
    assert "ValuationTarget" in capsys.readouterr().err


def test_phase0_naive_as_of_exit_2(tmp_path, capsys):
    assert main(["phase0", "--out", str(tmp_path / "o"), "--as-of", "2025-06-30T15:00:00"]) == 2
    assert "timezone-naive" in capsys.readouterr().err


def test_example_script_runs(tmp_path):
    script = REPO / "examples/synthetic_mature_operating/run_phase0.py"
    p = subprocess.run(
        [sys.executable, str(script), "--out", str(tmp_path / "ex"), "--seed", "3"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["schema_version"] == SCHEMA_VERSION
