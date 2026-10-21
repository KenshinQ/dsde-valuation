"""Market-pricing state contracts (SPEC §14.3). Distinct from fundamental regimes.

Fundamental regimes use GROWTH / STABLE / DETERIORATING / RECOVERY (/ optional DISTRESS).
Market-pricing states use COMPRESSED / NORMAL / EXPANDED (/ optional DISLOCATION).
These vocabularies MUST NOT collapse into one label (SPEC §22.14).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from vms.assumptions import cite
def validate_probabilities(
    probabilities: dict[str, float],
    states: list[str],
    label: str,
    *,
    tol: float = 1e-8,
) -> None:
    """Local copy — avoid importing vms.regimes (circular with schemas.config)."""
    if set(probabilities) != set(states):
        raise ValueError(f"{label}: probability keys {sorted(probabilities)} != states {states}")
    if any((not isinstance(v, (int, float))) or v < -tol for v in probabilities.values()):
        raise ValueError(f"{label}: probabilities must be non-negative finite")
    s = float(sum(probabilities.values()))
    if abs(s - 1.0) > tol:
        raise ValueError(f"{label}: probabilities sum to {s}, not 1")


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
    estimator_phase: Literal["PHASE_9", "PHASE_9_DEFERRED"] = "PHASE_9"
    confidence: Literal["HIGH", "MEDIUM", "LOW", "NONE"] = "NONE"
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    # Explicit dependence hook — None means independent of fundamentals (default).
    dependence_on_fundamentals: Literal["NONE", "CONFIGURED"] = "NONE"
    diagnostics: dict = Field(default_factory=dict)

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
    """Estimator unavailable — never inferred from fundamentals (SPEC §14.3)."""
    return MarketPricingStatePosterior(
        status="UNAVAILABLE",
        reason=reason
        or (
            "market-pricing state estimator unavailable / insufficient market data "
            "(SPEC §14.3); not inferred from fundamental regimes"
        ),
        estimator_phase="PHASE_9",
        confidence="NONE",
        flags=["MARKET_PRICING_ESTIMATOR_UNAVAILABLE", "LOW_CONFIDENCE"],
        assumptions=cite(
            "MARKET-PRICING-SCHEMA-v1",
            "MARKET-PRICING-INDEPENDENT-v1",
            "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
        ),
        dependence_on_fundamentals="NONE",
    )


def fallback_market_pricing_prior(
    probabilities: dict[str, float],
    *,
    reason: str,
    source: str = "configured_fallback_prior",
) -> MarketPricingStatePosterior:
    """Explicit low-confidence fallback distribution when estimation is unsupported."""
    states = [s for s in MARKET_PRICING_STATES if s in probabilities]
    return MarketPricingStatePosterior(
        status="AVAILABLE",
        states=states,
        probabilities={s: float(probabilities[s]) for s in states},
        source=source,
        reason=reason,
        estimator_phase="PHASE_9",
        confidence="LOW",
        flags=["MARKET_PRICING_FALLBACK_PRIOR", "LOW_CONFIDENCE", "ESTIMATION_UNSUPPORTED"],
        assumptions=cite(
            "MARKET-PRICING-SCHEMA-v1",
            "MARKET-PRICING-FALLBACK-PRIOR-v1",
            "MARKET-PRICING-INDEPENDENT-v1",
            "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
        ),
        dependence_on_fundamentals="NONE",
        diagnostics={"fallback": True},
    )
