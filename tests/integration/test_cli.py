"""CLI exit codes, artifacts, gating and reproducibility (Phase 0 + Phase 1)."""

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
from vms.data.io import write_directory

REPO = Path(__file__).resolve().parents[2]
INST = synthetic.SYNTHETIC_INSTRUMENT
DATA_FILES = ["financial_observations.csv", "market_observations.csv", "corporate_actions.csv", "sources.yaml",
              "instrument_classification.csv"]


def _hashes(d: Path) -> dict[str, str]:
    names = list(DETERMINISTIC_ARTIFACTS) + [f"data/{n}" for n in DATA_FILES]
    return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in names}


def _vms(*args: str) -> subprocess.CompletedProcess:
    exe = shutil.which("vms") or str(Path(sys.executable).parent / "vms")
    return subprocess.run([exe, *args], capture_output=True, text=True, cwd=REPO, timeout=120)


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    write_directory(d, *synthetic.generate(42), synthetic.source_descriptors(),
                    classifications=synthetic.classifications())
    return d


def _corrupt_capex_sign(d: Path) -> None:
    p = d / "financial_observations.csv"
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    idx = df.index[(df.field_name == "capex") & (df.period_end == "2023-06-30")][0]
    df.loc[idx, "value"] = "-" + df.loc[idx, "value"]
    df.to_csv(p, index=False)


# ---------------------------------------------------------------- demo
def test_demo_via_console_script(tmp_path):
    out = tmp_path / "run"
    p = _vms("demo", "--out", str(out), "--seed", "42", "--paths", "500")
    assert p.returncode == 0, p.stderr
    summary = json.loads(p.stdout)
    assert summary["status"] == SMOKE_STATUS and summary["quality_status"] == "PASS"
    for name in [*DETERMINISTIC_ARTIFACTS, "run_context.json"]:
        art = json.loads((out / name).read_text())
        assert art["run_id"] == summary["run_id"] and art["schema_version"] == summary["schema_version"]
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert "no dcf" in meta["warning"].lower() or "no valuation" in meta["warning"].lower() and meta["metadata"]["seed"] == 42
    assert summary["projection_status"] == "VALID" and summary["violations"] == []
    req = json.loads((out / "request.json").read_text())
    assert req["request"]["as_of"] == "2025-06-30T15:00:00+08:00" and req["as_of_rule"]["id"] == "ASOF-DATE-CLOSE"


def test_same_inputs_reproduce_identical_artifacts(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    assert main(["demo", "--out", str(a), "--seed", "7", "--paths", "100"]) == 0
    assert main(["demo", "--out", str(b), "--seed", "7", "--paths", "100"]) == 0
    assert _hashes(a) == _hashes(b)
    assert main(["demo", "--out", str(c), "--seed", "8", "--paths", "100"]) == 0
    assert _hashes(c)["data/financial_observations.csv"] != _hashes(a)["data/financial_observations.csv"]


def test_demo_parquet_same_snapshot_as_csv(tmp_path):
    assert main(["demo", "--out", str(tmp_path / "c"), "--seed", "7"]) == 0
    assert main(["demo", "--out", str(tmp_path / "p"), "--seed", "7", "--format", "parquet"]) == 0
    mc = json.loads((tmp_path / "c/data_manifest.json").read_text())
    mp = json.loads((tmp_path / "p/data_manifest.json").read_text())
    assert mc["data_hash"] == mp["data_hash"]
    assert {v["format"] for v in mp["files"].values()} == {"parquet", "yaml"}


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


@pytest.mark.parametrize("args,needle", [
    (["--as-of", "2025-06-30T15:00:00"], "timezone-naive"),
    (["--as-of", "yesterday"], "not ISO-8601"),
    (["--paths", "0"], "monte_carlo_paths"),
    (["--horizons", "1,x"], "comma-separated integers"),
    (["--horizons", "0,3"], "positive"),
    (["--config", "/nonexistent.yaml"], "not found"),
    (["--mode", "exploratory"], "--override-reason"),
    (["--override-reason", "x"], "only valid with --mode exploratory"),
])
def test_demo_invalid_inputs_exit_2(tmp_path, capsys, args, needle):
    assert main(["demo", "--out", str(tmp_path / "o"), *args]) == 2
    assert needle in capsys.readouterr().err


# ---------------------------------------------------------------- build-snapshot
def test_build_snapshot_ok(tmp_path, data_dir):
    out = tmp_path / "snap"
    p = _vms("build-snapshot", "--input", str(data_dir), "--ticker", INST, "--as-of", "2024-05-15", "--out", str(out))
    assert p.returncode == 0, p.stderr
    s = json.loads(p.stdout)
    assert s["status"] == "PASS_WITH_WARNINGS" and "MISSING_QUARTER" in s["issues"]
    assert "STALE_FINANCIALS" in s["issues"]   # FY2023 annual report overdue (published 2024-06-20)
    for n in ("data_manifest.json", "data_quality_report.json", "pit_snapshot.json"):
        art = json.loads((out / n).read_text())
        assert art["run_id"] == s["run_id"] and art["schema_version"] == s["schema_version"]
    man = json.loads((out / "data_manifest.json").read_text())
    assert man["as_of"] == "2024-05-15T15:00:00+08:00" and man["field_registry_version"] == "FIELDS-2"
    assert man["excluded_post_as_of"]["financial"] > 0 and len(man["snapshot_hash"]) == 64
    rep = json.loads((out / "data_quality_report.json").read_text())
    assert {c["check"]: c["status"] for c in rep["checks"]}["EV_BRIDGE"] == "DEFERRED"


def test_build_snapshot_blocked_production_exit_3_no_snapshot(tmp_path, data_dir):
    _corrupt_capex_sign(data_dir)
    out = tmp_path / "snap"
    p = _vms("build-snapshot", "--input", str(data_dir), "--ticker", INST, "--as-of", "2024-12-31", "--out", str(out))
    assert p.returncode == 3
    assert "BLOCKED" in p.stderr and "SIGN_CONVENTION_VIOLATION" in p.stderr
    assert (out / "data_quality_report.json").is_file() and not (out / "pit_snapshot.json").exists()
    assert json.loads((out / "data_quality_report.json").read_text())["status"] == "BLOCKED"


def test_build_snapshot_blocked_before_bad_record_published(tmp_path, data_dir):
    _corrupt_capex_sign(data_dir)   # bad record published 2023-08-28 18:00
    assert main(["build-snapshot", "--input", str(data_dir), "--ticker", INST, "--as-of", "2023-08-28",
                 "--out", str(tmp_path / "s")]) == 0


def test_build_snapshot_exploratory_override_recorded(tmp_path, data_dir):
    _corrupt_capex_sign(data_dir)
    out = tmp_path / "snap"
    rc = main(["build-snapshot", "--input", str(data_dir), "--ticker", INST, "--as-of", "2024-12-31",
               "--out", str(out), "--mode", "exploratory", "--override-reason", "checking sign issue"])
    assert rc == 0 and (out / "pit_snapshot.json").is_file()
    rep = json.loads((out / "data_quality_report.json").read_text())
    assert rep["status"] == "BLOCKED" and rep["usable_for_production"] is False
    assert rep["override"] == {"mode": "exploratory", "reason": "checking sign issue",
                               "overridden_critical_codes": ["SIGN_CONVENTION_VIOLATION"]}


def test_build_snapshot_invalid_schema_exit_2(tmp_path, data_dir, capsys):
    p = data_dir / "financial_observations.csv"
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    df.loc[0, "currency"] = "RMB"
    df.to_csv(p, index=False)
    assert main(["build-snapshot", "--input", str(data_dir), "--ticker", INST, "--as-of", "2024-12-31",
                 "--out", str(tmp_path / "s")]) == 2
    assert "line 2: currency" in capsys.readouterr().err


# ---------------------------------------------------------------- validate-data
def test_validate_data_schema_only(data_dir, capsys):
    assert main(["validate-data", "--input", str(data_dir)]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["status"] == "SCHEMA_VALID" and "pass --as-of" in rep["note"]


def test_validate_data_as_of_filters(data_dir, capsys):
    assert main(["validate-data", "--input", str(data_dir), "--as-of", "2022-06-30"]) == 0
    rep = json.loads(capsys.readouterr().out)
    inst = rep["instruments"][0]
    assert inst["status"] == "PASS" and inst["excluded_post_as_of"]["financial"] > 0
    assert rep["as_of"] == "2022-06-30T15:00:00+08:00"


def test_validate_data_as_of_blocked_exit_3(data_dir, capsys):
    _corrupt_capex_sign(data_dir)
    assert main(["validate-data", "--input", str(data_dir), "--as-of", "2024-12-31"]) == 3
    assert "BLOCKED" in capsys.readouterr().err


def test_validate_data_invalid_rows_exit_2_with_line_numbers(data_dir, capsys):
    p = data_dir / "financial_observations.csv"
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    df.loc[0, "currency"] = "RMB"
    df.loc[1, "published_at"] = "2021-04-28T18:00:00"
    df.loc[2, "unit_scale"] = "millions"
    df.to_csv(p, index=False)
    assert main(["validate-data", "--input", str(data_dir)]) == 2
    err = capsys.readouterr().err
    assert "line 2: currency" in err and "line 3: published_at" in err and "timezone-naive" in err
    assert "line 4: unit_scale" in err


def test_validate_data_missing_files_and_columns(tmp_path, capsys):
    assert main(["validate-data", "--input", str(tmp_path / "nope")]) == 2
    tmp_path.joinpath("financial_observations.csv").write_text("instrument_id,value\nX,1\n")
    assert main(["validate-data", "--input", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "missing required columns" in err and "market_observations" in err
