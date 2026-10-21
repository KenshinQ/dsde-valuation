"""Explicit named convergence-to-intrinsic scenarios (SPEC §14.4). Never the default."""

from __future__ import annotations

from typing import Mapping, Sequence

from vms.market_pricing.config import MarketPricingConfig, default_market_pricing_config
from vms.market_pricing.exit_prices import ExitPriceBundle, generate_exit_prices
from vms.market_pricing.schemas import MarketPricingStatePosterior
from vms.market_pricing.transitions import TransitionModel, constant_state_persistence
from vms.statements.paths import FinancialPathBundle, FinancialPathRecord


def run_convergence_scenario(
    financial_paths: FinancialPathBundle | Sequence[FinancialPathRecord],
    *,
    market_posterior: MarketPricingStatePosterior,
    intrinsic_by_path_horizon: Mapping[tuple[str, int], float],
    config: MarketPricingConfig | None = None,
    horizons_years: Sequence[int] = (1, 3),
    metric_id: str | None = None,
    transition_model: TransitionModel | None = None,
    seed: int = 42,
    stochastic_rate: float | None = None,
    blend_weight: float | None = None,
) -> ExitPriceBundle:
    """Build an explicitly labeled CONVERGENCE_TO_INTRINSIC exit-price bundle.

    Requires either config.convergence.enabled or explicit stochastic_rate.
    """
    cfg = config or default_market_pricing_config()
    if not cfg.convergence.enabled and stochastic_rate is None:
        # Enable a copy for this call only — still labeled as explicit scenario.
        cfg = cfg.model_copy(
            update={
                "convergence": cfg.convergence.model_copy(
                    update={
                        "enabled": True,
                        "stochastic_rate": 0.25 if stochastic_rate is None else stochastic_rate,
                        "blend_weight": 0.5 if blend_weight is None else blend_weight,
                    }
                )
            }
        )
    return generate_exit_prices(
        financial_paths,
        market_posterior=market_posterior,
        config=cfg,
        horizons_years=horizons_years,
        metric_id=metric_id,
        transition_model=transition_model or constant_state_persistence(),
        seed=seed,
        scenario_kind="CONVERGENCE_TO_INTRINSIC",
        intrinsic_by_path_horizon=intrinsic_by_path_horizon,
        convergence_rate=stochastic_rate,
        convergence_blend=blend_weight,
    )
