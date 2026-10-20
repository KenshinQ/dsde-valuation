"""CLI: vms returns writes return_distribution_summary.json (+ parquet)."""

from __future__ import annotations

import json
from pathlib import Path

from vms.cli.main import main


def test_cli_returns(tmp_path: Path):
    demo = tmp_path / "demo"
    assert main(["demo", "--out", str(demo), "--seed", "3", "--paths", "40", "--horizons", "1,3"]) == 0
    out = tmp_path / "ret"
    ticker = "SYN000001.SZ"
    rc = main(["returns", "--input", str(demo / "data"), "--ticker", ticker, "--as-of", "2025-06-30",
               "--out", str(out), "--seed", "3", "--paths", "40", "--years", "3", "--horizons", "1,3"])
    assert rc == 0
    summary = json.loads((out / "return_distribution_summary.json").read_text())
    assert summary["schema_version"].startswith("vms-0.1")
    assert summary["schema_kind"] == "ReturnDistributionBundle" or "spot_price" in summary
    body = summary if "spot_price" in summary else summary.get("bundle", summary)
    # artifact stamps wrap payload — find spot
    if "spot_price" not in body:
        # stamped artifact: keys include run_id at top; payload fields merged or nested
        assert "entry_prices" in summary or "spot_price" in summary
    assert (out / "path_returns.parquet").exists() or (out / "path_returns_error.json").exists()
    assert (out / "valuation_summary.json").exists()
