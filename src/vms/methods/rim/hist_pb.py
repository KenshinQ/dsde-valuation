"""R2d: subject own historical P/B on common-equity BPS with raw (unadjusted) close.

PIT: only FY points with financial published_at <= as_of and market bar timestamp <= as_of.
Numerator = raw_close (never forward-adjusted / qfq).
Denominator BPS = common_equity / diluted_shares (RIM-COMMON-EQUITY-v1).
Fewer than MIN_HIST_PB_POINTS → caller must mark exit channel UNAVAILABLE (no invent).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Sequence

from vms.assumptions import cite
from vms.drivers.history import extract_annual
from vms.methods.rim.from_snapshot import common_equity_components
from vms.pit.snapshot import PITSnapshot, local_date

MIN_HIST_PB_POINTS = 12
PEER_FIELD_PB_COMMON = "pb_common"


@dataclass(frozen=True)
class HistPbPoint:
    year: int
    period_end: date
    raw_close: float
    common_equity: float
    diluted_shares: float
    bps: float
    pb: float
    market_timestamp: datetime
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class YearFunnelEntry:
    year: int
    status: str  # INCLUDED | SKIP_*
    reason: str | None = None


@dataclass(frozen=True)
class HistPbSeries:
    ok: bool
    ineligible_reason: str | None
    points: list[HistPbPoint]
    flags: list[str]
    assumption_ids: list[str]
    n: int
    median: float | None
    p25: float | None
    p75: float | None
    detail: str = ""
    year_funnel: list[YearFunnelEntry] = field(default_factory=list)


def _raw_close_on_or_before(
    snap: PITSnapshot,
    *,
    on_or_before: date,
    as_of: datetime,
) -> tuple[float | None, datetime | None, list[str]]:
    """Last raw_close with bar local_date <= on_or_before and timestamp <= as_of."""
    flags: list[str] = []
    best = None
    best_ts = None
    for m in snap.market:
        ts = m.timestamp
        if ts > as_of:
            continue
        d = local_date(ts)
        if d > on_or_before:
            continue
        px = float(m.raw_close)
        if not (math.isfinite(px) and px > 0):
            flags.append("SKIP_NONPOSITIVE_RAW_CLOSE")
            continue
        if best_ts is None or ts >= best_ts:
            best = px
            best_ts = ts
    return best, best_ts, flags


def historical_common_pb(
    snap: PITSnapshot,
    *,
    zeros_explicit: bool = True,
    min_points: int = MIN_HIST_PB_POINTS,
) -> HistPbSeries:
    """Build PIT-truncated own P/B series: raw_close / (common_equity / shares) at FY-12-31."""
    aids = cite(
        "RIM-COMMON-EQUITY-v1",
        "RIM-EXIT-OWN-PB-HIST-v1",
        "HITHINK-NO-VENDOR-QFQ-v1",
        "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
    )
    flags: list[str] = ["PB_NUMERATOR_RAW_CLOSE", "PB_DENOMINATOR_COMMON_BPS"]
    h = extract_annual(snap)
    as_of = snap.as_of
    points: list[HistPbPoint] = []
    year_funnel: list[YearFunnelEntry] = []

    for y in h.years:
        be, comps, cflags, err = common_equity_components(
            h, year=y, zeros_explicit=zeros_explicit,
        )
        flags.extend(cflags)
        if err or be is None or be <= 0:
            reason = err or "NONPOSITIVE_COMMON_EQUITY"
            flags.append(f"PB_SKIP_NO_COMMON_EQUITY@{y}:{reason}")
            year_funnel.append(YearFunnelEntry(year=y, status="SKIP_NO_COMMON_EQUITY", reason=reason))
            continue
        sh_pt = h.shares.get(y)
        shares = None if sh_pt is None else sh_pt.value
        if shares is None or not (math.isfinite(shares) and shares > 0):
            flags.append(f"PB_SKIP_NO_SHARES@{y}")
            year_funnel.append(YearFunnelEntry(year=y, status="SKIP_NO_SHARES", reason="MISSING_OR_NONPOSITIVE_SHARES"))
            continue
        pe = date(y, 12, 31)
        px, ts, pflags = _raw_close_on_or_before(snap, on_or_before=pe, as_of=as_of)
        flags.extend(pflags)
        if px is None or ts is None:
            flags.append(f"PB_SKIP_NO_RAW_CLOSE@{y}")
            year_funnel.append(YearFunnelEntry(year=y, status="SKIP_NO_RAW_CLOSE", reason="MISSING_RAW_CLOSE"))
            continue
        bps = float(be) / float(shares)
        if not (math.isfinite(bps) and bps > 0):
            flags.append(f"PB_SKIP_NONPOSITIVE_BPS@{y}")
            year_funnel.append(YearFunnelEntry(year=y, status="SKIP_NONPOSITIVE_BPS", reason="NONPOSITIVE_BPS"))
            continue
        pb = float(px) / bps
        if not (math.isfinite(pb) and pb > 0):
            flags.append(f"PB_SKIP_NONPOSITIVE_PB@{y}")
            year_funnel.append(YearFunnelEntry(year=y, status="SKIP_NONPOSITIVE_PB", reason="NONPOSITIVE_PB"))
            continue
        points.append(
            HistPbPoint(
                year=y,
                period_end=pe,
                raw_close=float(px),
                common_equity=float(be),
                diluted_shares=float(shares),
                bps=bps,
                pb=pb,
                market_timestamp=ts,
                flags=sorted(set(cflags)),
            )
        )
        year_funnel.append(YearFunnelEntry(year=y, status="INCLUDED", reason=None))

    n = len(points)
    pbs = [p.pb for p in points]
    med = float(__import__("numpy").median(pbs)) if pbs else None
    p25 = float(__import__("numpy").quantile(pbs, 0.25)) if pbs else None
    p75 = float(__import__("numpy").quantile(pbs, 0.75)) if pbs else None

    if n < int(min_points):
        return HistPbSeries(
            ok=False,
            ineligible_reason="INSUFFICIENT_OWN_PB_HISTORY",
            points=points,
            flags=sorted(set(flags + ["OWN_PB_HISTORY_UNAVAILABLE", f"N_HIST_PB={n}<{min_points}"])),
            assumption_ids=aids,
            n=n,
            median=med,
            p25=p25,
            p75=p75,
            detail=f"need >={min_points} PIT FY common-P/B points; got {n}",
            year_funnel=year_funnel,
        )
    return HistPbSeries(
        ok=True,
        ineligible_reason=None,
        points=points,
        flags=sorted(set(flags)),
        assumption_ids=aids,
        n=n,
        median=med,
        p25=p25,
        p75=p75,
        detail=f"n={n}; median_pb={med}",
        year_funnel=year_funnel,
    )


def subject_spot_raw_close(snap: PITSnapshot) -> tuple[float | None, list[str]]:
    """Last raw_close at or before as_of."""
    flags: list[str] = []
    best = None
    best_ts = None
    for m in snap.market:
        if m.timestamp > snap.as_of:
            continue
        px = float(m.raw_close)
        if not (math.isfinite(px) and px > 0):
            flags.append("SKIP_NONPOSITIVE_SPOT_RAW_CLOSE")
            continue
        if best_ts is None or m.timestamp >= best_ts:
            best = px
            best_ts = m.timestamp
    if best is None:
        flags.append("MISSING_SPOT_RAW_CLOSE")
    return best, flags


def subject_pb_at_asof(
    *,
    common_equity: float,
    diluted_shares: float,
    raw_close: float,
) -> tuple[float | None, float | None, list[str]]:
    """Subject P/B = raw_close / (common_equity/shares)."""
    flags: list[str] = ["PB_NUMERATOR_RAW_CLOSE", "PB_DENOMINATOR_COMMON_BPS"]
    if not (math.isfinite(common_equity) and common_equity > 0):
        return None, None, flags + ["NONPOSITIVE_COMMON_EQUITY"]
    if not (math.isfinite(diluted_shares) and diluted_shares > 0):
        return None, None, flags + ["NONPOSITIVE_SHARES"]
    if not (math.isfinite(raw_close) and raw_close > 0):
        return None, None, flags + ["NONPOSITIVE_RAW_CLOSE"]
    bps = common_equity / diluted_shares
    pb = raw_close / bps
    return pb, bps, flags
