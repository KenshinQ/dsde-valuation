"""Market-regime carrier on RegimeResult (estimation pipeline).

VMS-0.2 Phase 3: the *vocabulary* of market-pricing states lives in
``vms.market_pricing`` (COMPRESSED / NORMAL / EXPANDED / DISLOCATION; SPEC §14.3).
This module only exposes an UNAVAILABLE ``MarketRegimePosterior`` so the
fundamental-regime result never invents a market label from fundamentals
(MARKET-REGIME-UNAVAILABLE-v1). Phase 9 populates ``MarketPricingStatePosterior`` via ``vms.market_pricing``;
this legacy carrier remains UNAVAILABLE when market_regime_source is ``none``.
"""

from __future__ import annotations

from vms.regimes.schemas import MarketRegimePosterior


def market_regime(source: str) -> MarketRegimePosterior:
    if source == "none":
        return MarketRegimePosterior(
            status="UNAVAILABLE",
            reason=(
                "no market-pricing estimator configured (regimes.market_regime_source: none); "
                "use vms.market_pricing.estimate_market_pricing_state for Phase 9 posteriors; "
                "not inferred from the fundamental state"
            ),
        )
    raise ValueError(f"unknown market_regime_source {source!r}")
