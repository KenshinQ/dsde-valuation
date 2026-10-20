"""Map Eastmoney RPT_SHAREBONUS_DET → CorporateActionEvent (EM-CA-SHAREBONUS-v1).

PRETAX_BONUS_RMB / BONUS_* ratios are **per 10 shares** (A-share convention in EM UI).
announced_at = PLAN_NOTICE_DATE @ 15:00 Asia/Shanghai when present, else NOTICE_DATE.
Never invent announced_at from EX_DIVIDEND_DATE. Rows without announce + ex_date are skipped.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from vms.schemas.observations import CorporateActionEvent

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "em_sharebonus"


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
    if f != f:  # NaN
        return None
    return f


def _announce_at(plan: date | None, notice: date | None) -> datetime | None:
    d = plan or notice
    if d is None:
        return None
    return datetime.combine(d, time(15, 0), tzinfo=TZ)


def _bonus_per_10(row: dict[str, Any]) -> float:
    """Total 送+转 shares per 10 shares."""
    for key in ("BONUS_IT_RATIO", "bonus_it_ratio"):
        v = _as_float(row.get(key))
        if v is not None and v > 0:
            return v
    bonus = _as_float(row.get("BONUS_RATIO") or row.get("bonus_ratio")) or 0.0
    transfer = (
        _as_float(row.get("TRANSFER_IT_RATIO") or row.get("transfer_it_ratio"))
        or _as_float(row.get("IT_RATIO") or row.get("it_ratio"))
        or 0.0
    )
    # When BONUS_RATIO is 送 and IT_RATIO is 转 (see 000002 10送1转4)
    if bonus > 0 and transfer > 0 and abs(bonus + transfer - (_as_float(row.get("BONUS_IT_RATIO")) or -1)) > 0.01:
        # prefer sum if BONUS_IT_RATIO missing
        return bonus + transfer
    if bonus > 0 and transfer > 0:
        return bonus + transfer
    return max(bonus, transfer, 0.0)


def map_sharebonus_row(
    row: dict[str, Any],
    *,
    instrument_id: str,
    source_id: str = SOURCE_ID,
) -> list[CorporateActionEvent]:
    """Map one EM sharebonus row to 0–2 CorporateActionEvents (cash and/or bonus_share)."""
    plan = _as_date(row.get("PLAN_NOTICE_DATE") or row.get("plan_notice_date"))
    notice = _as_date(row.get("NOTICE_DATE") or row.get("notice_date"))
    ex = _as_date(row.get("EX_DIVIDEND_DATE") or row.get("ex_dividend_date"))
    announced = _announce_at(plan, notice)
    if announced is None or ex is None:
        return []
    if ex < announced.date():
        return []

    report = _as_date(row.get("REPORT_DATE") or row.get("report_date"))
    report_s = report.isoformat() if report else "unknown"
    code = str(row.get("SECURITY_CODE") or row.get("security_code") or instrument_id.split(".", 1)[0])

    cash_per_10 = _as_float(row.get("PRETAX_BONUS_RMB") or row.get("pretax_bonus_rmb"))
    cash_ps = (cash_per_10 / 10.0) if cash_per_10 is not None and cash_per_10 > 0 else None
    bonus_10 = _bonus_per_10(row)
    share_ratio = (1.0 + bonus_10 / 10.0) if bonus_10 > 0 else None

    # revision: if NOTICE later than PLAN, prefer NOTICE as revision stamp when both present
    rev = None
    if plan and notice and notice > plan:
        rev = f"notice={notice.isoformat()}"

    out: list[CorporateActionEvent] = []
    if cash_ps is not None:
        out.append(CorporateActionEvent(
            action_id=f"em:{code}:{report_s}:cash",
            instrument_id=instrument_id,
            action_type="cash_dividend",
            announced_at=announced,
            ex_date=ex,
            share_ratio=None,
            cash_per_share=cash_ps,
            currency="CNY",
            source_id=source_id,
            revision_id=rev,
        ))
    if share_ratio is not None and share_ratio != 1.0:
        out.append(CorporateActionEvent(
            action_id=f"em:{code}:{report_s}:bonus",
            instrument_id=instrument_id,
            action_type="bonus_share",
            announced_at=announced,
            ex_date=ex,
            share_ratio=share_ratio,
            cash_per_share=None,
            currency="CNY",
            source_id=source_id,
            revision_id=rev,
        ))
    return out


def map_sharebonus_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: str,
    source_id: str = SOURCE_ID,
) -> tuple[list[CorporateActionEvent], dict[str, int]]:
    events: list[CorporateActionEvent] = []
    stats = {"rows": len(rows), "mapped": 0, "skipped_no_announce_or_ex": 0, "skipped_ex_before_announce": 0}
    for r in rows:
        plan = _as_date(r.get("PLAN_NOTICE_DATE") or r.get("plan_notice_date"))
        notice = _as_date(r.get("NOTICE_DATE") or r.get("notice_date"))
        ex = _as_date(r.get("EX_DIVIDEND_DATE") or r.get("ex_dividend_date"))
        if (plan is None and notice is None) or ex is None:
            stats["skipped_no_announce_or_ex"] += 1
            continue
        announced = _announce_at(plan, notice)
        assert announced is not None
        if ex < announced.date():
            stats["skipped_ex_before_announce"] += 1
            continue
        evs = map_sharebonus_row(r, instrument_id=instrument_id, source_id=source_id)
        if evs:
            stats["mapped"] += 1
            events.extend(evs)
        else:
            stats["skipped_no_announce_or_ex"] += 1
    return events, stats
