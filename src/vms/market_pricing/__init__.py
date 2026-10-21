"""Market-pricing regime + exit-price engine (SPEC §14 / VMS-0.2 Phase 9).

Fundamental value and future market exit price are distinct. Default exit-price
generation uses terminal multiples conditional on an independent market-pricing
state — it never silently copies intrinsic value to future price.

Heavy submodules (exit_prices, estimator, …) load lazily via ``__getattr__`` so
``vms.schemas.config`` can import ``MarketPricingConfig`` without circular imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from vms.market_pricing.schemas import (
    MARKET_PRICING_STATES,
    MarketPricingState,
    MarketPricingStatePosterior,
    fallback_market_pricing_prior,
    unavailable_market_pricing,
)

if TYPE_CHECKING:  # pragma: no cover
    from vms.market_pricing.config import MarketPricingConfig
    from vms.market_pricing.exit_prices import ExitPriceBundle, ExitPricePath
    from vms.market_pricing.sensitivity import PersistenceSensitivityReport
    from vms.market_pricing.transitions import TransitionModel

__all__ = [
    "MARKET_PRICING_STATES",
    "MarketPricingState",
    "MarketPricingStatePosterior",
    "MarketPricingConfig",
    "ExitPriceBundle",
    "ExitPricePath",
    "PersistenceSensitivityReport",
    "TransitionModel",
    "unavailable_market_pricing",
    "fallback_market_pricing_prior",
    "default_market_pricing_config",
    "estimate_market_pricing_state",
    "apply_configured_dependence",
    "sample_state",
    "generate_exit_prices",
    "run_convergence_scenario",
    "compare_persistence_vs_mean_reversion",
    "constant_state_persistence",
    "build_transition_models",
]

_LAZY = {
    "MarketPricingConfig": ("vms.market_pricing.config", "MarketPricingConfig"),
    "default_market_pricing_config": ("vms.market_pricing.config", "default_market_pricing_config"),
    "estimate_market_pricing_state": ("vms.market_pricing.estimator", "estimate_market_pricing_state"),
    "apply_configured_dependence": ("vms.market_pricing.estimator", "apply_configured_dependence"),
    "sample_state": ("vms.market_pricing.estimator", "sample_state"),
    "generate_exit_prices": ("vms.market_pricing.exit_prices", "generate_exit_prices"),
    "ExitPriceBundle": ("vms.market_pricing.exit_prices", "ExitPriceBundle"),
    "ExitPricePath": ("vms.market_pricing.exit_prices", "ExitPricePath"),
    "run_convergence_scenario": ("vms.market_pricing.convergence", "run_convergence_scenario"),
    "compare_persistence_vs_mean_reversion": (
        "vms.market_pricing.sensitivity",
        "compare_persistence_vs_mean_reversion",
    ),
    "PersistenceSensitivityReport": ("vms.market_pricing.sensitivity", "PersistenceSensitivityReport"),
    "constant_state_persistence": ("vms.market_pricing.transitions", "constant_state_persistence"),
    "build_transition_models": ("vms.market_pricing.transitions", "build_transition_models"),
    "TransitionModel": ("vms.market_pricing.transitions", "TransitionModel"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        mod_name, attr = _LAZY[name]
        import importlib

        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
