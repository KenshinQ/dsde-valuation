"""Robust peer-multiple aggregation (SPEC §12.5).

Never blind arithmetic mean of raw peers. Configured estimators:
median (default), winsorized_mean, trimmed_mean. Sample-size and dispersion
diagnostics are always attached.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

AggregatorName = Literal["median", "winsorized_mean", "trimmed_mean"]


class AggregateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    multiple: float | None
    estimator: str
    n: int
    n_raw: int
    n_excluded_nonpositive: int
    median: float | None
    mean_of_retained: float | None = None
    p25: float | None = None
    p75: float | None = None
    iqr: float | None = None
    mad: float | None = None
    dispersion_ratio: float | None = Field(
        default=None, description="IQR / median when median > 0; high => uncertainty",
    )
    flags: list[str] = Field(default_factory=list)
    detail: str = ""


def _positive_finite(xs: list[float]) -> tuple[list[float], int]:
    kept: list[float] = []
    dropped = 0
    for x in xs:
        if math.isfinite(x) and x > 0:
            kept.append(float(x))
        else:
            dropped += 1
    return kept, dropped


def _winsorize(arr: np.ndarray, pct: float) -> np.ndarray:
    if arr.size == 0:
        return arr
    lo = float(np.quantile(arr, pct))
    hi = float(np.quantile(arr, 1.0 - pct))
    return np.clip(arr, lo, hi)


def _trim(arr: np.ndarray, pct: float) -> np.ndarray:
    if arr.size == 0:
        return arr
    lo = float(np.quantile(arr, pct))
    hi = float(np.quantile(arr, 1.0 - pct))
    return arr[(arr >= lo) & (arr <= hi)]


def aggregate_multiples(
    values: list[float],
    *,
    estimator: AggregatorName = "median",
    winsor_pct: float = 0.10,
    trim_pct: float = 0.10,
    peer_min_count: int = 5,
    peer_warn_count: int = 8,
    max_dispersion_ratio: float = 2.0,
    shrink_prior: float | None = None,
    shrink_strength: float = 0.0,
) -> AggregateResult:
    raw_n = len(values)
    kept, dropped = _positive_finite(values)
    flags: list[str] = []
    if dropped:
        flags.append("EXCLUDED_NONPOSITIVE_OR_NONFINITE_PEER_MULTIPLES")
    if not kept:
        return AggregateResult(
            ok=False, multiple=None, estimator=estimator, n=0, n_raw=raw_n,
            n_excluded_nonpositive=dropped, median=None,
            flags=sorted(flags + ["PEER_DATA_INSUFFICIENT"]),
            detail="no positive finite peer multiples after filters",
        )

    arr = np.asarray(kept, dtype=float)
    med = float(np.median(arr))
    p25 = float(np.quantile(arr, 0.25))
    p75 = float(np.quantile(arr, 0.75))
    iqr = p75 - p25
    mad = float(np.median(np.abs(arr - med)))
    disp = (iqr / med) if med > 0 else None
    if disp is not None and disp > max_dispersion_ratio:
        flags.append("HIGH_PEER_DISPERSION")

    if estimator == "median":
        point = med
        retained = arr
    elif estimator == "winsorized_mean":
        retained = _winsorize(arr, winsor_pct)
        point = float(np.mean(retained))
        flags.append("AGGREGATOR_WINSORIZED_MEAN")
    elif estimator == "trimmed_mean":
        retained = _trim(arr, trim_pct)
        if retained.size == 0:
            retained = arr
            flags.append("TRIM_EMPTY_FALLBACK_MEDIAN")
            point = med
        else:
            point = float(np.mean(retained))
            flags.append("AGGREGATOR_TRIMMED_MEAN")
    else:
        raise ValueError(f"unknown aggregator {estimator!r}")

    if shrink_prior is not None and shrink_strength > 0 and math.isfinite(shrink_prior) and shrink_prior > 0:
        n = float(arr.size)
        k = float(shrink_strength)
        point = (n * point + k * float(shrink_prior)) / (n + k)
        flags.append("SHRINK_TO_PRIOR")

    n = int(arr.size)
    if n < peer_min_count:
        flags.append("PEER_SCARCITY")
        flags.append("PEER_DATA_INSUFFICIENT")
        return AggregateResult(
            ok=False, multiple=None, estimator=estimator, n=n, n_raw=raw_n,
            n_excluded_nonpositive=dropped, median=med,
            mean_of_retained=float(np.mean(retained)) if retained.size else None,
            p25=p25, p75=p75, iqr=iqr, mad=mad, dispersion_ratio=disp,
            flags=sorted(set(flags)),
            detail=f"n={n} < peer_min_count={peer_min_count}",
        )
    if n < peer_warn_count:
        flags.append("SMALL_PEER_SAMPLE")

    return AggregateResult(
        ok=True, multiple=float(point), estimator=estimator, n=n, n_raw=raw_n,
        n_excluded_nonpositive=dropped, median=med,
        mean_of_retained=float(np.mean(retained)) if retained.size else None,
        p25=p25, p75=p75, iqr=iqr, mad=mad, dispersion_ratio=disp,
        flags=sorted(set(flags)),
        detail=f"estimator={estimator}; n={n}; multiple={point}",
    )


def aggregate_diagnostics(result: AggregateResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
