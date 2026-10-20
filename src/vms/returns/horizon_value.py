"""Equity value at intermediate horizons from remaining FCFF PV (HORIZON-EQUITY-REMAINING-PV-v1)."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.equity_bridge.bridge import BridgeResult, bridge_ev_to_equity
from vms.schemas.config import LoadedConfig, TerminalValueConfig
from vms.statements.paths import FinancialPathRecord
from vms.valuation.wacc import WACCInputs


class HorizonEquity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    invalid_reason: str | None = None
    horizon_years: int
    calendar_year: int | None
    wacc: float
    g: float
    enterprise_value: float | None
    remaining_pv_fcff: float | None
    pv_tv: float | None
    tv: float | None
    bridge: BridgeResult | None = None
    value_per_share: float | None = None
    cum_dps: float | None = None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def _item(rec: FinancialPathRecord, name: str, year: int) -> float | None:
    if rec.projection is None:
        return None
    tv = rec.projection.items.get(f"{name}@{year}")
    return None if tv is None else tv.value


def _minority(rec: FinancialPathRecord, year: int, cfg) -> float:
    if cfg.valuation.minority_interest_book is not None:
        return float(cfg.valuation.minority_interest_book)
    te = _item(rec, "total_equity", year)
    pni = _item(rec, "parent_net_income", year)
    ni = _item(rec, "net_income", year)
    if te is None:
        return 0.0
    if ni and abs(ni) > 1e-12 and pni is not None:
        return max(te * (1.0 - pni / ni), 0.0)
    return 0.0


def enterprise_value_at_horizon(*, fcff_values: list[float], wacc: float, g: float,
                                horizon_index: int, min_wacc_minus_g: float,
                                max_terminal_growth: float) -> tuple[bool, str | None, dict[str, float | None], list[str]]:
    """horizon_index is 1-based year index within the forecast (1..n). At n, EV=TV only."""
    flags: list[str] = []
    n = len(fcff_values)
    empty = {"enterprise_value": None, "remaining_pv_fcff": None, "pv_tv": None, "tv": None}
    if n == 0 or horizon_index < 1 or horizon_index > n:
        return False, "HORIZON_OUT_OF_RANGE", empty, flags
    if g > max_terminal_growth + 1e-15:
        return False, "TERMINAL_GROWTH_ABOVE_MAX", empty, flags
    if wacc - g < min_wacc_minus_g - 1e-15:
        return False, "WACC_G_MARGIN_FAIL", empty, ["NO_SILENT_DENOMINATOR_REPAIR"]
    fcff_n = fcff_values[-1]
    tv = fcff_n * (1.0 + g) / (wacc - g)
    k = horizon_index
    if k == n:
        rem = 0.0
        pv_tv = tv
        ev = tv
    else:
        rem = 0.0
        for j in range(k + 1, n + 1):
            rem += fcff_values[j - 1] / (1.0 + wacc) ** (j - k)
        pv_tv = tv / (1.0 + wacc) ** (n - k)
        ev = rem + pv_tv
    if not all(math.isfinite(x) for x in (ev, rem, pv_tv, tv)):
        return False, "NONFINITE_DCF", empty, flags
    return True, None, {"enterprise_value": ev, "remaining_pv_fcff": rem, "pv_tv": pv_tv, "tv": tv}, flags


def cumulative_dps(rec: FinancialPathRecord, horizon_index: int) -> float | None:
    """Sum of cash DPS over years 1..H without reinvestment (DIVIDEND-NO-REINVEST-v1)."""
    if rec.projection is None or horizon_index < 1:
        return None
    years = list(rec.projection.years)
    if horizon_index > len(years):
        return None
    total = 0.0
    for y in years[:horizon_index]:
        ys = str(y)
        div = rec.dividends.get(ys, 0.0)
        sh = rec.shares.get(ys)
        if sh is None or not math.isfinite(sh) or sh <= 0:
            return None
        if not math.isfinite(div):
            return None
        total += div / sh
    return total


def equity_at_horizon(*, rec: FinancialPathRecord, wacc_inputs: WACCInputs, loaded: LoadedConfig,
                      horizon_index: int) -> HorizonEquity:
    assumptions = cite("HORIZON-EQUITY-REMAINING-PV-v1", "DIVIDEND-NO-REINVEST-v1", "EV-EQUITY-BRIDGE-v1",
                       "TV-GORDON-v1", "WACC-CONSTRUCTION-v1")
    tv_cfg: TerminalValueConfig = loaded.config.terminal_value
    if rec.status != "VALID" or rec.projection is None:
        return HorizonEquity(valid=False, invalid_reason=rec.invalid_reason or rec.status,
                             horizon_years=horizon_index, calendar_year=None, wacc=wacc_inputs.wacc,
                             g=tv_cfg.terminal_growth, enterprise_value=None, remaining_pv_fcff=None,
                             pv_tv=None, tv=None, assumptions=assumptions)
    years = list(rec.projection.years)
    ok, reason, parts, flags = enterprise_value_at_horizon(
        fcff_values=[rec.fcff[str(y)] for y in years], wacc=wacc_inputs.wacc, g=tv_cfg.terminal_growth,
        horizon_index=horizon_index, min_wacc_minus_g=tv_cfg.min_wacc_minus_g,
        max_terminal_growth=tv_cfg.max_terminal_growth)
    cal = years[horizon_index - 1] if 1 <= horizon_index <= len(years) else None
    if not ok:
        return HorizonEquity(valid=False, invalid_reason=reason, horizon_years=horizon_index,
                             calendar_year=cal, wacc=wacc_inputs.wacc, g=tv_cfg.terminal_growth,
                             enterprise_value=None, remaining_pv_fcff=None, pv_tv=None, tv=None,
                             flags=flags, assumptions=assumptions)
    assert cal is not None
    cash = _item(rec, "cash", cal) or 0.0
    debt = _item(rec, "interest_bearing_debt", cal) or 0.0
    shares = _item(rec, "diluted_shares", cal) or 0.0
    minority = _minority(rec, cal, loaded.config)
    br = bridge_ev_to_equity(
        enterprise_value=float(parts["enterprise_value"]), cash=cash, debt=debt,
        lease_debt_like=loaded.config.valuation.lease_debt_like, minority_interest_book=minority,
        other_senior_claims=loaded.config.valuation.other_senior_claims, diluted_shares=shares)
    flags = list(flags) + list(br.flags)
    if not br.valid:
        return HorizonEquity(valid=False, invalid_reason=br.invalid_reason, horizon_years=horizon_index,
                             calendar_year=cal, wacc=wacc_inputs.wacc, g=tv_cfg.terminal_growth,
                             enterprise_value=parts["enterprise_value"], remaining_pv_fcff=parts["remaining_pv_fcff"],
                             pv_tv=parts["pv_tv"], tv=parts["tv"], bridge=br, flags=sorted(set(flags)),
                             assumptions=assumptions)
    dps = cumulative_dps(rec, horizon_index)
    if dps is None:
        return HorizonEquity(valid=False, invalid_reason="DPS_UNDEFINED", horizon_years=horizon_index,
                             calendar_year=cal, wacc=wacc_inputs.wacc, g=tv_cfg.terminal_growth,
                             enterprise_value=parts["enterprise_value"], remaining_pv_fcff=parts["remaining_pv_fcff"],
                             pv_tv=parts["pv_tv"], tv=parts["tv"], bridge=br,
                             value_per_share=br.value_per_share, flags=sorted(set(flags)),
                             assumptions=assumptions)
    return HorizonEquity(
        valid=True, horizon_years=horizon_index, calendar_year=cal, wacc=wacc_inputs.wacc,
        g=tv_cfg.terminal_growth, enterprise_value=parts["enterprise_value"],
        remaining_pv_fcff=parts["remaining_pv_fcff"], pv_tv=parts["pv_tv"], tv=parts["tv"],
        bridge=br, value_per_share=br.value_per_share, cum_dps=dps, flags=sorted(set(flags)),
        assumptions=assumptions)
