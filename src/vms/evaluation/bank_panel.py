"""Synthetic deposit-taking FI panel for R6 RIM walk-forward (offline).

Labeled SYNTHETIC — never claims investment value. Includes lean-curated IDs
(000001.SZ among them). One short-OEI name demonstrates Track B hist_n<12 skip;
others carry deep OEI so Track B can be eligible when origins allow.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from vms.data import synthetic as syn
from vms.data.io import LoadResult
from vms.methods.rim.bank_peers import LEAN_CURATED_DEPOSIT_TAKING_FI
from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
from vms.schemas import (
    CorporateActionEvent,
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    QualityStatus,
    ReportingConvention,
    SourceDescriptor,
    UnitScale,
    Versioning,
)
from vms.seeding import stream_rng

TZ = ZoneInfo("Asia/Shanghai")

# Default offline subset: 000001 (short OEI) + two deep peers from lean curated.
DEFAULT_BANK_PANEL_IDS: tuple[str, ...] = (
    "000001.SZ",
    "600036.SH",
    "601398.SH",
)


def _pub(pe: date) -> datetime:
    return datetime(pe.year + 1, 4, 20, 18, 0, tzinfo=TZ)


def _obs(
    iid: str,
    pe: date,
    stype: str,
    name: str,
    value: float,
    pub: datetime,
) -> FinancialObservation:
    return FinancialObservation(
        instrument_id=iid,
        period_end=pe,
        published_at=pub,
        ingested_at=pub + timedelta(days=1),
        statement_type=stype,
        field_name=name,
        value=float(value),
        currency="CNY",
        unit_scale=UnitScale.UNIT,
        source_id=syn.SYNTHETIC_SOURCE,
        revision_id="r0",
        quality_status=QualityStatus.OBSERVED,
    )


def generate_bank_eval_panel(
    *,
    seed: int = 42,
    instrument_ids: list[str] | None = None,
    start_year: int = 2008,
    n_years: int = 16,
    short_oei_ids: frozenset[str] | None = None,
) -> dict[str, LoadResult]:
    """Multi-name annual synthetic deposit-taking FI panel for chronological RIM walk-forward.

    ``short_oei_ids`` (default {000001.SZ}) get OEI only from mid-series onward
    so own-hist common P/B depth stays below MIN_HIST_PB_POINTS=12 — Track B
    must skip honestly (no invent OEI / no lower floor).
    """
    ids = list(instrument_ids) if instrument_ids else list(DEFAULT_BANK_PANEL_IDS)
    short = short_oei_ids if short_oei_ids is not None else frozenset({"000001.SZ"})
    bank_label = deposit_taking_fi_sw_label()
    src = SourceDescriptor(
        source_id=syn.SYNTHETIC_SOURCE,
        reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
        versioning=Versioning.FULL_HISTORY,
        description="SYNTHETIC deposit-taking FI R6 eval panel — not real data",
    )
    out: dict[str, LoadResult] = {}
    for i, iid in enumerate(ids):
        rng = stream_rng(seed + i * 17, f"bank_eval_panel:{iid}")
        fin: list[FinancialObservation] = []
        # Scale book/NI by index so names differ
        te = 200e9 * (1 + 0.15 * i)
        oei = 20e9 * (1 + 0.1 * i)
        mi = 0.0
        shares = 1.0e10 * (1 + 0.05 * i)
        rev = 80e9 * (1 + 0.1 * i)
        ni = 15e9 * (1 + 0.1 * i)
        # Short-OEI names: OEI appears only after start_year + (n_years - 9)
        oei_from_year = start_year if iid not in short else (start_year + max(n_years - 9, 1))
        for y in range(start_year, start_year + n_years):
            pe = date(y, 12, 31)
            pub = _pub(pe)
            g = float(np.clip(rng.normal(0.06, 0.03), -0.05, 0.15))
            te *= 1 + g
            rev *= 1 + float(np.clip(rng.normal(0.04, 0.03), -0.1, 0.12))
            ni = te * float(np.clip(rng.normal(0.10, 0.015), 0.04, 0.16))
            oei *= 1 + float(np.clip(rng.normal(0.02, 0.01), -0.02, 0.06))
            gw = te * 0.015
            oci = float(rng.normal(0.0, 0.2e9))
            eps = ni / shares
            have_oei = y >= oei_from_year
            oei_v = float(oei) if have_oei else None
            flows: dict[str, float] = {
                "revenue": rev,
                "interest_income": rev * 0.7,
                "parent_net_income": ni,
                "basic_eps": eps,
                "other_comprehensive_income": oci,
                "dividends_paid": ni * 0.25,
                "cash_flow_from_operations": ni * 1.1,
                "capex": rev * 0.01,
                "acquisitions_net": 0.0,
                "share_repurchases": 0.0,
                "non_recurring_items_pretax": 0.0,
            }
            for name, val in flows.items():
                st = (
                    "cash_flow"
                    if name
                    in {
                        "cash_flow_from_operations",
                        "capex",
                        "acquisitions_net",
                        "dividends_paid",
                        "share_repurchases",
                    }
                    else "income"
                )
                fin.append(_obs(iid, pe, st, name, val, pub))
            stocks: dict[str, float] = {
                "cash": rev * 0.3,
                "interest_bearing_debt": te * 0.05,
                "accounts_receivable": rev * 0.05,
                "inventory": 0.0,
                "accounts_payable": rev * 0.02,
                "total_liabilities": te * 8.0,
                "total_equity": te,
                "total_assets": te * 9.0,
                "minority_interest": mi,
                "goodwill": gw,
            }
            if have_oei and oei_v is not None:
                stocks["other_equity_instruments"] = oei_v
                stocks["preferred_shares"] = oei_v * 0.3
                stocks["perpetual_bond"] = oei_v * 0.7
            for name, val in stocks.items():
                fin.append(_obs(iid, pe, "balance_sheet", name, val, pub))
        mkt: list[MarketObservation] = []
        # Price ~ book/share * pb; start early enough for hist PB depth
        price = max(5.0, (te / shares) * 0.9)
        for y in range(start_year, start_year + n_years + 1):
            for month in range(1, 13):
                if y == start_year + n_years and month > 6:
                    break
                d = date(y, month, calendar.monthrange(y, month)[1])
                price *= float(np.exp(rng.normal(0.004, 0.04)))
                mkt.append(
                    MarketObservation(
                        instrument_id=iid,
                        timestamp=datetime.combine(d, time(15, 0), TZ),
                        raw_close=round(price, 2),
                        adjusted_close=round(price, 4),
                        shares_outstanding=shares,
                        corporate_action_version="none",
                        currency="CNY",
                        source_id=syn.SYNTHETIC_SOURCE,
                    )
                )
        actions = [
            CorporateActionEvent(
                action_id=f"em:{iid.split('.')[0]}:{start_year + 3}-12-31:cash",
                instrument_id=iid,
                action_type="cash_dividend",
                announced_at=datetime(start_year + 4, 5, 1, 18, 0, tzinfo=TZ),
                ex_date=date(start_year + 4, 6, 15),
                cash_per_share=0.15,
                currency="CNY",
                source_id="em_sharebonus",
                revision_id="r0",
            ),
        ]
        cls = [
            InstrumentClassification(
                instrument_id=iid,
                scheme="SW2021_L1",
                industry=bank_label,
                published_at=datetime(start_year, 1, 1, 9, 0, tzinfo=TZ),
                source_id=syn.SYNTHETIC_SOURCE,
            )
        ]
        out[iid] = LoadResult(
            financial=fin,
            market=mkt,
            corporate_actions=actions,
            classifications=cls,
            sources={syn.SYNTHETIC_SOURCE: src},
            corporate_actions_provided=True,
            sources_provided=True,
        )
    return out


def lean_curated_ids() -> tuple[str, ...]:
    return LEAN_CURATED_DEPOSIT_TAKING_FI


def bank_panel_meta(*, short_oei_ids: frozenset[str] | None = None) -> dict[str, Any]:
    short = short_oei_ids if short_oei_ids is not None else frozenset({"000001.SZ"})
    return {
        "panel_kind": "bank_fi_synthetic",
        "short_oei_ids": sorted(short),
        "track_b_note": (
            "Instruments in short_oei_ids have OEI history too short for "
            "MIN_HIST_PB_POINTS=12 → Track B must SKIP (no invent OEI)."
        ),
        "lean_curated_ref": "LEAN_CURATED_DEPOSIT_TAKING_FI",
    }


__all__ = [
    "DEFAULT_BANK_PANEL_IDS",
    "bank_panel_meta",
    "generate_bank_eval_panel",
    "lean_curated_ids",
]
