"""CLI: vms sensitivity writes sensitivity_report.json into a prior run directory."""

from __future__ import annotations

import json
from pathlib import Path

from vms.cli.main import main


def test_cli_sensitivity_from_run_dir(tmp_path: Path):
    demo = tmp_path / "demo"
    # smaller demo — sensitivity inside demo is heavy; use returns then sensitivity with few paths
    assert main(["demo", "--out", str(demo), "--seed", "2", "--paths", "30", "--horizons", "1,3"]) == 0
    assert (demo / "sensitivity_report.json").exists()  # demo now writes Phase 8
    rep = json.loads((demo / "sensitivity_report.json").read_text())
    assert rep["schema_kind"] == "SensitivityReport" or "content_hash" in rep
    assert "monte_carlo_percentile_interval" in json.dumps(rep).lower() or rep.get("interval_labeling", {}).get("rule") == "MC_PERCENTILE_NOT_CI" or "MC_PERCENTILE" in json.dumps(rep)

    out = tmp_path / "sens"
    rc = main(["sensitivity", "--run-dir", str(demo), "--out", str(out), "--seed", "2", "--paths", "25", "--years", "3"])
    assert rc == 0
    s = json.loads((out / "sensitivity_report.json").read_text())
    assert s.get("content_hash") or (s.get("schema_kind") == "SensitivityReport")
    # reproduce
    out2 = tmp_path / "sens2"
    assert main(["sensitivity", "--run-dir", str(demo), "--out", str(out2), "--seed", "2", "--paths", "25", "--years", "3"]) == 0
    s2 = json.loads((out2 / "sensitivity_report.json").read_text())
    assert s["content_hash"] == s2["content_hash"]
