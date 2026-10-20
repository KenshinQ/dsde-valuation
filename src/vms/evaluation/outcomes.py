"""Realize outcomes ONLY after the forecast horizon has elapsed (SPEC §15.1 step 4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from vms.data.io import LoadResult
from vms.quality.report import assess
from vms.schemas.config import QualityConfig

TZ = ZoneInfo("Asia/Shanghai")


def outcome_as_of(origin: datetime, horizon_years: int) -> datetime:
    """First moment after horizon years from origin (calendar year shift, 15:00 Asia/Shanghai)."""
    d = date(origin.year + horizon_years, origin.month, min(origin.day, 28))
    return datetime(d.year, d.month, d.day, 15, 0, tzinfo=TZ)


def realize_outcomes(*, load: LoadResult, instrument_id: str, origin: datetime, horizon_years: int,
                     entry_price: float, evaluation_as_of: datetime,
                     quality_cfg: QualityConfig) -> dict[str, Any]:
    """Extract realized CF / price / TSR using only information known by ``evaluation_as_of``."""
    due = outcome_as_of(origin, horizon_years)
    if evaluation_as_of < due:
        return {"pending": True, "due_as_of": due.isoformat(), "evaluation_as_of": evaluation_as_of.isoformat()}

    snap, _report = assess(load, instrument_id=instrument_id, as_of=evaluation_as_of, cfg=quality_cfg,
                           mode="exploratory", override_reason="phase9_outcome_realization")

    published_fys = sorted({
        f.period_end for f in snap.financials
        if f.field_name == "revenue" and f.period_end.month == 12 and f.value_cny is not None
        and f.formula is None and f.published_at <= origin
    })
    target_fy = date(published_fys[-1].year + horizon_years, 12, 31) if published_fys else None

    realized_fcff = None
    realized_cfo = None
    if target_fy is not None:
        def _val(name: str) -> float | None:
            recs = [f for f in snap.financials
                    if f.field_name == name and f.period_end == target_fy and f.value_cny is not None
                    and f.formula is None]
            return float(recs[-1].value_cny) if recs else None
        cfo = _val("cash_flow_from_operations")
        capex = _val("capex") or 0.0
        acq = _val("acquisitions_net") or 0.0
        realized_cfo = cfo
        if cfo is not None:
            realized_fcff = cfo - capex - acq

    mkt = [m for m in snap.market if m.timestamp <= due]
    px_h = float(mkt[-1].raw_close) if mkt else None
    div_cash = 0.0
    for sa in snap.corporate_actions:
        a = sa.event
        if a.action_type == "cash_dividend" and a.ex_date and origin.date() < a.ex_date <= due.date():
            if a.cash_per_share:
                div_cash += float(a.cash_per_share)
    realized_tsr = None
    if px_h is not None and entry_price > 0:
        realized_tsr = (px_h + div_cash - entry_price) / entry_price

    return {
        "pending": False,
        "due_as_of": due.isoformat(),
        "evaluation_as_of": evaluation_as_of.isoformat(),
        "target_fy": None if target_fy is None else target_fy.isoformat(),
        "operating_cash_flow": {"fcff_proxy": realized_fcff, "cfo": realized_cfo},
        "market_price": {"raw_close": px_h},
        "total_shareholder_return": {
            "realized": realized_tsr, "exit_price": px_h, "cum_dividends_per_share": div_cash,
            "entry_price": entry_price, "dividend_treatment": "DIVIDEND-NO-REINVEST-v1",
        },
        "intrinsic_value": {
            "note": "No market-price truth for intrinsic; scored via stability/coherence only, never price MAE alone",
            "realized_price_not_used_as_truth": True,
            "later_origin_vps": None,
        },
    }
