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


CYCLE_GROWTH = (0.15, 0.12, -0.06, -0.12, 0.02, 0.09, 0.16, 0.13, -0.04, -0.10, 0.03, 0.08, 0.14, 0.11, -0.05)


def cyclical_company(first_year=2009, n_years=16, growth=CYCLE_GROWTH, **kw):
    """Long annual history with growth/contraction cycles; EBIT margin moves with growth (operating leverage)."""
    years = tuple(range(first_year, first_year + n_years))
    over = dict(kw.pop("overrides", {}) or {})
    rev = 1000.0
    for i, y in enumerate(years):
        if i:
            rev *= 1 + growth[(i - 1) % len(growth)]
        g = growth[(i - 1) % len(growth)] if i else 0.05
        margin = 0.10 + 0.3 * g
        over.setdefault((y, "revenue"), rev)
        over.setdefault((y, "cost_of_revenue"), rev * 0.7)
        over.setdefault((y, "gross_profit"), rev * 0.3)
        over.setdefault((y, "ebit"), rev * margin)
        over.setdefault((y, "operating_expenses"), rev * (0.3 - margin))
        over.setdefault((y, "accounts_receivable"), rev * (0.15 + 0.1 * max(-g, 0)))
    return company(years=years, growth=0.0, overrides=over, shares=tuple([1e3] * n_years), **kw)
