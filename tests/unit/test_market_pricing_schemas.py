"""Market-pricing state schemas are distinct from fundamental regimes (SPEC §8.2 / §14.3 / §22.14)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vms.market_pricing import (
    MARKET_PRICING_STATES,
    MarketPricingState,
    MarketPricingStatePosterior,
    unavailable_market_pricing,
)
from vms.regimes.schemas import FundamentalRegimePosterior, MarketRegimePosterior
from vms.schemas.config import FUNDAMENTAL_STATES


def test_vocabularies_disjoint():
    assert set(MARKET_PRICING_STATES).isdisjoint(set(FUNDAMENTAL_STATES))
    assert {s.value for s in MarketPricingState} == set(MARKET_PRICING_STATES)


def test_schemas_cannot_cross_validate():
    mp = unavailable_market_pricing()
    assert mp.kind == "MARKET_PRICING" and mp.status == "UNAVAILABLE"
    assert mp.estimator_phase == "PHASE_9_DEFERRED"
    fund = FundamentalRegimePosterior(
        model_id="X", model_version="1", states=["GROWTH", "STABLE"],
        probabilities={"GROWTH": 0.4, "STABLE": 0.6}, period_end=None,
        as_of=__import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc),
        staleness_days=None, flags=[], assumptions=[],
    )
    with pytest.raises(ValidationError):
        MarketPricingStatePosterior.model_validate(fund.model_dump())
    with pytest.raises(ValidationError):
        FundamentalRegimePosterior.model_validate(mp.model_dump())
    # Legacy carrier also distinct
    carrier = MarketRegimePosterior(status="UNAVAILABLE", reason="x")
    with pytest.raises(ValidationError):
        MarketPricingStatePosterior.model_validate(carrier.model_dump())
    assert not issubclass(MarketPricingStatePosterior, FundamentalRegimePosterior)
    assert not issubclass(FundamentalRegimePosterior, MarketPricingStatePosterior)


def test_available_requires_market_pricing_states_only():
    ok = MarketPricingStatePosterior(
        status="AVAILABLE",
        states=["COMPRESSED", "NORMAL", "EXPANDED", "DISLOCATION"],
        probabilities={"COMPRESSED": 0.1, "NORMAL": 0.6, "EXPANDED": 0.2, "DISLOCATION": 0.1},
        source="unit-test-fixture",
    )
    assert ok.status == "AVAILABLE"
    with pytest.raises(ValidationError):
        MarketPricingStatePosterior(
            status="AVAILABLE",
            states=["GROWTH", "STABLE"],  # fundamental labels forbidden here
            probabilities={"GROWTH": 0.5, "STABLE": 0.5},
            source="bad",
        )


def test_unavailable_rejects_embedded_probabilities():
    with pytest.raises(ValidationError, match="must not carry"):
        MarketPricingStatePosterior(
            status="UNAVAILABLE", reason="x",
            states=["NORMAL"], probabilities={"NORMAL": 1.0},
        )
