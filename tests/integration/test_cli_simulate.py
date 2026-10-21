"""`vms simulate` artifacts and exit codes (Phase 4)."""

from __future__ import annotations

import hashlib
import json

from tests.company import company, cyclical_company
from tests.factories import INST as CINST
from vms.cli.main import main
from vms.data.io import write_directory


def _write(tmp_path, load):
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    return d


def _sim(d, out, as_of, *extra):
    return main(["simulate", "--input", str(d), "--ticker", CINST, "--as-of", as_of, "--out", str(out),
                 "--paths", "80", "--years", "3", *extra])


def test_simulate_artifacts(tmp_path, capsys):
    load, as_of = cyclical_company()
    out = tmp_path / "o"
    assert _sim(_write(tmp_path, load), out, as_of.date().isoformat(), "--seed", "5") == 0
    summ = json.loads(capsys.readouterr().out)
    b = json.loads((out / "simulation_bundle.json").read_text())
    meta = json.loads((out / "simulation_metadata.json").read_text())
    assert b["run_id"] == summ["run_id"] == meta["run_id"]
    assert b["schema_version"] == "vms-0.2.phase2"
    assert b["sampler_version"] == "PATH-SAMPLER-1"
    assert b["central"]["kind"] == "central" and b["paths"]
    assert b["dependence"]["method"] == "gaussian_copula_shrunk_pearson"
    assert meta["status"] == "PATHS_ONLY_NOT_A_VALUATION"
    assert (out / "state_posterior.json").exists() and (out / "driver_diagnostics.json").exists()
    assert summ["n_valid"] == 80 and summ["seed_stable"] is True


def test_simulate_seed_reproducible(tmp_path):
    load, as_of = cyclical_company()
    d = _write(tmp_path, load)
    assert _sim(d, tmp_path / "a", as_of.date().isoformat(), "--seed", "9") == 0
    assert _sim(d, tmp_path / "b", as_of.date().isoformat(), "--seed", "9") == 0
    assert _sim(d, tmp_path / "c", as_of.date().isoformat(), "--seed", "10") == 0
    ha = hashlib.sha256((tmp_path / "a/simulation_bundle.json").read_bytes()).hexdigest()
    hb = hashlib.sha256((tmp_path / "b/simulation_bundle.json").read_bytes()).hexdigest()
    hc = hashlib.sha256((tmp_path / "c/simulation_bundle.json").read_bytes()).hexdigest()
    assert ha == hb != hc


def test_simulate_unsupported_exit_4(tmp_path, capsys):
    load, as_of = company(industry="银行")
    out = tmp_path / "o"
    assert _sim(_write(tmp_path, load), out, as_of.date().isoformat()) == 4
    assert json.loads((out / "simulation_bundle.json").read_text())["bundle"] is None
