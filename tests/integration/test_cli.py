"""CLI exit codes, manifests and reproducibility (Phase 0 acceptance)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from vms.cli.main import DETERMINISTIC_ARTIFACTS, SMOKE_STATUS, main
from vms.data import synthetic
from vms.data.io import FINANCIAL_FILE, MARKET_FILE, write_directory

REPO = Path(__file__).resolve().parents[2]


def _hashes(d: Path) -> dict[str, str]:
    names = list(DETERMINISTIC_ARTIFACTS) + [f"data/{FINANCIAL_FILE}", f"data/{MARKET_FILE}"]
    return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in names}


def _vms(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("vms") or str(Path(sys.executable).parent / "vms")
    return subprocess.run([exe, *args], capture_output=True, text=True, cwd=REPO, timeout=120)


def test_demo_via_console_script(tmp_path):
    out = tmp_path / "run"
    p = _vms("demo", "--out", str(out), "--seed", "42", "--paths", "500")
    assert p.returncode == 0, p.stderr
    summary = json.loads(p.stdout)
    assert summary["status"] == SMOKE_STATUS
    for name in [*DETERMINISTIC_ARTIFACTS, "run_context.json"]:
        art = json.loads((out / name).read_text())
        assert art["run_id"] == summary["run_id"] and art["schema_version"] == summary["schema_version"]
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert meta["status"] == SMOKE_STATUS and "No valuation" in meta["warning"]
    md = meta["metadata"]
    assert md["seed"] == 42 and md["monte_carlo_paths"] == 500
    assert len(md["data_hash"]) == 64 and len(md["config_hash"]) == 64
    assert md["code_version"]["git_sha"]
    req = json.loads((out / "request.json").read_text())["request"]
    assert req["as_of"].endswith("+08:00") and req["random_seed"] == 42
    assert json.loads((out / "data_manifest.json").read_text())["source_id"] == "SYNTHETIC"


def test_same_inputs_reproduce_identical_artifacts(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    assert main(["demo", "--out", str(a), "--seed", "7", "--paths", "100"]) == 0
    assert main(["demo", "--out", str(b), "--seed", "7", "--paths", "100"]) == 0
    assert _hashes(a) == _hashes(b)  # byte-identical: tolerance is exact for Phase 0 artifacts
    assert main(["demo", "--out", str(c), "--seed", "8", "--paths", "100"]) == 0
    hc = _hashes(c)
    assert hc["data/" + FINANCIAL_FILE] != _hashes(a)["data/" + FINANCIAL_FILE]
    assert json.loads((c / "request.json").read_text())["run_id"] != json.loads((a / "request.json").read_text())["run_id"]


def test_config_change_changes_config_hash(tmp_path, repo):
    import yaml
    cfg_dir = tmp_path / "cfg"
    shutil.copytree(repo / "config", cfg_dir)
    y = yaml.safe_load((cfg_dir / "default.yaml").read_text())
    y["terminal_value"]["tv_fraction_warning"] = 0.7
    (cfg_dir / "default.yaml").write_text(yaml.safe_dump(y))
    assert main(["demo", "--out", str(tmp_path / "x"), "--seed", "7"]) == 0
    assert main(["demo", "--out", str(tmp_path / "y"), "--seed", "7", "--config", str(cfg_dir / "default.yaml")]) == 0
    mx = json.loads((tmp_path / "x/simulation_metadata.json").read_text())["metadata"]
    my = json.loads((tmp_path / "y/simulation_metadata.json").read_text())["metadata"]
    assert mx["data_hash"] == my["data_hash"] and mx["config_hash"] != my["config_hash"]


def test_validate_data_ok(tmp_path, capsys):
    fin, mkt = synthetic.generate(1)
    write_directory(tmp_path, fin, mkt)
    assert main(["validate-data", "--input", str(tmp_path), "--as-of", "2023-06-30"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["status"] == "SCHEMA_VALID" and rep["financial_records"] == len(fin)


def test_validate_data_invalid_rows_exit_2_with_line_numbers(tmp_path, capsys):
    fin, mkt = synthetic.generate(1)
    write_directory(tmp_path, fin, mkt)
    df = pd.read_csv(tmp_path / FINANCIAL_FILE, dtype=str, keep_default_na=False)
    df.loc[0, "currency"] = "RMB"
    df.loc[1, "published_at"] = "2021-04-28T18:00:00"   # naive
    df.loc[2, "unit_scale"] = "millions"
    df.to_csv(tmp_path / FINANCIAL_FILE, index=False)
    assert main(["validate-data", "--input", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "line 2: currency" in err and "line 3: published_at" in err and "timezone-naive" in err
    assert "line 4: unit_scale" in err


def test_validate_data_missing_files_and_columns(tmp_path, capsys):
    assert main(["validate-data", "--input", str(tmp_path / "nope")]) == 2
    tmp_path.joinpath(FINANCIAL_FILE).write_text("instrument_id,value\nX,1\n")
    assert main(["validate-data", "--input", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "missing required columns" in err and MARKET_FILE in err


@pytest.mark.parametrize("args,needle", [
    (["--as-of", "2025-06-30T15:00:00"], "timezone-naive"),
    (["--as-of", "yesterday"], "not ISO-8601"),
    (["--paths", "0"], "monte_carlo_paths"),
    (["--horizons", "1,x"], "comma-separated integers"),
    (["--horizons", "0,3"], "positive"),
    (["--config", "/nonexistent.yaml"], "not found"),
])
def test_demo_invalid_inputs_exit_2(tmp_path, capsys, args, needle):
    assert main(["demo", "--out", str(tmp_path / "o"), *args]) == 2
    assert needle in capsys.readouterr().err
