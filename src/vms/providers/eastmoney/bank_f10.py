"""Eastmoney PC_HSF10 NewFinanceAnalysis (companyType=3) → canonical observations (EM-FI-F10-v1).

Endpoint family:
  PC_HSF10/NewFinanceAnalysis/{zcfzb,lrb,xjllb}AjaxNew
  PC_HSF10/NewFinanceAnalysis/{zcfzb,lrb}DateAjaxNew for available REPORT_DATEs.

published_at = NOTICE_DATE @ 15:00 Asia/Shanghai (never invent from REPORT_DATE).
Does **not** re-emit total_equity / parent_net_income (avoid source conflict with HiThink).
Maps only R2 deposit-taking FI lines: OEI, preferred, perpetual, minority, goodwill,
OCI, EPS, interest.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from vms.schemas.fields import get_field
from vms.schemas.observations import FinancialObservation

TZ = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "em_bank_f10"

# Balance (zcfzb) — stocks
BS_MAP: dict[str, str] = {
    "OTHER_EQUITY_TOOL": "other_equity_instruments",
    "PREFERRED_SHARES": "preferred_shares",
    "PERPETUAL_BOND": "perpetual_bond",
    "MINORITY_EQUITY": "minority_interest",
    "GOODWILL": "goodwill",
    "TOTAL_PARENT_EQUITY": "parent_equity",
}

# Income (lrb) — flows / per-share
IS_MAP: dict[str, str] = {
    "PARENT_OCI": "other_comprehensive_income",
    "BASIC_EPS": "basic_eps",
    "INTEREST_INCOME": "interest_income",
    "INTEREST_NI": "interest_net_income",
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


def map_bank_f10_rows(
    *,
    balance_rows: list[dict[str, Any]] | None = None,
    income_rows: list[dict[str, Any]] | None = None,
    instrument_id: str,
    source_id: str = SOURCE_ID,
    annual_only: bool = True,
) -> tuple[list[FinancialObservation], dict[str, int]]:
    """Map companyType=3 F10 rows to FinancialObservation list (NOTICE-aligned)."""
    out: list[FinancialObservation] = []
    stats = {
        "balance_rows": len(balance_rows or []),
        "income_rows": len(income_rows or []),
        "mapped": 0,
        "skipped_no_notice": 0,
        "skipped_non_annual": 0,
        "null_fields": 0,
    }
    now = datetime.now(TZ)

    def _emit(rows: list[dict[str, Any]] | None, fmap: dict[str, str]) -> None:
        if not rows:
            return
        for r in rows:
            pe = _parse_date(r.get("REPORT_DATE") or r.get("report_date"))
            notice = _parse_date(r.get("NOTICE_DATE") or r.get("notice_date"))
            if pe is None:
                continue
            if annual_only and (pe.month, pe.day) != (12, 31):
                stats["skipped_non_annual"] += 1
                continue
            if notice is None:
                stats["skipped_no_notice"] += 1
                continue
            pub = notice_at_1500(notice)
            for col, field in fmap.items():
                raw = r.get(col)
                if raw is None and col.lower() in r:
                    raw = r.get(col.lower())
                val = _as_float(raw)
                if val is None:
                    stats["null_fields"] += 1
                    continue
                fdef = get_field(field)
                if fdef is None:
                    continue
                out.append(
                    FinancialObservation(
                        instrument_id=instrument_id,
                        period_end=pe,
                        published_at=pub,
                        ingested_at=now,
                        statement_type=fdef.statement_type,
                        field_name=field,
                        value=val,
                        currency="CNY",
                        unit_scale="unit",
                        source_id=source_id,
                        revision_id=f"published_at_source=eastmoney_notice_date;em_col={col}",
                        quality_status="observed",
                    )
                )
                stats["mapped"] += 1

    _emit(balance_rows, BS_MAP)
    _emit(income_rows, IS_MAP)
    return out, stats
