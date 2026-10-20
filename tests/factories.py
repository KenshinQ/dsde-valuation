"""Tiny record factories for crafted Phase-1 fixtures."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from vms.schemas import (CorporateActionEvent, FinancialObservation, MarketObservation, SourceDescriptor)
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
INST = "TST000001.SZ"


def ts(d: str, hh: int = 18) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def fobs(period_end: str, field: str, value, pub: str, *, rev="r0", source="S", currency="CNY",
         unit="unit", status=None, stype=None, hh=18) -> FinancialObservation:
    f = get_field(field)
    return FinancialObservation(
        instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=ts(pub, hh),
        statement_type=stype or (f.statement_type if f else "income"), field_name=field, value=value,
        currency=currency, unit_scale=unit, source_id=source, revision_id=rev if value is not None else None,
        quality_status=status or ("observed" if value is not None else "missing"))


def mobs(d: str, close: float, shares: float | None = 1e9, adj: float | None = None, source="S",
         currency="CNY") -> MarketObservation:
    return MarketObservation(instrument_id=INST, timestamp=ts(d, 15), raw_close=close, adjusted_close=adj,
                             shares_outstanding=shares, currency=currency, source_id=source)


def ca(action_id: str, kind: str, announced: str, ex: str, *, ratio=None, cash=None, rev="r0") -> CorporateActionEvent:
    return CorporateActionEvent(action_id=action_id, instrument_id=INST, action_type=kind, announced_at=ts(announced),
                                ex_date=date.fromisoformat(ex), share_ratio=ratio, cash_per_share=cash,
                                currency="CNY", source_id="S", revision_id=rev)


def src(conv="CN_CUMULATIVE_YTD", versioning="FULL_HISTORY", sid="S") -> SourceDescriptor:
    return SourceDescriptor(source_id=sid, reporting_convention=conv, versioning=versioning)
