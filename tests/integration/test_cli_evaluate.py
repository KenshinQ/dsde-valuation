"""CLI: vms evaluate --universe --start --end writes evaluation_report.json."""

from __future__ import annotations

import json
from pathlib import Path

from vms.cli.main import main

REPO = Path(__file__).resolve().parents[2]


def test_cli_evaluate_synthetic(tmp_path: Path):
    out = tmp_path / "eval"
    rc = main([
        "evaluate",
        "--universe", str(REPO / "config" / "universe.synthetic.yaml"),
        "--start", "2018-01-01",
        "--end", "2022-12-31",
        "--out", str(out),
    ])
    assert rc == 0
    rep = json.loads((out / "evaluation_report.json").read_text())
    assert rep["schema_kind"] == "EvaluationReport" or "labels" in rep
    assert rep["labels"]["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert rep["n_forecasts_persisted"] > 0
    assert (out / "forecasts").exists()
    # random split rejected
    rc2 = main([
        "evaluate", "--universe", str(REPO / "config" / "universe.synthetic.yaml"),
        "--start", "2018-01-01", "--end", "2022-12-31", "--out", str(tmp_path / "bad"),
        "--split-mode", "random",
    ])
    assert rc2 == 2
