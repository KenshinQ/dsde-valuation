"""Crafted annual company fixtures for Phase-2 tests (CNY yuan, FY records only)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from tests.conftest import REPO, make_load
from tests.factories import INST, fobs, mobs, src
from vms.schemas import CorporateActionEvent, InstrumentClassification
from vms.schemas.config import load_config

CST = timezone(timedelta(hours=8))
BASE_YEAR_VALUES = {
    "revenue": 1000.0, "cost_of_revenue": 700.0, "gross_profit": 300.0, "operating_expenses": 200.0,
    "ebit": 100.0, "interest_expense": 4.0, "tax_expense": 24.0, "parent_net_income": 72.0,
    "depreciation_amortization": 40.0, "capex": 50.0, "dividends_paid": 21.6, "acquisitions_net": 0.0,
    "share_repurchases": 0.0, "cash_flow_from_operations": 110.0,
    "cash": 200.0, "interest_bearing_debt": 100.0, "accounts_receivable": 150.0, "inventory": 120.0,
    "accounts_payable": 90.0, "total_assets": 1000.0, "total_liabilities": 400.0, "total_equity": 600.0,
}


def company(years=(2021, 2022, 2023, 2024), growth=0.05, overrides=None, industry="机械设备", scheme="SW2021_L1",
            shares=(1e3, 1e3, 1e3, 1e3), price=10.0, drop=(), actions=()):
    """FY records for each year. Flows grow with `growth`; `overrides[(year, field)] = value|None|'na'`."""
    overrides = overrides or {}
    fin = []
    for i, y in enumerate(years):
        g = (1 + growth) ** i
        for name, v in BASE_YEAR_VALUES.items():
            if (y, name) in drop:
                continue
            val = v * g
            status = None
            if (y, name) in overrides:
                val = overrides[(y, name)]
                if val == "na":
                    val, status = None, "not_applicable"
            fin.append(fobs(f"{y}-12-31", name, val, f"{y + 1}-04-20", status=status))
    mkt = [mobs(f"{y}-12-29", price, shares=s) for y, s in zip(years, shares)]
    mkt.append(mobs(f"{years[-1] + 1}-04-30", price, shares=shares[-1]))
    cls = [] if industry is None else [InstrumentClassification(
        instrument_id=INST, scheme=scheme, industry=industry, published_at=datetime(2020, 1, 1, tzinfo=CST),
        source_id="S")]
    load = make_load(fin, mkt, list(actions), sources=[src()])
    load.classifications = cls
    as_of = datetime.combine(date(years[-1] + 1, 5, 6), time(15), CST)
    return load, as_of


def loaded_config():
    return load_config(REPO / "config/default.yaml")
