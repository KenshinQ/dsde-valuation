"""Market-pricing state transitions: persistence baseline + optional configured MR (SPEC §14.5)."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.market_pricing.config import MarketPricingConfig, MeanReversionConfig, default_market_pricing_config
from vms.market_pricing.schemas import MARKET_PRICING_STATES

TransitionModelId = Literal[
    "CONSTANT_STATE_PERSISTENCE",
    "CONFIGURED_SLOW_MEAN_REVERSION",
    "CONFIGURED_FAST_MEAN_REVERSION",
]


class TransitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: TransitionModelId
    estimation_status: Literal["BASELINE", "UNSUPPORTED", "CONFIGURED_ONLY"]
    matrix: dict[str, dict[str, float]]  # from_state -> to_state -> prob
    assumptions: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    notes: str = ""


def _identity_matrix() -> dict[str, dict[str, float]]:
    return {s: {t: (1.0 if s == t else 0.0) for t in MARKET_PRICING_STATES} for s in MARKET_PRICING_STATES}


def _reversion_matrix(rate: float, normal_stay: float) -> dict[str, dict[str, float]]:
    """Configured transition: non-NORMAL rows move toward NORMAL with `rate`; NORMAL stays with normal_stay."""
    m: dict[str, dict[str, float]] = {}
    for s in MARKET_PRICING_STATES:
        row = {t: 0.0 for t in MARKET_PRICING_STATES}
        if s == "NORMAL":
            row["NORMAL"] = normal_stay
            rem = 1.0 - normal_stay
            others = [t for t in MARKET_PRICING_STATES if t != "NORMAL"]
            for t in others:
                row[t] = rem / len(others)
        else:
            row[s] = 1.0 - rate
            row["NORMAL"] = rate
        m[s] = row
    return m


def constant_state_persistence() -> TransitionModel:
    """Always-available baseline (SPEC §14.5 / Phase 9 AC2)."""
    return TransitionModel(
        model_id="CONSTANT_STATE_PERSISTENCE",
        estimation_status="BASELINE",
        matrix=_identity_matrix(),
        assumptions=cite(
            "MARKET-PRICING-PERSISTENCE-BASELINE-v1",
            "MARKET-PRICING-SCHEMA-v1",
            "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
        ),
        flags=["PERSISTENCE_BASELINE"],
        notes="State persists for the full horizon; no mean-reversion imposed.",
    )


def configured_mean_reversion(
    cfg: MeanReversionConfig,
    *,
    speed: Literal["slow", "fast"],
) -> TransitionModel:
    """Configured-only MR. Does not invent rates from short series."""
    if cfg.estimation_status == "UNSUPPORTED" and not cfg.enabled:
        # Still allow building the matrix for sensitivity, but label UNSUPPORTED.
        status: Literal["UNSUPPORTED", "CONFIGURED_ONLY"] = "UNSUPPORTED"
    else:
        status = "CONFIGURED_ONLY" if cfg.enabled else "UNSUPPORTED"
    rate = cfg.slow_reversion_rate if speed == "slow" else cfg.fast_reversion_rate
    mid: TransitionModelId = (
        "CONFIGURED_SLOW_MEAN_REVERSION" if speed == "slow" else "CONFIGURED_FAST_MEAN_REVERSION"
    )
    return TransitionModel(
        model_id=mid,
        estimation_status=status,
        matrix=_reversion_matrix(rate, cfg.normal_stay),
        assumptions=cite(
            "MARKET-PRICING-PERSISTENCE-BASELINE-v1",
            "MARKET-PRICING-ESTIMATOR-PHASE9-v1",
            "MARKET-PRICING-SCHEMA-v1",
        ),
        flags=["CONFIGURED_MEAN_REVERSION", f"SPEED_{speed.upper()}", status],
        notes=(
            f"Configured {speed} reversion rate={rate} toward NORMAL; "
            "not estimated from short series (SPEC §14.5)."
        ),
    )


def build_transition_models(config: MarketPricingConfig | None = None) -> list[TransitionModel]:
    cfg = config or default_market_pricing_config()
    models = [constant_state_persistence()]
    models.append(configured_mean_reversion(cfg.mean_reversion, speed="slow"))
    models.append(configured_mean_reversion(cfg.mean_reversion, speed="fast"))
    return models


def step_state(
    current: str,
    model: TransitionModel,
    *,
    rng: np.random.Generator,
) -> str:
    row = model.matrix[current]
    states = list(MARKET_PRICING_STATES)
    p = np.array([row[s] for s in states], dtype=float)
    p = p / p.sum()
    return str(rng.choice(states, p=p))


def evolve_state(
    initial: str,
    model: TransitionModel,
    *,
    horizon_years: int,
    rng: np.random.Generator,
) -> str:
    """Evolve for horizon_years annual steps; return terminal state."""
    s = initial
    for _ in range(max(0, horizon_years)):
        s = step_state(s, model, rng=rng)
    return s
