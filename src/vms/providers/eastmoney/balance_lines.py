"""Eastmoney RPT_DMSK_FN_BALANCE → inventory / accounts_payable (EM-BS-LINES-v1).

HiThink local balance_sheets lacks inventory and payables. EM datacenter reports
those lines with NOTICE_DATE. For published_at we prefer the same EM earnings
NOTICE already used for HiThink statements (HITHINK-PIT-NOTICE-v1), because the
balance-report NOTICE_DATE often tracks later amendments (LATEST_ONLY). Values
may still be restated — snapshots stay pit_complete=false.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from vms.schemas.observations import FinancialObservation

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "em_dmsk_balance"
# DATE_TYPE_CODE: 001 annual, 002 H1, 003 Q1, 004 Q3 (observed on A-share samples)
FIELD_MAP = {
    "INVENTORY": "inventory",
    "ACCOUNTS_PAYABLE": "accounts_payable",
}


def _parse_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan", "nat", "--", "-"):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _as_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def notice_at_1500(d: date) -> datetime:
    return datetime.combine(d, time(15, 0), tzinfo=TZ)


def map_balance_line_rows(
    rows: list[dict[str, Any]],
    *,
    instrument_id: str,
    notice_by_period_end: dict[date, date] | None = None,
    source_id: str = SOURCE_ID,
) -> tuple[list[FinancialObservation], dict[str, int]]:
    """Map EM balance rows to FinancialObservation stocks.

    published_at priority:
      1. earnings NOTICE for same period_end (if provided)
      2. row NOTICE_DATE @ 15:00 Asia/Shanghai
    Rows without any publish date are skipped (never invent from REPORT_DATE).
    """
    notice_by_period_end = notice_by_period_end or {}
    out: list[FinancialObservation] = []
    stats = {
        "rows": len(rows),
        "mapped": 0,
        "skipped_no_publish": 0,
        "used_earnings_notice": 0,
        "used_balance_notice": 0,
        "null_fields": 0,
    }
    now = datetime.now(TZ)
    for r in rows:
        pe = _parse_date(r.get("REPORT_DATE") or r.get("report_date"))
        if pe is None:
            continue
        bal_n = _parse_date(r.get("NOTICE_DATE") or r.get("notice_date"))
        earn_n = notice_by_period_end.get(pe)
        if earn_n is not None:
            pub = notice_at_1500(earn_n)
            pub_src = "eastmoney_notice_date"
            stats["used_earnings_notice"] += 1
            if bal_n is not None and bal_n > earn_n:
                rev = f"em_balance_notice_later={bal_n.isoformat()};published_at_source={pub_src}"
            else:
                rev = f"published_at_source={pub_src}"
        elif bal_n is not None:
            pub = notice_at_1500(bal_n)
            pub_src = "em_balance_notice_date"
            stats["used_balance_notice"] += 1
            rev = f"published_at_source={pub_src}"
        else:
            stats["skipped_no_publish"] += 1
            continue
        date_type = str(r.get("DATE_TYPE_CODE") or r.get("date_type_code") or "")
        for col, field in FIELD_MAP.items():
            raw = r.get(col)
            if raw is None and col.lower() in r:
                raw = r.get(col.lower())
            val = _as_float(raw)
            if val is None:
                stats["null_fields"] += 1
                continue
            out.append(
                FinancialObservation(
                    instrument_id=instrument_id,
                    period_end=pe,
                    published_at=pub,
                    ingested_at=now,
                    statement_type="balance_sheet",
                    field_name=field,
                    value=val,
                    currency="CNY",
                    unit_scale="unit",
                    source_id=source_id,
                    revision_id=f"{rev};date_type={date_type}" if date_type else rev,
                    quality_status="observed",
                )
            )
            stats["mapped"] += 1
    return out, stats
