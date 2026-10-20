"""`vms estimate` (Phase 3): persisted state_posterior.json / driver_diagnostics.json, provenance, exit codes."""

from __future__ import annotations

import hashlib
import json
import shutil

import yaml

from tests.company import company, cyclical_company
from tests.factories import INST as CINST
from vms.cli.main import main
from vms.data.io import write_directory


def _write(tmp_path, load):
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    return d


def _estimate(d, out, as_of, *extra):
    return main(["estimate", "--input", str(d), "--ticker", CINST, "--as-of", as_of, "--out", str(out), *extra])


def test_estimate_artifacts_and_provenance(tmp_path, capsys):
    load, as_of = cyclical_company()
    d = _write(tmp_path, load)
    out = tmp_path / "o"
    assert _estimate(d, out, as_of.date().isoformat(), "--seed", "9") == 0
    summ = json.loads(capsys.readouterr().out)
    sp = json.loads((out / "state_posterior.json").read_text())
    dd = json.loads((out / "driver_diagnostics.json").read_text())
    for art in (sp, dd):
        assert art["run_id"] == summ["run_id"] and art["schema_version"] == "vms-0.1.phase6"
    # distinct schemas; market UNAVAILABLE
    assert sp["fundamental"]["kind"] == "FUNDAMENTAL" and sp["fundamental"]["inputs"] == "PIT_FUNDAMENTALS_ONLY"
    assert sp["market"] == {**sp["market"], "kind": "MARKET", "status": "UNAVAILABLE", "probabilities": None}
    assert abs(sum(sp["fundamental"]["probabilities"].values()) - 1) < 1e-9
    assert abs(sum(sp["fundamental_next_year"].values()) - 1) < 1e-9
    assert sp["model"]["model_id"] == "FUND-RULES" and sp["model"]["model_version"]
    assert sp["model"]["hmm_status"].startswith("NOT_IMPLEMENTED")
    assert len(sp["history"]) == 15 and sp["transitions"]["row_support"]
    assert sp["walk_forward"]["summary"]["n_scored"] > 0
    # walk-forward + provenance persisted
    wf = dd["walk_forward"]
    assert wf["version"] == "WF-1" and len(wf["origins"]) == 13 and wf["per_driver"]["ebit_margin"]["selection"]
    dist = dd["distributions"]
    assert dist["seed"] == 9 and dist["distribution_version"] == "DRIVER-DIST-1" and dist["estimation_config"]
    g = dist["drivers"]["revenue_growth"]
    assert all(o["refs"] for o in g["observations"]) and g["parameter_uncertainty"]["draws_loc"]
    assert g["selection"]["rule"].startswith("min mean walk-forward pinball")
    assert "MODEL-SELECTION-WF-v2" in dist["assumptions"]
    assert "REGIME-PIT-FUNDAMENTALS-ONLY-v1" in sp["fundamental"]["assumptions"]


def test_estimate_byte_reproducible_and_seed_sensitive(tmp_path, capsys):
    load, as_of = cyclical_company()
    d = _write(tmp_path, load)
    h = {}
    for name, seed in (("a", "1"), ("b", "1"), ("c", "2")):
        assert _estimate(d, tmp_path / name, as_of.date().isoformat(), "--seed", seed) == 0
        h[name] = {f: hashlib.sha256((tmp_path / name / f).read_bytes()).hexdigest()
                   for f in ("state_posterior.json", "driver_diagnostics.json")}
    assert h["a"] == h["b"]
    assert h["a"]["driver_diagnostics.json"] != h["c"]["driver_diagnostics.json"]


def test_estimate_unsupported_profile_exit_4(tmp_path, capsys):
    load, as_of = company(industry="银行")
    out = tmp_path / "o"
    assert _estimate(_write(tmp_path, load), out, as_of.date().isoformat()) == 4
    assert not (out / "state_posterior.json").exists()
    assert json.loads((out / "driver_diagnostics.json").read_text())["distributions"] is None
    assert "UNSUPPORTED_PROFILE" in capsys.readouterr().err


def test_estimate_unclassified_blocked_exit_3(tmp_path, capsys):
    load, as_of = company(industry=None)
    out = tmp_path / "o"
    assert _estimate(_write(tmp_path, load), out, as_of.date().isoformat()) == 3
    assert not (out / "state_posterior.json").exists()
    assert "INDUSTRY_UNCLASSIFIED" in capsys.readouterr().err


def test_estimate_hmm_not_implemented_exit_2(tmp_path, capsys, repo):
    cfg_dir = tmp_path / "cfg"
    shutil.copytree(repo / "config", cfg_dir)
    y = yaml.safe_load((cfg_dir / "default.yaml").read_text())
    y["regimes"]["model"] = "hmm"
    (cfg_dir / "default.yaml").write_text(yaml.safe_dump(y, allow_unicode=True))
    load, as_of = company()
    rc = _estimate(_write(tmp_path, load), tmp_path / "o", as_of.date().isoformat(),
                   "--config", str(cfg_dir / "default.yaml"))
    assert rc == 2 and "interface only" in capsys.readouterr().err
