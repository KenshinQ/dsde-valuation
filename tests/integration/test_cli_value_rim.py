"""CLI: vms value-rim (R1/R2 real-bank RIM) + legacy project/value still UNSUPPORTED."""

from __future__ import annotations

import json
from pathlib import Path

from vms.cli.main import main


def _write_bank_dir(tmp: Path, *, r2: bool = True) -> Path:
    """Minimal bank LoadResult directory for CLI smoke (no live ingest)."""
    from datetime import date, datetime, time, timedelta, timezone

    from vms.data.io import LoadResult, write_directory
    from vms.schemas import (
        CorporateActionEvent,
        FinancialObservation,
        InstrumentClassification,
        MarketObservation,
        SourceDescriptor,
    )
    from vms.schemas.fields import get_field

    CST = timezone(timedelta(hours=8))
    INST = "000001.SZ"
    SHARES = 1.9405918198e10

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
    series = [
        (2019, 300e9, 40e9, 1.4, 28e9),
        (2020, 330e9, 45e9, 1.5, 30e9),
        (2021, 360e9, 50e9, 1.7, 35e9),
        (2022, 400e9, 55e9, 1.9, 40e9),
        (2023, 472.0e9, 69.55e9, 2.25, 46.455e9),
        (2024, 494.842e9, 69.948e9, 2.15, 44.508e9),
    ]
    for y, te, oei, eps, ni in series:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            f(pe, "total_equity", te, pub),
            f(pe, "parent_net_income", ni, pub),
            f(pe, "revenue", 150e9, pub),
            f(pe, "dividends_paid", 20e9, pub),
            f(pe, "total_assets", te * 10, pub),
            f(pe, "total_liabilities", te * 9, pub),
        ])
        if r2:
            fins.extend([
                f(pe, "other_equity_instruments", oei, pub),
                f(pe, "minority_interest", 0.0, pub),
                f(pe, "basic_eps", eps, pub),
                f(pe, "goodwill", 7.568e9, pub),
                f(pe, "other_comprehensive_income", -0.3e9, pub),
                f(pe, "interest_income", 180e9, pub),
            ])
    mkts = [
        MarketObservation(
            instrument_id=INST, timestamp=ts(f"{y}-12-30", 15), raw_close=12.0,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ) for y, *_ in series
    ]
    mkts.append(MarketObservation(
        instrument_id=INST, timestamp=ts("2025-06-30", 15), raw_close=12.07,
        adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
    ))
    cas = []
    if r2:
        cas = [
            CorporateActionEvent(
                action_id="em:000001:2024-12-31:cash", instrument_id=INST, action_type="cash_dividend",
                announced_at=ts("2025-03-15", 15), ex_date=date.fromisoformat("2025-06-12"),
                cash_per_share=0.362, currency="CNY", source_id="em_sharebonus",
            ),
            CorporateActionEvent(
                action_id="em:000001:2024-06-30:cash", instrument_id=INST, action_type="cash_dividend",
                announced_at=ts("2024-08-16", 15), ex_date=date.fromisoformat("2024-10-10"),
                cash_per_share=0.246, currency="CNY", source_id="em_sharebonus",
            ),
        ]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    load = LoadResult(
        financial=fins, market=mkts, corporate_actions=cas,
        sources={"S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                       versioning="FULL_HISTORY")},
        classifications=[cls], corporate_actions_provided=True,
    )
    data = tmp / "data"
    write_directory(
        data, load.financial, load.market, corporate_actions=cas,
        sources=list(load.sources.values()), fmt="csv", classifications=load.classifications,
    )
    return data


def test_cli_value_rim_bank_valid(tmp_path, repo):
    data = _write_bank_dir(tmp_path, r2=True)
    out = tmp_path / "rim"
    cfg = str(repo / "config/default.yaml")
    rc = main([
        "value-rim", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R2 unit smoke: synthetic bank PIT for CLI",
        "--years", "5", "--zeros-explicit", "--paths", "80", "--seed", "7",
    ])
    assert rc == 0
    summ = json.loads((out / "value_rim_summary.json").read_text())
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert summ["profile_primary"] == "FINANCIAL_INSTITUTION"
    assert summ["rim_status"] == "VALID"
    assert summ["ev_bridge_applied"] is False
    assert summ["ensemble"] is None
    assert summ["industrial_fcff_disabled"]["fcff_dcf_eligible"] is False
    assert summ["equity_basis"] == "common"
    assert summ["common_equity_0"] == 424_894_000_000.0
    assert abs(summ["last_fy_dps"] - 0.608) < 1e-9
    assert "CLEAN_SURPLUS_ZEROS_ASSUMED" in summ["flags"] or "OCI_CONSTANT_LAST_FY_ASSUMPTION" in summ["flags"]
    assert summ["distribution"]["vps_p50"] is not None
    assert summ["distribution"]["vps_p05"] < summ["distribution"]["vps_p50"] < summ["distribution"]["vps_p95"]
    assert (out / "rim_inputs.json").exists()
    assert (out / "rim_distribution.json").exists()
    assert (out / "method_result.json").exists()


def test_cli_legacy_project_value_still_unsupported_on_bank(tmp_path, repo):
    data = _write_bank_dir(tmp_path, r2=True)
    cfg = str(repo / "config/default.yaml")
    out_p = tmp_path / "project"
    rc_p = main([
        "project", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_p), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R2: legacy gate must remain",
    ])
    assert rc_p == 4  # EXIT_UNSUPPORTED
    out_v = tmp_path / "value"
    rc_v = main([
        "value", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_v), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R2: legacy gate must remain", "--seed", "42", "--paths", "10", "--years", "3",
    ])
    assert rc_v == 4
