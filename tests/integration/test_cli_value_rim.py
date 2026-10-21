"""CLI: vms value-rim (R1 real-bank RIM) + legacy project/value still UNSUPPORTED."""

from __future__ import annotations

import json
from pathlib import Path

from vms.cli.main import main


def _write_bank_dir(tmp: Path) -> Path:
    """Minimal bank LoadResult directory for CLI smoke (no live ingest)."""
    from datetime import date, datetime, time, timedelta, timezone

    from vms.data.io import LoadResult, write_directory
    from vms.schemas import (
        FinancialObservation,
        InstrumentClassification,
        MarketObservation,
        SourceDescriptor,
    )
    from vms.schemas.fields import get_field

    CST = timezone(timedelta(hours=8))
    INST = "000001.SZ"

    def ts(d: str, hh: int = 18) -> datetime:
        return datetime.combine(date.fromisoformat(d), time(hh), CST)

    def f(period_end: str, field: str, value, pub: str) -> FinancialObservation:
        cf = get_field(field)
        return FinancialObservation(
            instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=ts(pub),
            statement_type=cf.statement_type if cf else "income", field_name=field, value=value,
            currency="CNY", unit_scale="unit", source_id="S", revision_id="r0", quality_status="observed",
        )

    fins = []
    for y, te, ni, rev, div, ta in [
        (2023, 472.0e9, 46.455e9, 164.699e9, 13.773e9, 5.5e12),
        (2024, 494.842e9, 44.508e9, 146.695e9, 26.807e9, 5.7e12),
    ]:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            f(pe, "total_equity", te, pub),
            f(pe, "parent_net_income", ni, pub),
            f(pe, "revenue", rev, pub),
            f(pe, "dividends_paid", div, pub),
            f(pe, "total_assets", ta, pub),
            f(pe, "total_liabilities", ta - te, pub),
        ])
    mkts = [MarketObservation(
        instrument_id=INST, timestamp=ts("2025-06-30", 15), raw_close=12.07,
        adjusted_close=None, shares_outstanding=1.9405918198e10, currency="CNY", source_id="S",
    )]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    load = LoadResult(
        financial=fins, market=mkts, corporate_actions=[],
        sources={"S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                       versioning="FULL_HISTORY")},
        classifications=[cls],
    )
    data = tmp / "data"
    write_directory(data, load.financial, load.market, corporate_actions=[], sources=list(load.sources.values()),
                    fmt="csv", classifications=load.classifications)
    return data


def test_cli_value_rim_bank_valid(tmp_path, repo):
    data = _write_bank_dir(tmp_path)
    out = tmp_path / "rim"
    cfg = str(repo / "config/default.yaml")
    rc = main([
        "value-rim", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R1 unit smoke: synthetic bank-like PIT for CLI",
        "--years", "5", "--zeros-explicit",
    ])
    assert rc == 0
    summ = json.loads((out / "value_rim_summary.json").read_text())
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["profile_primary"] == "FINANCIAL_INSTITUTION"
    assert summ["rim_status"] == "VALID"
    assert summ["ev_bridge_applied"] is False
    assert summ["ensemble"] is None
    assert summ["industrial_fcff_disabled"]["fcff_dcf_eligible"] is False
    assert "CLEAN_SURPLUS_ZEROS_ASSUMED" in summ["flags"]
    assert summ["equity_value"] is not None
    assert (out / "rim_inputs.json").exists()
    assert (out / "method_result.json").exists()


def test_cli_legacy_project_value_still_unsupported_on_bank(tmp_path, repo):
    data = _write_bank_dir(tmp_path)
    cfg = str(repo / "config/default.yaml")
    out_p = tmp_path / "project"
    rc_p = main([
        "project", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_p), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R1: legacy gate must remain",
    ])
    assert rc_p == 4  # EXIT_UNSUPPORTED
    out_v = tmp_path / "value"
    rc_v = main([
        "value", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_v), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R1: legacy gate must remain", "--seed", "42", "--paths", "10", "--years", "3",
    ])
    assert rc_v == 4
