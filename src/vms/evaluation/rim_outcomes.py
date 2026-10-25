"""Realize deposit-taking FI RIM outcomes AFTER forecast persist (SPEC §17.1 step 4).

Driver ROE and later-origin intrinsic VPS are scored separately from market
price. Market price is never used as intrinsic ground truth.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from vms.data.io import LoadResult
from vms.evaluation.outcomes import outcome_as_of
from vms.evaluation.rim_forecast import build_rim_track_a_forecast
from vms.evaluation.protocol import reconstruct_pit
from vms.methods.rim.distribution import historical_common_roe
from vms.quality.report import assess
from vms.schemas.config import LoadedConfig, QualityConfig

TZ = ZoneInfo("Asia/Shanghai")


def _spot(snap) -> float | None:
    if not snap.market:
        return None
    return float(snap.market[-1].raw_close)


def realize_rim_outcomes(
    *,
    load: LoadResult,
    instrument_id: str,
    origin: datetime,
    horizon_years: int,
    entry_price: float,
    evaluation_as_of: datetime,
    quality_cfg: QualityConfig,
    loaded: LoadedConfig,
    origin_vps: float | None,
) -> dict[str, Any]:
    """Extract realized driver / price / TSR and later-origin VPS (stability)."""
    due = outcome_as_of(origin, horizon_years)
    if evaluation_as_of < due:
        return {
            "pending": True,
            "due_as_of": due.isoformat(),
            "evaluation_as_of": evaluation_as_of.isoformat(),
        }

    snap, _report = assess(
        load,
        instrument_id=instrument_id,
        as_of=evaluation_as_of,
        cfg=quality_cfg,
        mode="exploratory",
        override_reason="r6_rim_outcome_realization",
    )

    # Realized next-FY common ROE from hist series whose year == origin FY + horizon
    origin_fy = origin.year - 1 if origin.month < 4 else origin.year
    # Prefer FY of last revenue known at origin
    published_fys = sorted({
        f.period_end.year
        for f in snap.financials
        if f.field_name == "revenue"
        and f.period_end.month == 12
        and f.value_cny is not None
        and f.formula is None
        and f.published_at is not None
        and f.published_at <= origin
    })
    if published_fys:
        origin_fy = published_fys[-1]
    target_fy = origin_fy + horizon_years

    roe_hist = historical_common_roe(snap, zeros_explicit=True)
    realized_roe = None
    for y, r in zip(roe_hist.years, roe_hist.roe):
        if y == target_fy:
            realized_roe = float(r)
            break

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

    # Later-origin intrinsic VPS for stability scoring (not price truth)
    later_vps = None
    later_snap, later_rep = reconstruct_pit(
        load,
        instrument_id=instrument_id,
        as_of=due,
        cfg_quality=quality_cfg,
    )
    later_spot = _spot(later_snap)
    if later_spot is not None and later_spot > 0:
        later_fc = build_rim_track_a_forecast(
            snap=later_snap,
            quality_report=later_rep,
            instrument_id=instrument_id,
            as_of=due,
            loaded=loaded,
            spot=later_spot,
            horizon_years=horizon_years,
        )
        later_vps = (later_fc.get("forecasts") or {}).get("intrinsic_value", {}).get("point")

    return {
        "pending": False,
        "due_as_of": due.isoformat(),
        "evaluation_as_of": evaluation_as_of.isoformat(),
        "target_fy": date(target_fy, 12, 31).isoformat(),
        "driver_roe": {"realized": realized_roe, "target_fy": target_fy},
        "operating_cash_flow": {"fcff_proxy": None, "cfo": None, "note": "FI path; CF not primary"},
        "market_price": {"raw_close": px_h},
        "total_shareholder_return": {
            "realized": realized_tsr,
            "exit_price": px_h,
            "cum_dividends_per_share": div_cash,
            "entry_price": entry_price,
            "dividend_treatment": "DIVIDEND-NO-REINVEST-v1",
        },
        "intrinsic_value": {
            "note": (
                "No market-price truth for intrinsic; scored via stability vs later-origin "
                "RIM VPS only (EVAL-IV-NOT-PRICE-TRUTH-v1)."
            ),
            "realized_price_not_used_as_truth": True,
            "later_origin_vps": later_vps,
            "origin_vps": origin_vps,
        },
    }


__all__ = ["realize_rim_outcomes"]
