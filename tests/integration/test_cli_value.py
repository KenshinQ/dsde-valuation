"""`vms value` (Phase 6)."""

from __future__ import annotations

import json
from pathlib import Path

from tests.company import cyclical_company
from tests.factories import INST as CINST
from vms.cli.main import main
from vms.data.io import write_directory


def test_value_artifacts(tmp_path, capsys):
    load, as_of = cyclical_company()
    d = tmp_path / "data"
    write_directory(d, load.financial, load.market, load.corporate_actions, list(load.sources.values()),
                    classifications=load.classifications)
    out = tmp_path / "o"
    rc = main(["value", "--input", str(d), "--ticker", CINST, "--as-of", as_of.date().isoformat(),
               "--out", str(out), "--seed", "8", "--paths", "25", "--years", "4",
               "--policy", "historical_continuation"])
    assert rc == 0, capsys.readouterr()
    summ = json.loads(capsys.readouterr().out)
    vs = json.loads((out / "valuation_summary.json").read_text())
    assert vs["run_id"] == summ["run_id"] and vs["schema_version"] == "vms-0.2.phase6"
    assert vs["central"]["status"] == "VALID"
    assert vs["n_valid_dcf"] == 25
    assert (out / "path_valuations.parquet").exists()
    assert (out / "financial_path_ledgers.parquet").exists()
    assert summ["central_vps_dcf"] is not None and summ["wacc"] > 0
