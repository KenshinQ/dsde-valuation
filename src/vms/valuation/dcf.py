"""FCFF DCF + Gordon TV (SPEC §11.1–11.2). TV-GORDON-v1."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.schemas.config import TerminalValueConfig
from vms.statements.cashflows import FCFFSeries, WACC, present_value
from vms.valuation.wacc import WACCInputs, as_wacc

INVALID_VALUATION_REASONS = (
    "WACC_G_MARGIN_FAIL",
    "TERMINAL_GROWTH_ABOVE_MAX",
    "NONFINITE_DCF",
    "EMPTY_FCFF",
    "NONPOSITIVE_SHARES",
    "BRIDGE_NONFINITE",
)


class DCFResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    invalid_reason: str | None = None
    wacc: float
    g: float
    fcff_values: list[float]
    years: list[int]
    pv_fcff: float | None
    fcff_n1: float | None
    tv: float | None
    pv_tv: float | None
    enterprise_value: float | None
    tv_fraction: float | None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def dcf_fcff(*, fcff: FCFFSeries, wacc_inputs: WACCInputs, tv_cfg: TerminalValueConfig,
             g: float | None = None) -> DCFResult:
    """End-of-year PV of forecast FCFF + Gordon TV on FCFF[n]*(1+g). Rejects invalid WACC-g."""
    g = tv_cfg.terminal_growth if g is None else g
    flags: list[str] = []
    assumptions = cite("TV-GORDON-v1", "WACC-CONSTRUCTION-v1", *wacc_inputs.assumptions)
    if not fcff.values:
        return DCFResult(valid=False, invalid_reason="EMPTY_FCFF", wacc=wacc_inputs.wacc, g=g,
                         fcff_values=[], years=list(fcff.years), pv_fcff=None, fcff_n1=None, tv=None,
                         pv_tv=None, enterprise_value=None, tv_fraction=None, flags=flags,
                         assumptions=assumptions)
    if g > tv_cfg.max_terminal_growth + 1e-15:
        return DCFResult(valid=False, invalid_reason="TERMINAL_GROWTH_ABOVE_MAX", wacc=wacc_inputs.wacc, g=g,
                         fcff_values=list(fcff.values), years=list(fcff.years), pv_fcff=None, fcff_n1=None,
                         tv=None, pv_tv=None, enterprise_value=None, tv_fraction=None, flags=flags,
                         assumptions=assumptions)
    margin = wacc_inputs.wacc - g
    if margin < tv_cfg.min_wacc_minus_g - 1e-15:
        return DCFResult(valid=False, invalid_reason="WACC_G_MARGIN_FAIL", wacc=wacc_inputs.wacc, g=g,
                         fcff_values=list(fcff.values), years=list(fcff.years), pv_fcff=None, fcff_n1=None,
                         tv=None, pv_tv=None, enterprise_value=None, tv_fraction=None,
                         flags=["NO_SILENT_DENOMINATOR_REPAIR"], assumptions=assumptions)
    rate = as_wacc(wacc_inputs)
    try:
        pv_fcff = present_value(fcff, rate)
        fcff_n = fcff.values[-1]
        fcff_n1 = fcff_n * (1.0 + g)
        tv = fcff_n1 / (wacc_inputs.wacc - g)
        n = len(fcff.values)
        pv_tv = tv / (1.0 + wacc_inputs.wacc) ** n
        ev = pv_fcff + pv_tv
    except Exception:  # noqa: BLE001
        return DCFResult(valid=False, invalid_reason="NONFINITE_DCF", wacc=wacc_inputs.wacc, g=g,
                         fcff_values=list(fcff.values), years=list(fcff.years), pv_fcff=None, fcff_n1=None,
                         tv=None, pv_tv=None, enterprise_value=None, tv_fraction=None, flags=flags,
                         assumptions=assumptions)
    if not all(math.isfinite(x) for x in (pv_fcff, fcff_n1, tv, pv_tv, ev)):
        return DCFResult(valid=False, invalid_reason="NONFINITE_DCF", wacc=wacc_inputs.wacc, g=g,
                         fcff_values=list(fcff.values), years=list(fcff.years), pv_fcff=None, fcff_n1=None,
                         tv=None, pv_tv=None, enterprise_value=None, tv_fraction=None, flags=flags,
                         assumptions=assumptions)
    tv_frac = pv_tv / ev if ev != 0 else math.nan
    if math.isfinite(tv_frac) and tv_frac > tv_cfg.tv_fraction_warning:
        flags.append("TV_FRACTION_HIGH")
    return DCFResult(valid=True, invalid_reason=None, wacc=wacc_inputs.wacc, g=g,
                     fcff_values=list(fcff.values), years=list(fcff.years), pv_fcff=pv_fcff, fcff_n1=fcff_n1,
                     tv=tv, pv_tv=pv_tv, enterprise_value=ev, tv_fraction=tv_frac, flags=sorted(flags),
                     assumptions=assumptions)
