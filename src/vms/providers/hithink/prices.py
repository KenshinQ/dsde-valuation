"""OHLCV from marketdb — raw_close only; never vendor qfq into adjusted_close (HITHINK-NO-VENDOR-QFQ-v1)."""

from __future__ import annotations

import importlib

from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vms.providers.hithink.paths import duckdb_available, market_db_path
from vms.schemas.observations import MarketObservation

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "hithink_em_notice"


class PriceFetchError(RuntimeError):
    pass


def read_raw_bars(
    thscode: str,
    *,
    start: date | None = None,
    end: date | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    if not duckdb_available():
        raise PriceFetchError("duckdb not installed; pip install 'dsde-valuation[hithink]'")
    
    path = Path(db_path) if db_path else market_db_path()
    if not path.is_file():
        raise PriceFetchError(f"marketdb not found: {path}")
    con = importlib.import_module("duckdb").connect(str(path), read_only=True)
    try:
        q = """
            SELECT thscode, date, open, high, low, close, volume, turnover, currency, adjusted
            FROM raw_kline_daily
            WHERE thscode = ?
        """
        params: list[Any] = [thscode]
        if start is not None:
            q += " AND date >= ?"
            params.append(start.isoformat())
        if end is not None:
            q += " AND date <= ?"
            params.append(end.isoformat())
        q += " ORDER BY date"
        return con.execute(q, params).fetchdf().to_dict(orient="records")
    finally:
        con.close()


def bars_to_market_obs(
    bars: list[dict[str, Any]],
    *,
    instrument_id: str,
    shares_outstanding: float | None = None,
) -> list[MarketObservation]:
    """Write raw_close; leave adjusted_close null (never vendor forward-adjusted)."""
    out: list[MarketObservation] = []
    for b in bars:
        d = b.get("date")
        if isinstance(d, datetime):
            d = d.date()
        elif isinstance(d, str):
            d = date.fromisoformat(d[:10])
        if not isinstance(d, date):
            continue
        close = b.get("close")
        if close is None:
            continue
        ts = datetime.combine(d, time(15, 0), tzinfo=TZ)
        cur = str(b.get("currency") or "CNY").upper()
        if cur in ("RMB", "¥"):
            cur = "CNY"
        out.append(MarketObservation(
            instrument_id=instrument_id,
            timestamp=ts,
            raw_close=float(close),
            adjusted_close=None,  # HITHINK-NO-VENDOR-QFQ-v1
            shares_outstanding=shares_outstanding,
            currency=cur,
            source_id=SOURCE_ID,
        ))
    return out


def recipe_e_ensure_prices(
    thscode: str,
    *,
    start: date,
    end: date,
    prefer_local: bool = True,
    lab_prices: Any | None = None,
) -> dict[str, Any]:
    """Local marketdb first; on miss, one HiThink REST upsert via lab lib_prices (Recipe E).

    Does not silently switch vendors. Returns diagnostics (no secrets).
    """
    bars = read_raw_bars(thscode, start=start, end=end)
    diag: dict[str, Any] = {
        "local_bars": len(bars),
        "prefer_local": prefer_local,
        "rest_used": False,
        "source": "marketdb_raw_kline_daily",
    }
    if prefer_local and bars:
        # Coverage check: last bar date >= end - small tolerance (weekends)
        last = bars[-1]["date"]
        if isinstance(last, datetime):
            last = last.date()
        elif isinstance(last, str):
            last = date.fromisoformat(last[:10])
        if isinstance(last, date) and last >= end:
            return {**diag, "bars": bars}
        # partial coverage — still try Recipe E if not prefer-only-enough
    if prefer_local and bars and len(bars) >= 5:
        # Accept partial local without REST when prefer_local and some history exists,
        # unless force refresh path (prefer_local False).
        return {**diag, "bars": bars}

    if lab_prices is None:
        return {**diag, "bars": bars, "note": "lab_prices unavailable; returning local only"}

    # Recipe E: lab get_forward_closes does REST upsert of raw then re-read forward;
    # we re-read RAW ourselves so adjusted_close stays null.
    try:
        lab_prices.get_forward_closes(
            thscode, start, end, prefer_local=prefer_local, force_rest=not prefer_local,
        )
        diag["rest_used"] = True
        diag["source"] = "marketdb_after_rest_upsert"
    except Exception as e:  # noqa: BLE001
        diag["rest_error"] = f"{type(e).__name__}: {str(e)[:160]}"
    bars2 = read_raw_bars(thscode, start=start, end=end)
    diag["local_bars_after"] = len(bars2)
    return {**diag, "bars": bars2}
