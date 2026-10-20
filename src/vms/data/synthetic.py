"""SYNTHETIC operating-company data source (offline, seeded). Phase 1 version.

Every record carries source_id='SYNTHETIC'; numbers describe no real company. The dataset is
built to exercise the Phase-1 PIT machinery:

- Flows are reported **cumulative YTD** (source declared ``CN_CUMULATIVE_YTD``, ``FULL_HISTORY``).
- **Restatement:** FY2022 revenue/gross_profit/ebit/parent_net_income restated (revision ``r1``)
  with the H1-2023 report published 2023-08-28 18:00.
- **Late publication:** FY2023 annual report published 2024-06-20 18:00 (after the Q1-2024 report
  of 2024-04-28), so snapshots in between have a missing 2023-12-31 quarter.
- **Corporate action:** the FY2023 report announces a 10送3 bonus share (ratio 1.3) and a cash
  dividend of 0.50/share, ex-date 2024-07-10; the dividend is **revised** to 0.45 on 2024-07-01.
  Raw prices fall and shares rise by 1.3x at the ex-date.
- **Vendor adjusted_close** is forward-adjusted to the dataset end (前复权), i.e. it embeds the
  2024 bonus share in 2021–2024H1 prices — the snapshot must not use it.
- All publications are at 18:00 Asia/Shanghai (after the 15:00 close).
- ``minority_interest`` is explicitly missing every period.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from vms.schemas import (CorporateActionEvent, FinancialObservation, MarketObservation, QualityStatus,
                         ReportingConvention, SourceDescriptor, UnitScale, Versioning)
from vms.seeding import stream_rng

SYNTHETIC_SOURCE = "SYNTHETIC"
SYNTHETIC_INSTRUMENT = "SYN000001.SZ"
TZ = ZoneInfo("Asia/Shanghai")
START_YEAR, N_YEARS = 2021, 4

RESTATED_PERIOD = date(2022, 12, 31)
RESTATEMENT_PUBLISHED = datetime(2023, 8, 28, 18, 0, tzinfo=TZ)
LATE_PERIOD = date(2023, 12, 31)
LATE_PUBLISHED = datetime(2024, 6, 20, 18, 0, tzinfo=TZ)
BONUS_ACTION_ID = "SYN-2023-BONUS"
DIVIDEND_ACTION_ID = "SYN-2023-DIV"
EX_DATE = date(2024, 7, 10)
BONUS_RATIO = 1.3
DIVIDEND_REVISED_AT = datetime(2024, 7, 1, 18, 0, tzinfo=TZ)
_BASE_SHARES = 1.0e9

_FLOWS = [("income", "revenue"), ("income", "cost_of_revenue"), ("income", "gross_profit"),
          ("income", "operating_expenses"), ("income", "ebit"), ("income", "parent_net_income"),
          ("income", "depreciation_amortization"), ("cash_flow", "cash_flow_from_operations"),
          ("cash_flow", "capex"), ("cash_flow", "dividends_paid")]
_STOCKS = ["cash", "interest_bearing_debt", "accounts_receivable", "inventory", "accounts_payable",
           "total_assets", "total_liabilities", "total_equity"]


def source_descriptors() -> list[SourceDescriptor]:
    return [SourceDescriptor(source_id=SYNTHETIC_SOURCE, reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
                             versioning=Versioning.FULL_HISTORY,
                             description="SYNTHETIC example source — not real data")]


def _publication(pe: date) -> datetime:
    if pe == LATE_PERIOD:
        return LATE_PUBLISHED
    lag = {3: 28, 6: 59, 9: 28, 12: 116}[pe.month]
    return datetime.combine(pe + timedelta(days=lag), time(18, 0), TZ)


def _obs(pe, stype, name, value, pub, rev="r0", status=QualityStatus.OBSERVED) -> FinancialObservation:
    return FinancialObservation(
        instrument_id=SYNTHETIC_INSTRUMENT, period_end=pe, published_at=pub, ingested_at=pub + timedelta(days=1),
        statement_type=stype, field_name=name, value=None if value is None else round(float(value), 4),
        currency="CNY", unit_scale=UnitScale.TEN_THOUSAND, source_id=SYNTHETIC_SOURCE,
        revision_id=rev if value is not None else None, quality_status=status)


def generate(seed: int) -> tuple[list[FinancialObservation], list[MarketObservation], list[CorporateActionEvent]]:
    rng = stream_rng(seed, "synthetic_data")
    fin: list[FinancialObservation] = []
    revenue_q = 50_000.0  # 万元 standalone quarter
    equity = 400_000.0
    ytd: dict[str, float] = {}
    for year in range(START_YEAR, START_YEAR + N_YEARS):
        ytd = {name: 0.0 for _, name in _FLOWS}
        for month in (3, 6, 9, 12):
            pe = date(year, month, calendar.monthrange(year, month)[1])
            pub = _publication(pe)
            revenue_q *= 1.0 + rng.normal(0.02, 0.04)
            gm = float(np.clip(rng.normal(0.32, 0.02), 0.05, 0.8))
            opex = revenue_q * float(rng.normal(0.18, 0.015))
            q = {"revenue": revenue_q, "cost_of_revenue": revenue_q * (1 - gm), "gross_profit": revenue_q * gm,
                 "operating_expenses": opex}
            q["ebit"] = q["gross_profit"] - opex
            q["parent_net_income"] = q["ebit"] * 0.75
            q["depreciation_amortization"] = revenue_q * float(rng.uniform(0.03, 0.05))
            q["cash_flow_from_operations"] = q["parent_net_income"] + q["depreciation_amortization"]
            q["capex"] = revenue_q * float(rng.uniform(0.04, 0.07))
            q["dividends_paid"] = revenue_q * 0.1 if month == 6 else 0.0
            for k in ytd:
                ytd[k] += q[k]
            for stype, name in _FLOWS:
                fin.append(_obs(pe, stype, name, ytd[name], pub))
            equity += q["parent_net_income"] - q["dividends_paid"]
            liabilities = revenue_q * float(rng.uniform(2.0, 2.4))
            stocks = {"cash": revenue_q * float(rng.uniform(0.8, 1.2)),
                      "interest_bearing_debt": revenue_q * float(rng.uniform(0.3, 0.5)),
                      "accounts_receivable": revenue_q * float(rng.uniform(0.5, 0.7)),
                      "inventory": revenue_q * float(rng.uniform(0.4, 0.6)),
                      "accounts_payable": revenue_q * float(rng.uniform(0.3, 0.5)),
                      "total_liabilities": liabilities, "total_equity": equity,
                      "total_assets": liabilities + equity}
            for name in _STOCKS:
                fin.append(_obs(pe, "balance_sheet", name, stocks[name], pub))
            fin.append(_obs(pe, "balance_sheet", "minority_interest", None, pub, status=QualityStatus.MISSING))
            if pe == RESTATED_PERIOD:
                d = ytd["revenue"] * 0.03
                restated = {("income", "revenue"): ytd["revenue"] - d, ("income", "gross_profit"): ytd["gross_profit"] - d,
                            ("income", "ebit"): ytd["ebit"] - d,
                            ("income", "parent_net_income"): ytd["parent_net_income"] - 0.75 * d}
                for (stype, name), v in restated.items():
                    fin.append(_obs(pe, stype, name, v, RESTATEMENT_PUBLISHED, rev="r1"))

    actions = [
        CorporateActionEvent(action_id=BONUS_ACTION_ID, instrument_id=SYNTHETIC_INSTRUMENT, action_type="bonus_share",
                             announced_at=LATE_PUBLISHED, ex_date=EX_DATE, share_ratio=BONUS_RATIO, currency="CNY",
                             source_id=SYNTHETIC_SOURCE, revision_id="r0"),
        CorporateActionEvent(action_id=DIVIDEND_ACTION_ID, instrument_id=SYNTHETIC_INSTRUMENT,
                             action_type="cash_dividend", announced_at=LATE_PUBLISHED, ex_date=EX_DATE,
                             cash_per_share=0.50, currency="CNY", source_id=SYNTHETIC_SOURCE, revision_id="r0"),
        CorporateActionEvent(action_id=DIVIDEND_ACTION_ID, instrument_id=SYNTHETIC_INSTRUMENT,
                             action_type="cash_dividend", announced_at=DIVIDEND_REVISED_AT, ex_date=EX_DATE,
                             cash_per_share=0.45, currency="CNY", source_id=SYNTHETIC_SOURCE, revision_id="r1"),
    ]

    mkt: list[MarketObservation] = []
    price = 20.0  # economic (pre-bonus share basis) price
    for year in range(START_YEAR, START_YEAR + N_YEARS + 1):
        for month in range(1, 13):
            if year == START_YEAR + N_YEARS and month > 6:
                break
            d = date(year, month, calendar.monthrange(year, month)[1])
            price *= float(np.exp(rng.normal(0.008, 0.08)))
            post = d >= EX_DATE
            raw = price / BONUS_RATIO if post else price
            mkt.append(MarketObservation(
                instrument_id=SYNTHETIC_INSTRUMENT, timestamp=datetime.combine(d, time(15, 0), TZ),
                raw_close=round(raw, 2),
                adjusted_close=round(raw if post else raw / BONUS_RATIO, 4),  # 前复权 to dataset end
                shares_outstanding=_BASE_SHARES * (BONUS_RATIO if post else 1.0),
                corporate_action_version="vendor-qfq-2025H1", currency="CNY", source_id=SYNTHETIC_SOURCE))
    return fin, mkt, actions
