"""Denominator validity gates for multiples (SPEC §12.5, §22.9).

Negative / near-zero / non-finite denominators are never treated as valid
conventional multiples.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DenominatorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    value: float | None
    ok: bool
    code: str
    detail: str
    warnings: list[str] = Field(default_factory=list)


def check_denominator(
    *,
    field: str,
    value: float | None,
    near_zero_eps: float = 1e-6,
    require_positive: bool = True,
) -> DenominatorDecision:
    """Gate a subject denominator before multiplying by a peer multiple."""
    if value is None:
        return DenominatorDecision(
            field=field, value=None, ok=False,
            code="MISSING_DENOMINATOR",
            detail=f"{field} is missing",
        )
    if not math.isfinite(value):
        return DenominatorDecision(
            field=field, value=value, ok=False,
            code="NONFINITE_DENOMINATOR",
            detail=f"{field}={value} is non-finite",
        )
    warnings: list[str] = []
    if abs(value) < near_zero_eps:
        return DenominatorDecision(
            field=field, value=value, ok=False,
            code="INELIGIBLE_DENOMINATOR",
            detail=f"{field}={value} is near-zero (|x|<{near_zero_eps}); conventional multiple undefined",
            warnings=["NEAR_ZERO_DENOMINATOR"],
        )
    if require_positive and value <= 0:
        return DenominatorDecision(
            field=field, value=value, ok=False,
            code="INELIGIBLE_DENOMINATOR",
            detail=f"{field}={value} is non-positive; conventional multiple undefined",
            warnings=["NEGATIVE_OR_NONPOSITIVE_DENOMINATOR"],
        )
    if not require_positive and value < 0:
        warnings.append("NEGATIVE_DENOMINATOR_QUALIFIED")
    return DenominatorDecision(
        field=field, value=value, ok=True,
        code="DENOMINATOR_OK",
        detail=f"{field}={value}",
        warnings=warnings,
    )


def subject_metric(subject: dict[str, Any], field: str) -> float | None:
    """Pull a finite float from subject fundamentals; missing → None."""
    if field not in subject:
        return None
    v = subject[field]
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
