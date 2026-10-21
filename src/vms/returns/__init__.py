"""Entry-price-conditioned return distributions.

Legacy Track-A horizon-equity path (VMS-0.1 Phase 7) remains in ``distributions``.
VMS-0.2 Phase 10 Track B uses exit-market prices via ``track_b``.
"""

from vms.returns.distributions import (
    ReturnDistributionBundle,
    build_return_distributions,
    content_fingerprint,
    entry_price_grid,
    pathwise_returns_improve_at_lower_price,
)
from vms.returns.formula import annualized_geometric, holding_period_return, return_components
from vms.returns.horizon_value import cumulative_dps, enterprise_value_at_horizon, equity_at_horizon
from vms.returns.recompute import (
    exit_bundle_fingerprint,
    posterior_fingerprint,
    recompute_returns_after_market_posterior_change,
)
from vms.returns.stats import cvar_es, summarize_returns
from vms.returns.track_b import (
    ReturnDistributionBundleTrackB,
    build_return_distributions_from_exit_prices,
    content_fingerprint_track_b,
    merge_entry_prices,
    pathwise_returns_improve_at_lower_price_track_b,
)

# Prefer Track B grid helper name collision: re-export track_b entry_price_grid as alias
from vms.returns.track_b import entry_price_grid as entry_price_grid_track_b

__all__ = [
    "ReturnDistributionBundle",
    "ReturnDistributionBundleTrackB",
    "annualized_geometric",
    "build_return_distributions",
    "build_return_distributions_from_exit_prices",
    "content_fingerprint",
    "content_fingerprint_track_b",
    "cumulative_dps",
    "cvar_es",
    "enterprise_value_at_horizon",
    "entry_price_grid",
    "entry_price_grid_track_b",
    "equity_at_horizon",
    "exit_bundle_fingerprint",
    "holding_period_return",
    "merge_entry_prices",
    "pathwise_returns_improve_at_lower_price",
    "pathwise_returns_improve_at_lower_price_track_b",
    "posterior_fingerprint",
    "recompute_returns_after_market_posterior_change",
    "return_components",
    "summarize_returns",
]
