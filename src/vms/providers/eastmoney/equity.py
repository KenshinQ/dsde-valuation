"""Eastmoney RPT_F10_EH_EQUITY → shares outstanding as-of NOTICE_DATE (EM-SHARES-EQUITY-v1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from vms.schemas.observations import MarketObservation


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    # pandas NaT / NA
    try:
        import pandas as pd  # optional
        if v is pd.NaT or (isinstance(v, float) and v != v):
            return None
    except Exception:
        if isinstance(v, float) and v != v:
            return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    # pandas Timestamp duck-typing
    if hasattr(v, "to_pydatetime"):
        try:
            return v.to_pydatetime().date()
        except Exception:
            return None
    if hasattr(v, "date") and callable(v.date):
        try:
            d = v.date()
            return d if isinstance(d, date) else None
        except Exception:
            return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "nat", "null"):
        return None
    return date.fromisoformat(s[:10])


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    return f


def equity_share_timeline(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    """Return sorted (notice_date, total_shares) known-at points (PIT publish = NOTICE_DATE)."""
    pts: list[tuple[date, float]] = []
    for r in rows:
        nd = _as_date(r.get("NOTICE_DATE") or r.get("notice_date"))
        shares = _as_float(r.get("TOTAL_SHARES") or r.get("total_shares")
                           or r.get("TOTAL_A_SHARES") or r.get("total_a_shares"))
        if nd is None or shares is None:
            continue
        pts.append((nd, shares))
    pts.sort(key=lambda x: x[0])
    # de-dup same notice_date: keep last
    out: list[tuple[date, float]] = []
    for nd, sh in pts:
        if out and out[-1][0] == nd:
            out[-1] = (nd, sh)
        else:
            out.append((nd, sh))
    return out


def shares_known_at(timeline: list[tuple[date, float]], as_of_date: date) -> float | None:
    """Latest TOTAL_SHARES with notice_date <= as_of_date."""
    cur: float | None = None
    for nd, sh in timeline:
        if nd <= as_of_date:
            cur = sh
        else:
            break
    return cur


def apply_shares_to_market(
    market: list[MarketObservation],
    timeline: list[tuple[date, float]],
) -> list[MarketObservation]:
    """Stamp shares_outstanding on each bar when a NOTICE_DATE <= bar date is known."""
    if not timeline:
        return market
    out: list[MarketObservation] = []
    for m in market:
        sh = shares_known_at(timeline, m.timestamp.date())
        if sh is None:
            out.append(m)
        else:
            out.append(m.model_copy(update={"shares_outstanding": sh}))
    return out
