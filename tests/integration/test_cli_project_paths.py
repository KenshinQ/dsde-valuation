"""`vms project-paths` (Phase 5)."""

from __future__ import annotations

import json

from tests.company import cyclical_company
from tests.factories import INST as CINST
from vms.cli.main import main
from vms.data.io import write_directory


def test_project_paths_artifacts(tmp_path, capsys):
    load, as_of = cyclical_company()
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    out = tmp_path / "o"
    rc = main(["project-paths", "--input", str(d), "--ticker", CINST, "--as-of", as_of.date().isoformat(),
               "--out", str(out), "--seed", "4", "--paths", "40", "--years", "3",
               "--policy", "historical_continuation"])
    assert rc == 0
    summ = json.loads(capsys.readouterr().out)
    fp = json.loads((out / "financial_path_bundle.json").read_text())
    assert fp["run_id"] == summ["run_id"] and fp["schema_version"] == "vms-0.1.phase9"
    assert fp["n_valid"] == 40 and fp["n_failed"] == 0
    assert fp["central"]["status"] == "VALID" and fp["aggregates"]["n"] == 40
    assert (out / "simulation_bundle.json").exists()
    assert summ["financial_n_valid"] == 40
