"""Recompute hooks when fundamental or market-state posteriors change (SPEC §15.3)."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from vms.market_pricing.exit_prices import ExitPriceBundle, generate_exit_prices
from vms.market_pricing.schemas import MarketPricingStatePosterior
from vms.returns.track_b import (
    ReturnDistributionBundleTrackB,
    build_return_distributions_from_exit_prices,
    content_fingerprint_track_b,
)
from vms.schemas.config import LoadedConfig
from vms.statements.paths import FinancialPathBundle


def posterior_fingerprint(posterior: MarketPricingStatePosterior | Mapping[str, Any]) -> str:
    if isinstance(posterior, MarketPricingStatePosterior):
        payload = posterior.model_dump(mode="json")
    else:
        payload = dict(posterior)
    return hashlib.sha256(repr(sorted(payload.items()) if isinstance(payload, dict) else payload).encode()).hexdigest()[:16]


def exit_bundle_fingerprint(bundle: ExitPriceBundle) -> str:
    payload = {
        "scenario": bundle.scenario_kind,
        "transition": bundle.transition_model_id,
        "metric": bundle.metric_id,
        "n_valid": bundle.n_valid,
        "summaries": bundle.summaries,
        "prices": sorted(
            (p.path_id, p.horizon_years, p.exit_price_per_share, p.terminal_market_state)
            for p in bundle.paths
            if p.valid
        )[:500],
    }
    return hashlib.sha256(repr(payload).encode()).hexdigest()[:16]


def recompute_returns_after_market_posterior_change(
    *,
    financial_paths: FinancialPathBundle,
    market_posterior: MarketPricingStatePosterior,
    spot_price: float,
    loaded: LoadedConfig,
    prior_fingerprint: str | None = None,
    horizons_years: Sequence[int] = (1, 3),
    seed: int = 42,
    metric_id: str | None = None,
) -> tuple[ExitPriceBundle, ReturnDistributionBundleTrackB, dict[str, Any]]:
    """Regenerate exit prices from the new market posterior, then rebuild returns.

    Returns (exit_bundle, return_bundle, meta). Meta records whether the posterior
    change actually altered exit/return fingerprints (AC3).
    """
    exit_bundle = generate_exit_prices(
        financial_paths,
        market_posterior=market_posterior,
        config=loaded.config.market_pricing,
        horizons_years=horizons_years,
        metric_id=metric_id,
        seed=seed,
    )
    returns = build_return_distributions_from_exit_prices(
        exit_prices=exit_bundle,
        spot_price=spot_price,
        loaded=loaded,
        financial=financial_paths,
        horizons_years=horizons_years,
    )
    meta = {
        "posterior_fingerprint": posterior_fingerprint(market_posterior),
        "exit_fingerprint": exit_bundle_fingerprint(exit_bundle),
        "return_fingerprint": content_fingerprint_track_b(returns),
        "prior_fingerprint": prior_fingerprint,
        "recomputed": True,
        "assumption": "RETURN-RECOMPUTE-ON-POSTERIOR-CHANGE-v1",
    }
    if prior_fingerprint is not None:
        meta["changed_vs_prior"] = meta["return_fingerprint"] != prior_fingerprint
    return exit_bundle, returns, meta
