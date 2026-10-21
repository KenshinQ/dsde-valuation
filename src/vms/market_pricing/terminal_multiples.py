"""Conditional terminal-multiple sampling (SPEC §14.4)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.market_pricing.config import MarketPricingConfig, TerminalMultipleFamilyConfig, default_market_pricing_config
from vms.methods.multiples.definitions import METRIC_DEFINITIONS, ClaimObject, get_definition


class TerminalMultipleDraw(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    metric_id: str
    market_pricing_state: str
    base_center: float | None
    state_scale: float | None
    multiple: float | None
    claim_object: str | None = None
    applies_ev_bridge: bool | None = None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def sample_terminal_multiple(
    *,
    metric_id: str,
    market_pricing_state: str,
    rng: np.random.Generator,
    config: MarketPricingConfig | None = None,
    profile_scale: float = 1.0,
) -> TerminalMultipleDraw:
    """Sample a terminal multiple conditional on metric family and market-pricing state."""
    cfg = config or default_market_pricing_config()
    assumptions = cite(
        "EXIT-PRICE-TERMINAL-MULTIPLE-v1",
        "MARKET-PRICING-SCHEMA-v1",
        "PEER-MULTIPLE-RELATIVE-v1",
    )
    if metric_id not in METRIC_DEFINITIONS:
        return TerminalMultipleDraw(
            valid=False,
            invalid_reason="UNKNOWN_METRIC_FAMILY",
            metric_id=metric_id,
            market_pricing_state=market_pricing_state,
            base_center=None,
            state_scale=None,
            multiple=None,
            assumptions=assumptions,
            flags=["UNKNOWN_METRIC"],
        )
    try:
        fam: TerminalMultipleFamilyConfig = cfg.family(metric_id)
    except KeyError:
        return TerminalMultipleDraw(
            valid=False,
            invalid_reason="METRIC_NOT_CONFIGURED",
            metric_id=metric_id,
            market_pricing_state=market_pricing_state,
            base_center=None,
            state_scale=None,
            multiple=None,
            assumptions=assumptions,
        )
    try:
        scale = cfg.state_scales.scale(market_pricing_state)
    except AttributeError:
        return TerminalMultipleDraw(
            valid=False,
            invalid_reason="UNKNOWN_MARKET_PRICING_STATE",
            metric_id=metric_id,
            market_pricing_state=market_pricing_state,
            base_center=fam.center,
            state_scale=None,
            multiple=None,
            assumptions=assumptions,
        )
    defn = get_definition(metric_id)
    center = fam.center * scale * float(profile_scale)
    # Lognormal around center
    draw = float(rng.lognormal(mean=math.log(center), sigma=fam.log_sigma))
    flags: list[str] = []
    if draw < fam.min_multiple:
        draw = fam.min_multiple
        flags.append("MULTIPLE_CLIPPED_LOW")
    if draw > fam.max_multiple:
        draw = fam.max_multiple
        flags.append("MULTIPLE_CLIPPED_HIGH")
    if not math.isfinite(draw) or draw <= 0:
        return TerminalMultipleDraw(
            valid=False,
            invalid_reason="NONFINITE_MULTIPLE",
            metric_id=metric_id,
            market_pricing_state=market_pricing_state,
            base_center=fam.center,
            state_scale=scale,
            multiple=None,
            assumptions=assumptions,
            flags=flags,
        )
    return TerminalMultipleDraw(
        valid=True,
        metric_id=metric_id,
        market_pricing_state=market_pricing_state,
        base_center=fam.center,
        state_scale=scale,
        multiple=draw,
        claim_object=defn.claim_object.value,
        applies_ev_bridge=defn.applies_ev_bridge,
        flags=flags,
        assumptions=assumptions,
        diagnostics={
            "scaled_center": center,
            "log_sigma": fam.log_sigma,
            "value_claim": defn.value_claim.value,
        },
    )


def metric_denominator_field(metric_id: str) -> str:
    return get_definition(metric_id).denominator_field


def metric_is_ev(metric_id: str) -> bool:
    return get_definition(metric_id).claim_object is ClaimObject.EV
