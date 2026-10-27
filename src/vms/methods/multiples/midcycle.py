"""Skeleton mid-cycle earnings/CF estimator (SPEC §12.6).

PIT series → mid_cycle_denominator | None + confidence + diagnostics.
Incomplete / short / missing series → None + LOW (no invent).
HIGH only under explicit completeness rules below.
Optional sector-prior stub is research-only / LOW and never silent-fills.
Orthogonal to ``vms.regimes`` and Track B hist P/B.
Label: INVESTMENT_VALUE_NOT_ESTABLISHED. Not ensemble-calibrated.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from statistics import median
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

# Explicit completeness rules for HIGH (skeleton; not a full cycle model).
MIN_COMPLETE_POINTS = 7
MIN_COMPLETE_SPAN_YEARS = 6.0
# Peak/trough: require max > median and min < median (strict inequality).
# Research-only sector prior never elevates confidence above LOW.


class MidCycleConfidence(str, Enum):
    """Confidence for a mid-cycle estimate. Default / incomplete → LOW."""

    LOW = "LOW"
    HIGH = "HIGH"


class MidCycleEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mid_cycle_denominator: float | None
    confidence: MidCycleConfidence = MidCycleConfidence.LOW
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _parse_as_of(as_of: date | datetime | str | None) -> date | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    s = str(as_of).strip()
    if not s:
        return None
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return date.fromisoformat(s[:10])
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def _coerce_point(raw: Any) -> tuple[date | None, float] | None:
    """Accept (date|str, value), mapping with period_end/as_of/value, or bare number."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        v = float(raw)
        if v != v:  # NaN
            return None
        return (None, v)
    if isinstance(raw, Mapping):
        val = raw.get("value", raw.get("v"))
        if val is None:
            return None
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        if v != v:
            return None
        d_raw = raw.get("period_end", raw.get("as_of", raw.get("date")))
        return (_parse_as_of(d_raw) if d_raw is not None else None, v)
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        d = _parse_as_of(raw[0]) if raw[0] is not None else None
        try:
            v = float(raw[1])
        except (TypeError, ValueError):
            return None
        if v != v:
            return None
        return (d, v)
    return None


def _span_years(dates: list[date]) -> float | None:
    if len(dates) < 2:
        return None
    delta = max(dates) - min(dates)
    return delta.days / 365.25


def estimate_mid_cycle_denominator(
    series: Sequence[Any] | None,
    *,
    as_of: date | datetime | str | None = None,
    sector_prior: float | None = None,
    use_sector_prior_stub: bool = False,
) -> MidCycleEstimate:
    """Estimate a mid-cycle denominator from a PIT earnings/CF series.

    Parameters
    ----------
    series:
        PIT-dated observations (mappings / (date, value) / bare floats). Future
        points relative to ``as_of`` are dropped when dates are present.
    as_of:
        Valuation as-of; used only to drop post-as_of points (PIT).
    sector_prior:
        Optional research-only prior. Applied only when ``use_sector_prior_stub``
        is True; always LOW confidence; never silent fill when stub is off.
    use_sector_prior_stub:
        Explicit opt-in for the research-only prior path.

    Returns
    -------
    MidCycleEstimate
        ``mid_cycle_denominator`` is None + LOW when incomplete; finite + HIGH
        only when explicit completeness rules pass. Never invents a denom.
    """
    reason_codes: list[str] = []
    as_of_d = _parse_as_of(as_of)

    if series is None:
        reason_codes.append("SERIES_MISSING")
        return _low(None, reason_codes, n_points=0, n_usable=0)

    points: list[tuple[date | None, float]] = []
    for raw in series:
        coerced = _coerce_point(raw)
        if coerced is None:
            continue
        d, v = coerced
        if as_of_d is not None and d is not None and d > as_of_d:
            reason_codes.append("PIT_DROPPED_POST_ASOF")
            continue
        points.append((d, v))

    n_points = len(points)
    values = [v for _, v in points]
    dated = [d for d, _ in points if d is not None]
    span = _span_years(dated) if dated else None

    if n_points == 0:
        reason_codes.append("SERIES_EMPTY_OR_UNUSABLE")
        return _maybe_prior_or_low(
            reason_codes,
            n_points=0,
            n_usable=0,
            span=span,
            sector_prior=sector_prior,
            use_sector_prior_stub=use_sector_prior_stub,
        )

    peak = max(values)
    trough = min(values)
    med = float(median(values))
    peak_detected = peak > med
    trough_detected = trough < med

    diagnostics_base: dict[str, Any] = {
        "n_points": n_points,
        "n_usable": n_points,
        "window_span_years": span,
        "peak_value": peak,
        "trough_value": trough,
        "peak_detected": peak_detected,
        "trough_detected": trough_detected,
        "median_value": med,
        "estimator": "median_of_pit_series_skel",
        "assumption_ids": ["CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1", "CYCLE-NORMALIZE-FLAG-v1"],
        "sector_prior_applied": False,
        "research_only": False,
        "min_complete_points": MIN_COMPLETE_POINTS,
        "min_complete_span_years": MIN_COMPLETE_SPAN_YEARS,
    }

    incomplete = False
    if n_points < MIN_COMPLETE_POINTS:
        reason_codes.append("SERIES_TOO_SHORT")
        incomplete = True
    if span is None or span < MIN_COMPLETE_SPAN_YEARS:
        reason_codes.append("SERIES_SPAN_INSUFFICIENT")
        incomplete = True
    if not (peak_detected and trough_detected):
        reason_codes.append("PEAK_TROUGH_NOT_DETECTABLE")
        incomplete = True

    if incomplete:
        return _maybe_prior_or_low(
            reason_codes,
            n_points=n_points,
            n_usable=n_points,
            span=span,
            sector_prior=sector_prior,
            use_sector_prior_stub=use_sector_prior_stub,
            extra=diagnostics_base,
        )

    reason_codes.append("COMPLETE_CYCLE_RULES_PASSED")
    diagnostics_base["reason_codes"] = sorted(set(reason_codes))
    return MidCycleEstimate(
        mid_cycle_denominator=med,
        confidence=MidCycleConfidence.HIGH,
        diagnostics=diagnostics_base,
    )


def _low(
    denom: float | None,
    reason_codes: list[str],
    *,
    n_points: int,
    n_usable: int,
    span: float | None = None,
    extra: dict[str, Any] | None = None,
    sector_prior_applied: bool = False,
    research_only: bool = False,
) -> MidCycleEstimate:
    diag: dict[str, Any] = {
        "n_points": n_points,
        "n_usable": n_usable,
        "window_span_years": span,
        "peak_value": None,
        "trough_value": None,
        "peak_detected": False,
        "trough_detected": False,
        "estimator": "median_of_pit_series_skel",
        "assumption_ids": ["CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1", "CYCLE-NORMALIZE-FLAG-v1"],
        "sector_prior_applied": sector_prior_applied,
        "research_only": research_only,
        "min_complete_points": MIN_COMPLETE_POINTS,
        "min_complete_span_years": MIN_COMPLETE_SPAN_YEARS,
        "reason_codes": sorted(set(reason_codes)),
    }
    if extra:
        for k, v in extra.items():
            if k == "reason_codes":
                continue
            diag[k] = v
        diag["reason_codes"] = sorted(set(reason_codes))
        diag["sector_prior_applied"] = sector_prior_applied
        diag["research_only"] = research_only
    return MidCycleEstimate(
        mid_cycle_denominator=denom,
        confidence=MidCycleConfidence.LOW,
        diagnostics=diag,
    )


def _maybe_prior_or_low(
    reason_codes: list[str],
    *,
    n_points: int,
    n_usable: int,
    span: float | None,
    sector_prior: float | None,
    use_sector_prior_stub: bool,
    extra: dict[str, Any] | None = None,
) -> MidCycleEstimate:
    """Sector prior only when explicitly opted in; always LOW / research-only."""
    if use_sector_prior_stub and sector_prior is not None:
        try:
            prior = float(sector_prior)
        except (TypeError, ValueError):
            prior = None
        if prior is not None and prior == prior and prior > 0:
            codes = list(reason_codes) + ["SECTOR_PRIOR_STUB_RESEARCH_ONLY"]
            return _low(
                prior,
                codes,
                n_points=n_points,
                n_usable=n_usable,
                span=span,
                extra=extra,
                sector_prior_applied=True,
                research_only=True,
            )
        reason_codes = list(reason_codes) + ["SECTOR_PRIOR_STUB_INVALID"]
    elif sector_prior is not None and not use_sector_prior_stub:
        reason_codes = list(reason_codes) + ["SECTOR_PRIOR_PRESENT_BUT_STUB_OFF"]
    return _low(
        None,
        reason_codes,
        n_points=n_points,
        n_usable=n_usable,
        span=span,
        extra=extra,
    )
