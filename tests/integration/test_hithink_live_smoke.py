"""Live smoke: ingest 600519.SH if local DBs exist; else skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vms.providers.hithink.paths import duckdb_available, fund_db_path, market_db_path

REPO = Path(__file__).resolve().parents[2]
TICKER = "600519.SH"


def _dbs_ready() -> bool:
    return duckdb_available() and fund_db_path().is_file() and market_db_path().is_file()


pytestmark = pytest.mark.skipif(not _dbs_ready(), reason="HiThink/market DuckDB or duckdb pkg missing")


def test_fetch_bundle_local_moutai():
    from vms.providers.hithink import fetch_bundle

    load, diag = fetch_bundle(TICKER, prefer_local=True, min_local=1)
    assert load.ok
    assert len(load.financial) > 0
    assert len(load.market) > 0
    assert "hithink_em_notice" in load.sources
    src = load.sources["hithink_em_notice"]
    assert src.versioning.value == "LATEST_ONLY"
    assert src.reporting_convention.value == "CN_CUMULATIVE_YTD"
    assert all(m.adjusted_close is None for m in load.market)
    assert diag.notice_joined + diag.notice_fallback > 0
    # Enrichment (EM public APIs / local cache): industry, shares, CA with announce dates
    assert load.classifications, "expected EM F10 industry classification"
    assert load.classifications[0].scheme == "SW2021_L1"
    assert load.classifications[0].industry  # e.g. 食品饮料
    assert load.corporate_actions_provided is True
    assert len(load.corporate_actions) >= 1
    assert all(e.announced_at is not None for e in load.corporate_actions)
    assert sum(1 for m in load.market if m.shares_outstanding is not None) > 0
    # Never period_end-as-PIT for NOTICE-joined rows
    for o in load.financial:
        if o.revision_id and "hithink_report_date_ms_fallback" in (o.revision_id or ""):
            assert o.quality_status.value == "low_confidence"
        else:
            assert o.published_at.hour == 15


def test_cli_ingest_and_build_snapshot(tmp_path):
    import subprocess
    import sys

    exe = REPO / ".venv" / "bin" / "vms"
    py = [str(exe)] if exe.is_file() else [sys.executable, "-m", "vms.cli.main"]
    out = tmp_path / "ingest"
    r = subprocess.run(
        [*py, "ingest-hithink", "--ticker", TICKER, "--out", str(out), "--prefer-local"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    summary = json.loads(r.stdout)
    assert summary["n_financial"] > 0
    assert summary["pit_complete_expected"] is False
    assert summary.get("n_corporate_actions", 0) >= 1
    assert summary.get("n_classifications", 0) >= 1
    assert summary.get("n_market_with_shares", 0) > 0
    assert (out / "sources.yaml").is_file()
    assert (out / "financial_observations.csv").is_file() or (out / "financial_observations.parquet").is_file()

    snap_out = tmp_path / "snap"
    r2 = subprocess.run(
        [*py, "build-snapshot", "--input", str(out), "--ticker", TICKER,
         "--as-of", "2025-06-30", "--out", str(snap_out),
         "--mode", "exploratory", "--override-reason", "hithink_live_smoke"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    body = json.loads(r2.stdout)
    # pit_complete false
    assert body.get("pit_complete") is False or body.get("status") in (
        "PIT_INCOMPLETE", "PASS_WITH_WARNINGS", "PASS", "BLOCKED",
    )
    # read report artifact
    rep = json.loads((snap_out / "data_quality_report.json").read_text())
    assert rep["pit_complete"] is False
    # market adjusted_close never in snapshot path — check ingest market file
    import pandas as pd
    mpath = out / "market_observations.csv"
    if mpath.is_file():
        df = pd.read_csv(mpath)
        if "adjusted_close" in df.columns:
            assert df["adjusted_close"].isna().all() or (df["adjusted_close"].astype(str) == "nan").all() or df["adjusted_close"].isnull().all()
