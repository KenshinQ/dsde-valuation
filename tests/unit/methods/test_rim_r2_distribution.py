"""R2b: P2 ROE bootstrap distribution + ke grid."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.distribution import historical_common_roe, run_rim_distribution
from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot
from vms.schemas import (
    CorporateActionEvent,
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.fields import get_field

# reuse fixture builder from R2a module via import of helpers by duplicating minimal set
CST = timezone(timedelta(hours=8))
INST = "000001.SZ"
SHARES = 1.9405918198e10


def _ts(d: str, hh: int = 18) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(period_end: str, field: str, value, pub: str) -> FinancialObservation:
    f = get_field(field)
    return FinancialObservation(
        instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=_ts(pub),
        statement_type=f.statement_type if f else "income", field_name=field, value=value,
        currency="CNY", unit_scale="unit", source_id="S", revision_id="r0", quality_status="observed",
    )


def _ca(report: str, cash: float, announced: str, ex: str) -> CorporateActionEvent:
    return CorporateActionEvent(
        action_id=f"em:000001:{report}:cash", instrument_id=INST, action_type="cash_dividend",
        announced_at=_ts(announced, 15), ex_date=date.fromisoformat(ex),
        cash_per_share=cash, currency="CNY", source_id="em_sharebonus",
    )


def _multi_year_snap():
    fins = []
    series = [
        (2015, 200e9, 20e9, 1.0),
        (2016, 220e9, 22e9, 1.05),
        (2017, 240e9, 25e9, 1.15),
        (2018, 270e9, 30e9, 1.25),
        (2019, 300e9, 40e9, 1.4),
        (2020, 330e9, 45e9, 1.5),
        (2021, 360e9, 50e9, 1.7),
        (2022, 400e9, 55e9, 1.9),
        (2023, 472.0e9, 69.55e9, 2.25),
        (2024, 494.842e9, 69.948e9, 2.15),
    ]
    for y, te, oei, eps in series:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(pe, "total_equity", te, pub),
            _f(pe, "other_equity_instruments", oei, pub),
            _f(pe, "minority_interest", 0.0, pub),
            _f(pe, "basic_eps", eps, pub),
            _f(pe, "parent_net_income", eps * SHARES, pub),
            _f(pe, "revenue", 100e9, pub),
            _f(pe, "total_assets", te * 10, pub),
            _f(pe, "total_liabilities", te * 9, pub),
            _f(pe, "goodwill", 7e9, pub),
            _f(pe, "other_comprehensive_income", -0.2e9, pub),
        ])
    mkts = [
        MarketObservation(
            instrument_id=INST, timestamp=_ts(f"{y}-12-30", 15), raw_close=10.0,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ) for y, *_ in series
    ]
    mkts.append(MarketObservation(
        instrument_id=INST, timestamp=_ts("2025-06-30", 15), raw_close=12.07,
        adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
    ))
    cas = [
        _ca("2024-12-31", 0.362, "2025-03-15", "2025-06-12"),
        _ca("2024-06-30", 0.246, "2024-08-16", "2024-10-10"),
    ]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=_ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    load = LoadResult(
        financial=fins, market=mkts, corporate_actions=cas,
        sources={"S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                       versioning="FULL_HISTORY")},
        classifications=[cls], corporate_actions_provided=True,
    )
    as_of, _ = parse_as_of("2025-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=load.financial, market=load.market,
        corporate_actions=cas, sources=load.sources, classifications=load.classifications,
    )
    return snap


def test_roe_history_pit_truncated(repo):
    snap = _multi_year_snap()
    hist = historical_common_roe(snap, zeros_explicit=True, max_years=10)
    assert len(hist.roe) >= 5
    assert hist.years[-1] == 2024
    assert all(r == r for r in hist.roe)  # finite


def test_p2_distribution_ordered_percentiles_and_reproducible(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _multi_year_snap()
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    d1 = run_rim_distribution(
        snap, loaded=loaded,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(bridge.book_equity_year),
        dps=float(bridge.last_fy_dps),
        diluted_shares=float(bridge.rim_inputs["diluted_shares"]),
        years=5, n_paths=100, seed=7,
        p1_common_ni=float(bridge.last_fy_ni),
        goodwill=bridge.goodwill_0,
        oci_constant=-0.2e9,
    )
    d2 = run_rim_distribution(
        snap, loaded=loaded,
        book_equity_0=float(bridge.common_equity_0),
        book_equity_year=int(bridge.book_equity_year),
        dps=float(bridge.last_fy_dps),
        diluted_shares=float(bridge.rim_inputs["diluted_shares"]),
        years=5, n_paths=100, seed=7,
        p1_common_ni=float(bridge.last_fy_ni),
        goodwill=bridge.goodwill_0,
        oci_constant=-0.2e9,
    )
    assert d1.ok and d2.ok
    assert len(d1.ke_grid) == 3
    primary = d1.ke_grid[0]
    assert primary.cost_of_equity == pytest.approx(0.08)
    assert primary.n_valid >= 10
    assert primary.vps_p05 < primary.vps_p50 < primary.vps_p95
    # reproducible
    assert d1.ke_grid[0].vps_p50 == d2.ke_grid[0].vps_p50
    assert d1.ke_grid[0].vps_p05 == d2.ke_grid[0].vps_p05
    # ke grid monotonic-ish: higher ke → lower VPS p50
    assert d1.ke_grid[0].vps_p50 > d1.ke_grid[2].vps_p50
    assert "RIM-NI-P2-ROE-v1" in d1.assumption_ids
    assert "RIM-KE-GRID-v1" in d1.assumption_ids
    assert d1.p1_control.get("value_per_share") is not None
