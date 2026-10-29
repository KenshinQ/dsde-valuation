"""Skeleton mid-cycle earnings/CF estimator (SPEC §12.6).

PIT series → mid_cycle_denominator | None + confidence + diagnostics.
Incomplete / short / missing series → None + LOW (no invent).
HIGH only under explicit completeness rules below.
Optional sector-prior shrink (opt-in stub) is research-only / LOW and never
silent-fills. Incomplete series with sample median > 0 may shrink toward the
prior (``CYCLE-MIDCYCLE-SECTOR-PRIOR-SHRINK-v1``); empty series keeps raw prior
fill. Prior never elevates confidence above LOW. Orthogonal to ``vms.regimes``
and Track B hist P/B. Label: INVESTMENT_VALUE_NOT_ESTABLISHED. Not
ensemble-calibrated.
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
# Peak/trough HIGH gate: strict local extrema vs immediate neighbors (window=1).
# See `_local_extrema_indices` / assumption CYCLE-MIDCYCLE-EXTREMA-v1.
# Endpoints are never local extrema under window=1. Flat / monotone / single-
# extremum → incomplete (NO_LOCAL_PEAK / NO_LOCAL_TROUGH). No invent.
# HIGH also requires median > 0 (NONPOSITIVE_MEDIAN otherwise).
# Research-only sector prior never elevates confidence above LOW.
# Shrink (when stub on + prior>0 + incomplete + sample med>0):
#   λ = clip(1 - n_usable / MIN_COMPLETE_POINTS, 0, 1)
#   denom = (1-λ)*m + λ*prior  (always LOW / research_only)
# Empty + stub + prior → raw prior fill (compat). m≤0 / stub off → no invent.


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
    """Parse as-of / period date. Raises ValueError on unparseable non-empty strings."""
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
    """Accept (date|str, value), mapping with period_end/as_of/value, or bare number.

    Bad date strings drop the whole point (SF2) instead of raising ValueError.
    """
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
        if d_raw is None:
            return (None, v)
        try:
            return (_parse_as_of(d_raw), v)
        except (TypeError, ValueError):
            return None  # drop point on bad date
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        try:
            v = float(raw[1])
        except (TypeError, ValueError):
            return None
        if v != v:
            return None
        if raw[0] is None:
            return (None, v)
        try:
            return (_parse_as_of(raw[0]), v)
        except (TypeError, ValueError):
            return None  # drop point on bad date
    return None


def _span_years(dates: list[date]) -> float | None:
    if len(dates) < 2:
        return None
    delta = max(dates) - min(dates)
    return delta.days / 365.25


def _local_extrema_indices(values: Sequence[float]) -> tuple[list[int], list[int]]:
    """Strict local peak/trough indices (window=1 vs immediate neighbors).

    Peak at i when ``values[i] > values[i-1]`` and ``values[i] > values[i+1]``.
    Trough at i when ``values[i] < values[i-1]`` and ``values[i] < values[i+1]``.
    Endpoints (i=0, i=n-1) are never extrema. Empty / length < 3 → no extrema.
    Deterministic; no tie-breaking invent (equalities fail the strict test).
    """
    peaks: list[int] = []
    troughs: list[int] = []
    n = len(values)
    if n < 3:
        return peaks, troughs
    for i in range(1, n - 1):
        v, left, right = values[i], values[i - 1], values[i + 1]
        if v > left and v > right:
            peaks.append(i)
        elif v < left and v < right:
            troughs.append(i)
    return peaks, troughs


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
        Incomplete + sample median > 0 → shrink blend toward prior; empty series
        → raw prior fill (compat). Never upgrades confidence to HIGH.
    use_sector_prior_stub:
        Explicit opt-in for the research-only prior / shrink path.

    Returns
    -------
    MidCycleEstimate
        ``mid_cycle_denominator`` is None + LOW when incomplete or non-positive
        median; finite + HIGH only when explicit completeness rules pass and
        median > 0. Never invents a denom. Bad date strings drop the point.
    """
    reason_codes: list[str] = []
    try:
        as_of_d = _parse_as_of(as_of)
    except (TypeError, ValueError):
        # Unparseable as_of: degrade (no PIT filter) rather than throw.
        reason_codes.append("ASOF_UNPARSEABLE")
        as_of_d = None

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

    med = float(median(values))
    peak_indices, trough_indices = _local_extrema_indices(values)
    peak_detected = len(peak_indices) >= 1
    trough_detected = len(trough_indices) >= 1
    # Extremum values among local extrema only (None when that class is empty).
    peak = max(values[i] for i in peak_indices) if peak_indices else None
    trough = min(values[i] for i in trough_indices) if trough_indices else None

    diagnostics_base: dict[str, Any] = {
        "n_points": n_points,
        "n_usable": n_points,
        "window_span_years": span,
        "peak_value": peak,
        "trough_value": trough,
        "peak_detected": peak_detected,
        "trough_detected": trough_detected,
        "peak_indices": list(peak_indices),
        "trough_indices": list(trough_indices),
        "peak_trough_method": "local_extrema_v1",
        "local_extrema_window": 1,
        "median_value": med,
        "estimator": "median_of_pit_series_skel",
        "assumption_ids": [
            "CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1",
            "CYCLE-MIDCYCLE-EXTREMA-v1",
            "CYCLE-NORMALIZE-FLAG-v1",
        ],
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
    if not peak_detected:
        reason_codes.append("NO_LOCAL_PEAK")
        incomplete = True
    if not trough_detected:
        reason_codes.append("NO_LOCAL_TROUGH")
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
            sample_median=med,
        )

    # SF1: HIGH requires med > 0 (hook also gates denom>0; estimator must not claim HIGH).
    if not (med == med and med > 0):
        reason_codes.append("NONPOSITIVE_MEDIAN")
        return _low(
            None,
            reason_codes,
            n_points=n_points,
            n_usable=n_points,
            span=span,
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
        "peak_indices": [],
        "trough_indices": [],
        "peak_trough_method": "local_extrema_v1",
        "local_extrema_window": 1,
        "estimator": "median_of_pit_series_skel",
        "assumption_ids": [
            "CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1",
            "CYCLE-MIDCYCLE-EXTREMA-v1",
            "CYCLE-NORMALIZE-FLAG-v1",
        ],
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


def _with_prior_diag(
    extra: dict[str, Any] | None,
    *,
    shrink_lambda: float | None,
    sample_median: float | None,
    sector_prior: float,
) -> dict[str, Any]:
    """Attach shrink diagnostics + CYCLE-MIDCYCLE-SECTOR-PRIOR-SHRINK-v1 assumption."""
    base: dict[str, Any] = dict(extra or {})
    ids = list(
        base.get("assumption_ids")
        or [
            "CYCLE-MIDCYCLE-ESTIMATOR-SKEL-v1",
            "CYCLE-MIDCYCLE-EXTREMA-v1",
            "CYCLE-NORMALIZE-FLAG-v1",
        ]
    )
    if "CYCLE-MIDCYCLE-SECTOR-PRIOR-SHRINK-v1" not in ids:
        ids.append("CYCLE-MIDCYCLE-SECTOR-PRIOR-SHRINK-v1")
    base["assumption_ids"] = ids
    base["shrink_lambda"] = shrink_lambda
    base["sample_median"] = sample_median
    base["sector_prior"] = sector_prior
    return base


def _maybe_prior_or_low(
    reason_codes: list[str],
    *,
    n_points: int,
    n_usable: int,
    span: float | None,
    sector_prior: float | None,
    use_sector_prior_stub: bool,
    extra: dict[str, Any] | None = None,
    sample_median: float | None = None,
) -> MidCycleEstimate:
    """Sector prior only when explicitly opted in; always LOW / research-only.

    When stub on and prior > 0:
    - ``n_usable == 0`` or no finite sample median → raw prior fill (compat).
    - Incomplete with finite sample median ``m > 0`` → shrink toward prior:
      ``λ = clip(1 - n_usable / MIN_COMPLETE_POINTS, 0, 1)``,
      ``denom = (1-λ)*m + λ*prior`` (if denom ≤ 0 → None + LOW).
    - ``m ≤ 0`` → no invent (None + LOW).
    Never elevates confidence above LOW; HIGH path never calls this helper.
    """
    if use_sector_prior_stub and sector_prior is not None:
        try:
            prior = float(sector_prior)
        except (TypeError, ValueError):
            prior = None
        if prior is not None and prior == prior and prior > 0:
            med_ok = (
                sample_median is not None
                and sample_median == sample_median  # not NaN
            )
            # Empty / unusable series: keep raw prior fill (compat).
            if n_usable == 0 or not med_ok:
                codes = list(reason_codes) + [
                    "SECTOR_PRIOR_STUB_RESEARCH_ONLY",
                    "SECTOR_PRIOR_SHRINK_EMPTY_SERIES",
                ]
                return _low(
                    prior,
                    codes,
                    n_points=n_points,
                    n_usable=n_usable,
                    span=span,
                    extra=_with_prior_diag(
                        extra,
                        shrink_lambda=1.0,
                        sample_median=None,
                        sector_prior=prior,
                    ),
                    sector_prior_applied=True,
                    research_only=True,
                )

            m = float(sample_median)
            if not (m > 0):
                codes = list(reason_codes) + [
                    "SECTOR_PRIOR_SKIPPED_NONPOSITIVE_SAMPLE_MEDIAN"
                ]
                skip_extra = dict(extra or {})
                skip_extra["sample_median"] = m
                skip_extra["sector_prior"] = prior
                skip_extra["shrink_lambda"] = None
                return _low(
                    None,
                    codes,
                    n_points=n_points,
                    n_usable=n_usable,
                    span=span,
                    extra=skip_extra,
                    sector_prior_applied=False,
                    research_only=False,
                )

            # Shrink blend: more weight on prior when fewer usable points.
            lam = max(0.0, min(1.0, 1.0 - (float(n_usable) / float(MIN_COMPLETE_POINTS))))
            denom = (1.0 - lam) * m + lam * prior
            if not (denom == denom and denom > 0):
                codes = list(reason_codes) + ["SECTOR_PRIOR_SHRINK_NONPOSITIVE_DENOM"]
                return _low(
                    None,
                    codes,
                    n_points=n_points,
                    n_usable=n_usable,
                    span=span,
                    extra=_with_prior_diag(
                        extra,
                        shrink_lambda=lam,
                        sample_median=m,
                        sector_prior=prior,
                    ),
                    sector_prior_applied=False,
                    research_only=True,
                )

            codes = list(reason_codes) + [
                "SECTOR_PRIOR_STUB_RESEARCH_ONLY",
                "SECTOR_PRIOR_SHRINK_APPLIED",
            ]
            return _low(
                denom,
                codes,
                n_points=n_points,
                n_usable=n_usable,
                span=span,
                extra=_with_prior_diag(
                    extra,
                    shrink_lambda=lam,
                    sample_median=m,
                    sector_prior=prior,
                ),
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
