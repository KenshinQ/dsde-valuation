"""Chronological walk-forward protocol helpers (SPEC §15.1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from vms.data.io import LoadResult
from vms.evaluation.errors import RandomSplitProhibitedError
from vms.pit.snapshot import PITSnapshot, build_snapshot
from vms.quality.report import assess

SplitMode = Literal["chronological"]
ALLOWED_SPLIT_MODES: tuple[str, ...] = ("chronological",)


def require_chronological(split_mode: str) -> None:
    if split_mode not in ALLOWED_SPLIT_MODES:
        raise RandomSplitProhibitedError(split_mode)


def enumerate_fy_origins(load: LoadResult, *, instrument_id: str, start: date, end: date,
                         min_history_years: int = 3) -> list[tuple[int, datetime]]:
    """Return (fy_year, origin_as_of) chronologically for FY revenue first-publication times in [start, end].

    origin_as_of = first published_at of FY revenue for that year (when FY became known).
    Requires at least ``min_history_years`` prior FYs visible in the full load for training.
    """
    fins = [f for f in load.financial if f.instrument_id == instrument_id
            and f.field_name == "revenue" and f.period_end.month == 12 and f.period_end.day == 31
            and f.value is not None]
    by_year: dict[int, datetime] = {}
    for f in fins:
        y = f.period_end.year
        first = f.published_at
        if first is None:
            continue
        if y not in by_year or first < by_year[y]:
            by_year[y] = first
    years = sorted(by_year)
    out: list[tuple[int, datetime]] = []
    for i, y in enumerate(years):
        origin = by_year[y]
        if origin.date() < start or origin.date() > end:
            continue
        # need prior history
        prior = [yy for yy in years if yy < y]
        if len(prior) < min_history_years:
            continue
        out.append((y, origin))
    return out  # already chronological by year order


def reconstruct_pit(load: LoadResult, *, instrument_id: str, as_of: datetime, cfg_quality):
    """Rebuild the information set available at ``as_of`` (past-only)."""
    return assess(load, instrument_id=instrument_id, as_of=as_of, cfg=cfg_quality, mode="exploratory",
                  override_reason="phase9_walk_forward_origin")
