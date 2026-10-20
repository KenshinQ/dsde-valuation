"""Pathwise total shareholder return (DIVIDEND-NO-REINVEST-v1)."""

from __future__ import annotations

import math

from vms.assumptions import cite


def holding_period_return(*, value_per_share: float, cum_dps: float, entry_price: float
                          ) -> tuple[float | None, list[str]]:
    """R = (VPS_H + cum_DPS_H - P0) / P0. No dividend reinvestment; no buyback cash add-on."""
    flags: list[str] = []
    if not (math.isfinite(entry_price) and entry_price > 0):
        return None, ["NONPOSITIVE_ENTRY_PRICE"]
    if not (math.isfinite(value_per_share) and math.isfinite(cum_dps)):
        return None, ["NONFINITE_RETURN_INPUTS"]
    r = (value_per_share + cum_dps - entry_price) / entry_price
    if not math.isfinite(r):
        return None, ["NONFINITE_RETURN"]
    return r, flags


def annualized_geometric(*, holding_return: float, horizon_years: int) -> tuple[float | None, list[str]]:
    """(1+R)^(1/H)-1; ANNUALIZED-GEO-ENDYEAR-v1. Undefined when R <= -1."""
    if horizon_years < 1:
        return None, ["NONPOSITIVE_HORIZON"]
    if not math.isfinite(holding_return):
        return None, ["NONFINITE_RETURN"]
    if holding_return <= -1.0:
        return None, ["ANNUALIZED_UNDEFINED_TOTAL_LOSS"]
    return (1.0 + holding_return) ** (1.0 / horizon_years) - 1.0, []


def cite_return_assumptions() -> list[str]:
    return cite("DIVIDEND-NO-REINVEST-v1", "ANNUALIZED-GEO-ENDYEAR-v1", "ENTRY-PRICE-GRID-v1",
                "PRICE-REGIME-INVARIANT-v1", "HORIZON-EQUITY-REMAINING-PV-v1")
