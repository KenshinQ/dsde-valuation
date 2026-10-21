"""Market-pricing state contracts (SPEC §14.3). Distinct from fundamental regimes.

Fundamental regimes use GROWTH / STABLE / DETERIORATING / RECOVERY (/ optional DISTRESS).
Market-pricing states use COMPRESSED / NORMAL / EXPANDED (/ optional DISLOCATION).
These vocabularies MUST NOT collapse into one label (SPEC §22.14).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.regimes.schemas import validate_probabilities

MARKET_PRICING_STATES = ("COMPRESSED", "NORMAL", "EXPANDED", "DISLOCATION")


class MarketPricingState(str, Enum):
    """Baseline market-pricing states (SPEC §14.3). Not fundamental regimes."""

    COMPRESSED = "COMPRESSED"
    NORMAL = "NORMAL"
    EXPANDED = "EXPANDED"
    DISLOCATION = "DISLOCATION"


class MarketPricingStatePosterior(BaseModel):
    """Posterior over market-pricing states. Separate type from FundamentalRegimePosterior."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["MARKET_PRICING"] = "MARKET_PRICING"
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    states: list[str] = Field(default_factory=list)
    probabilities: dict[str, float] | None = None
    source: str | None = None
    reason: str | None = None
    estimator_phase: Literal["PHASE_9_DEFERRED"] = "PHASE_9_DEFERRED"
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "MarketPricingStatePosterior":
        if self.status == "UNAVAILABLE":
            if self.probabilities is not None or self.states:
                raise ValueError("UNAVAILABLE market-pricing posterior must not carry states/probabilities")
            if not self.reason:
                raise ValueError("UNAVAILABLE market-pricing posterior needs a reason")
        else:
            if self.probabilities is None or not self.source:
                raise ValueError("AVAILABLE market-pricing posterior needs probabilities and a source")
            bad = [s for s in self.states if s not in MARKET_PRICING_STATES]
            if bad:
                raise ValueError(f"unknown market-pricing states: {bad}")
            validate_probabilities(self.probabilities, self.states, "market-pricing posterior")
        return self


def unavailable_market_pricing(*, reason: str | None = None) -> MarketPricingStatePosterior:
    """Phase-3 stub: estimator not implemented (Phase 9). Never inferred from fundamentals."""
    return MarketPricingStatePosterior(
        status="UNAVAILABLE",
        reason=reason
        or (
            "market-pricing state estimator deferred to Phase 9 "
            "(SPEC §14 / §20); not inferred from fundamental regimes"
        ),
        flags=["MARKET_PRICING_ESTIMATOR_NOT_IMPLEMENTED", "LOW_CONFIDENCE"],
        assumptions=["MARKET-PRICING-SCHEMA-v1", "MARKET-PRICING-ESTIMATOR-PHASE9-v1"],
    )
