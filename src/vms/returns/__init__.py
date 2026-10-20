"""Entry-price-conditioned return distributions (SPEC §12, Phase 7)."""

from vms.returns.distributions import (ReturnDistributionBundle, build_return_distributions,
                                       content_fingerprint, entry_price_grid,
                                       pathwise_returns_improve_at_lower_price)
from vms.returns.formula import annualized_geometric, holding_period_return
from vms.returns.horizon_value import cumulative_dps, enterprise_value_at_horizon, equity_at_horizon
from vms.returns.stats import cvar_es, summarize_returns

__all__ = [
    "ReturnDistributionBundle",
    "annualized_geometric",
    "build_return_distributions",
    "content_fingerprint",
    "cumulative_dps",
    "cvar_es",
    "enterprise_value_at_horizon",
    "entry_price_grid",
    "equity_at_horizon",
    "holding_period_return",
    "pathwise_returns_improve_at_lower_price",
    "summarize_returns",
]
