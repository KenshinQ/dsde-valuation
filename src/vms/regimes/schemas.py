"""Regime schemas (SPEC §7.4). Fundamental and market regimes are DISTINCT types.

``FundamentalRegimePosterior`` (kind="FUNDAMENTAL") is inferred from PIT fundamentals only.
``MarketRegimePosterior`` (kind="MARKET") is a separate dimension. Without market-regime inputs it is
``UNAVAILABLE`` and is never filled from the fundamental state. The ``kind`` literals plus extra="forbid"
make cross-validation between the two impossible.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROB_TOL = 1e-9


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def validate_probabilities(p: dict[str, float], states: list[str], what: str = "posterior") -> None:
    if list(p) != list(states):
        raise ValueError(f"{what}: keys {list(p)} != states {states}")
    bad = {k: v for k, v in p.items() if not (math.isfinite(v) and v >= 0.0)}
    if bad:
        raise ValueError(f"{what}: probabilities must be finite and >= 0; bad {bad}")
    s = sum(p.values())
    if abs(s - 1.0) > PROB_TOL:
        raise ValueError(f"{what}: probabilities sum to {s!r}, not 1 within {PROB_TOL}")


class FeatureRow(_M):
    """Fundamental features at one period end. Built from PIT financial records only."""

    period_end: date
    cadence: Literal["quarterly", "annual"]
    revenue_growth_yoy: float | None = Field(description="TTM revenue / TTM revenue one year earlier - 1")
    ebit_margin_ttm: float | None
    ebit_margin_change_yoy: float | None = Field(description="TTM EBIT margin minus its value one year earlier")
    known_at: datetime = Field(description="max published_at of all inputs (<= as_of by construction)")
    refs: list[str]
    flags: list[str]


class PeriodPosterior(_M):
    period_end: date
    probabilities: dict[str, float]
    memberships: dict[str, float | None]
    argmax: str
    entropy: float
    flags: list[str]


class FundamentalRegimePosterior(_M):
    kind: Literal["FUNDAMENTAL"] = "FUNDAMENTAL"
    model_id: str
    model_version: str
    states: list[str]
    probabilities: dict[str, float]
    period_end: date | None = Field(description="latest feature period (None => no features; prior used)")
    as_of: datetime
    staleness_days: int | None
    inputs: Literal["PIT_FUNDAMENTALS_ONLY"] = "PIT_FUNDAMENTALS_ONLY"
    flags: list[str]
    assumptions: list[str]

    @model_validator(mode="after")
    def _probs(self) -> "FundamentalRegimePosterior":
        validate_probabilities(self.probabilities, self.states, "fundamental posterior")
        return self


class MarketRegimePosterior(_M):
    kind: Literal["MARKET"] = "MARKET"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    states: list[str] = Field(default_factory=list)
    probabilities: dict[str, float] | None = None
    source: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "MarketRegimePosterior":
        if self.status == "UNAVAILABLE":
            if self.probabilities is not None or self.states:
                raise ValueError("UNAVAILABLE market regime must not carry states/probabilities")
            if not self.reason:
                raise ValueError("UNAVAILABLE market regime needs a reason")
        else:
            if self.probabilities is None or not self.source:
                raise ValueError("AVAILABLE market regime needs probabilities and a source")
            validate_probabilities(self.probabilities, self.states, "market posterior")
        return self


class TransitionModel(_M):
    """Annual-step transition matrix with a Dirichlet prior per row (REGIME-TRANSITION-DIRICHLET-v1)."""

    states: list[str]
    step: Literal["annual"] = "annual"
    prior_alpha: list[list[float]]
    expected_counts: list[list[float]]
    posterior_alpha: list[list[float]]
    mean: list[list[float]]
    posterior_sd: list[list[float]]
    row_support: list[float]
    n_pairs: int
    pair_weight: float = Field(description="weight per overlapping pair (1 / observations per year)")
    flags: list[str]

    @field_validator("mean")
    @classmethod
    def _rows(cls, v: list[list[float]]) -> list[list[float]]:
        for row in v:
            if any(not (math.isfinite(x) and x >= 0) for x in row) or abs(sum(row) - 1) > PROB_TOL:
                raise ValueError(f"transition row invalid: {row}")
        return v
