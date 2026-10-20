"""Market-regime dimension (SPEC §7.4). VMS-0.1 has no market-regime model or inputs, so the
dimension is UNAVAILABLE (MARKET-REGIME-UNAVAILABLE-v1). It is never inferred from fundamentals."""

from __future__ import annotations

from vms.regimes.schemas import MarketRegimePosterior


def market_regime(source: str) -> MarketRegimePosterior:
    if source == "none":
        return MarketRegimePosterior(status="UNAVAILABLE",
                                     reason="no market-regime inputs provided (regimes.market_regime_source: none); "
                                            "not inferred from the fundamental state")
    raise ValueError(f"unknown market_regime_source {source!r}")
