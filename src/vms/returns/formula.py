"""Pathwise total shareholder return conventions (DIVIDEND-NO-REINVEST-v1 / Track B)."""

from __future__ import annotations

import math

from vms.assumptions import cite


def holding_period_return(
    *, value_per_share: float, cum_dps: float, entry_price: float
) -> tuple[float | None, list[str]]:
    """R = (TerminalPrice + ShareholderDistributions - P0) / P0.

    ``value_per_share`` is the terminal price (Track B exit or legacy horizon VPS).
    ``cum_dps`` is cumulative cash DPS without reinvestment. No buyback cash add-on.
    """
    flags: list[str] = []
    if not (math.isfinite(entry_price) and entry_price > 0):
        return None, ["NONPOSITIVE_ENTRY_PRICE"]
    if not (math.isfinite(value_per_share) and math.isfinite(cum_dps)):
        return None, ["NONFINITE_RETURN_INPUTS"]
    r = (value_per_share + cum_dps - entry_price) / entry_price
    if not math.isfinite(r):
        return None, ["NONFINITE_RETURN"]
    return r, flags


def return_components(
    *, terminal_price: float, shareholder_distributions: float, entry_price: float
) -> dict[str, float | None]:
    """Decompose R into price and distribution components (same P0)."""
    if not (math.isfinite(entry_price) and entry_price > 0):
        return {"price_component": None, "distribution_component": None, "total": None}
    price_c = (terminal_price - entry_price) / entry_price
    dist_c = shareholder_distributions / entry_price
    total = price_c + dist_c
    return {
        "price_component": float(price_c) if math.isfinite(price_c) else None,
        "distribution_component": float(dist_c) if math.isfinite(dist_c) else None,
        "total": float(total) if math.isfinite(total) else None,
    }


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
    """Legacy 0.1 / Track-A-horizon return citations."""
    return cite(
        "DIVIDEND-NO-REINVEST-v1",
        "ANNUALIZED-GEO-ENDYEAR-v1",
        "ENTRY-PRICE-GRID-v1",
        "PRICE-REGIME-INVARIANT-v1",
        "HORIZON-EQUITY-REMAINING-PV-v1",
    )


def cite_return_assumptions_phase10() -> list[str]:
    """VMS-0.2 Phase 10 Track B citations."""
    return cite(
        "TRACK-B-EXIT-RETURN-v1",
        "SHAREHOLDER-DIST-CASH-DPS-ONLY-v1",
        "NO-DOUBLE-COUNT-CA-v1",
        "DIVIDEND-NO-REINVEST-v1",
        "ANNUALIZED-GEO-ENDYEAR-v1",
        "ENTRY-PRICE-GRID-v1",
        "PRICE-REGIME-INVARIANT-v1",
        "RETURN-RECOMPUTE-ON-POSTERIOR-CHANGE-v1",
        "MARKET-PRICING-NO-SILENT-INTRINSIC-EXIT-v1",
        "PHASE10-DSDE-PUBLIC-CONTRACT-v1",
    )
