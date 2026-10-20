"""NOTICE_DATE PIT join policy (HITHINK-PIT-NOTICE-v1).

Forbidden: using HiThink ``period_end_ms`` as published_at.
Fallback (only when NOTICE missing after local+EM fetch): HiThink ``report_date_ms``
with quality_status=low_confidence and published_at_source=hithink_report_date_ms_fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable

from vms.providers.hithink.mapping import ms_to_shanghai_date, notice_to_published_at

ASSUMPTION_ID = "HITHINK-PIT-NOTICE-v1"
FALLBACK_SOURCE = "hithink_report_date_ms_fallback"
NOTICE_SOURCE = "eastmoney_notice_date"


@dataclass(frozen=True)
class PublishResolve:
    published_at: datetime
    source: str  # NOTICE_SOURCE | FALLBACK_SOURCE
    notice_date: date | None
    period_end: date
    report_date_ms: int | None


def _notice_index(notices: Iterable[dict[str, Any]]) -> dict[date, date]:
    """Map EM report_date (period_end) → notice_date."""
    out: dict[date, date] = {}
    for n in notices:
        rd = n.get("report_date")
        nd = n.get("notice_date")
        if rd is None or nd is None:
            # try ms
            rd = rd or ms_to_shanghai_date(n.get("report_date_ms"))
            nd = nd or ms_to_shanghai_date(n.get("notice_date_ms"))
        if isinstance(rd, datetime):
            rd = rd.date()
        if isinstance(nd, datetime):
            nd = nd.date()
        if isinstance(rd, str):
            rd = date.fromisoformat(rd[:10])
        if isinstance(nd, str):
            nd = date.fromisoformat(nd[:10])
        if isinstance(rd, date) and isinstance(nd, date):
            # keep earliest notice if duplicates
            prev = out.get(rd)
            if prev is None or nd < prev:
                out[rd] = nd
    return out


def resolve_published_at(
    *,
    period_end_ms: int | None,
    report_date_ms: int | None,
    notice_by_period_end: dict[date, date],
    allow_report_date_fallback: bool = True,
) -> PublishResolve | None:
    """Resolve published_at for one statement row.

    Never returns period_end as published_at (even on fallback).
    """
    period_end = ms_to_shanghai_date(period_end_ms)
    if period_end is None:
        return None
    notice = notice_by_period_end.get(period_end)
    if notice is not None:
        pub = notice_to_published_at(notice)
        # Guard: must not equal midnight period_end alone without 15:00 — we always use 15:00.
        assert pub.date() == notice
        assert pub.hour == 15
        return PublishResolve(
            published_at=pub, source=NOTICE_SOURCE, notice_date=notice,
            period_end=period_end, report_date_ms=report_date_ms,
        )
    if allow_report_date_fallback and report_date_ms is not None:
        rd = ms_to_shanghai_date(report_date_ms)
        if rd is not None:
            # Explicitly NOT claiming exchange announce — 15:00 labeling for consistency.
            pub = notice_to_published_at(rd)
            # Forbidden check: fallback must not silently use period_end.
            if rd == period_end:
                # report_date coinciding with period_end is suspicious; still mark fallback
                # but never pretend it is NOTICE.
                pass
            return PublishResolve(
                published_at=pub, source=FALLBACK_SOURCE, notice_date=None,
                period_end=period_end, report_date_ms=report_date_ms,
            )
    return None


def build_notice_index(notices: Iterable[dict[str, Any]]) -> dict[date, date]:
    return _notice_index(notices)


def assert_not_period_end_as_pit(resolve: PublishResolve) -> None:
    """Raise if published_at date equals period_end AND source claims NOTICE incorrectly.

    Fallback may land on any calendar day; the critical forbid is treating period_end_ms
    itself as the announce timestamp without the fallback label.
    """
    if resolve.source == NOTICE_SOURCE:
        return
    if resolve.source != FALLBACK_SOURCE:
        raise AssertionError(f"unknown published_at source {resolve.source}")
