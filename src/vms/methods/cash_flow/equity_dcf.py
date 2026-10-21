"""FCFE DCF and DDM at cost of equity (SPEC §12.2–12.3). Never substitutes WACC."""

from __future__ import annotations

import math
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.schemas.config import TerminalValueConfig
from vms.statements.cashflows import CostOfEquity, FCFESeries, present_value

INVALID_EQUITY_DCF_REASONS = (
    "KE_G_MARGIN_FAIL",
    "TERMINAL_GROWTH_ABOVE_MAX",
    "NONFINITE_DCF",
    "EMPTY_CASHFLOWS",
    "WACC_SUBSTITUTION_FORBIDDEN",
)

INVALID_DDM_REASONS = (
    "PAYOUT_NOT_MODELABLE",
    "ERRATIC_PAYOUT",
    "ABSENT_DIVIDENDS",
    "KE_G_MARGIN_FAIL",
    "TERMINAL_GROWTH_ABOVE_MAX",
    "GORDON_STABILITY_FAIL",
    "NONFINITE_DDM",
    "EMPTY_DIVIDENDS",
)


class EquityDCFResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    cost_of_equity: float
    g: float
    cashflows: list[float]
    years: list[int]
    pv_cashflows: float | None
    cf_n1: float | None
    tv: float | None
    pv_tv: float | None
    equity_value: float | None
    tv_fraction: float | None
    discount_rate_kind: str = "COST_OF_EQUITY"
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class DDMResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    cost_of_equity: float
    g: float
    dividends: list[float]
    years: list[int]
    pv_dividends: float | None
    div_n1: float | None
    tv: float | None
    pv_tv: float | None
    equity_value: float | None
    tv_fraction: float | None
    form: str = "multi_stage_gordon"
    discount_rate_kind: str = "COST_OF_EQUITY"
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PayoutModelability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    modelable: bool
    reason_codes: list[str] = Field(default_factory=list)
    detail: str = ""
    payout_ratios: list[float] = Field(default_factory=list)
    payout_cv: float | None = None
    mean_dividend: float | None = None


def payout_modelable(
    *,
    dividends: Sequence[float],
    net_income: Sequence[float] | None = None,
    max_payout_cv: float = 1.0,
    min_positive_dividend_years: int = 1,
) -> PayoutModelability:
    """Hard gate for DDM: absent/erratic payout → not modelable (no invented dividends)."""
    divs = [float(d) for d in dividends]
    if not divs or all(abs(d) < 1e-15 for d in divs):
        return PayoutModelability(
            modelable=False,
            reason_codes=["ABSENT_DIVIDENDS", "PAYOUT_NOT_MODELABLE"],
            detail="no positive dividend observations; refusing to invent a dividend stream",
            payout_ratios=[],
            mean_dividend=0.0,
        )
    positive_years = sum(1 for d in divs if d > 1e-15)
    if positive_years < min_positive_dividend_years:
        return PayoutModelability(
            modelable=False,
            reason_codes=["ABSENT_DIVIDENDS", "PAYOUT_NOT_MODELABLE"],
            detail=f"positive dividend years={positive_years} < min={min_positive_dividend_years}",
            mean_dividend=float(sum(divs) / len(divs)),
        )
    ratios: list[float] = []
    if net_income is not None and len(net_income) == len(divs):
        for d, ni in zip(divs, net_income):
            if ni is not None and abs(ni) > 1e-12 and d >= 0:
                ratios.append(d / ni)
    cv = None
    if len(ratios) >= 2:
        mean = sum(ratios) / len(ratios)
        var = sum((r - mean) ** 2 for r in ratios) / (len(ratios) - 1)
        cv = math.sqrt(var) / abs(mean) if abs(mean) > 1e-12 else float("inf")
        if not math.isfinite(cv) or cv > max_payout_cv:
            return PayoutModelability(
                modelable=False,
                reason_codes=["ERRATIC_PAYOUT", "PAYOUT_NOT_MODELABLE"],
                detail=f"payout CV={cv} exceeds max_payout_cv={max_payout_cv}",
                payout_ratios=ratios,
                payout_cv=cv if cv is not None and math.isfinite(cv) else None,
                mean_dividend=float(sum(divs) / len(divs)),
            )
    elif positive_years == 1 and len(divs) > 2:
        # Single spike in a longer window → treat as unstable without inventing a policy
        return PayoutModelability(
            modelable=False,
            reason_codes=["ERRATIC_PAYOUT", "PAYOUT_NOT_MODELABLE"],
            detail="only one positive dividend year in a multi-year window",
            mean_dividend=float(sum(divs) / len(divs)),
        )
    return PayoutModelability(
        modelable=True,
        reason_codes=[],
        detail="payout judged modelable under configured stability constraints",
        payout_ratios=ratios,
        payout_cv=cv,
        mean_dividend=float(sum(divs) / len(divs)),
    )


def dcf_fcfe(
    *,
    fcfe: FCFESeries,
    cost_of_equity: float,
    tv_cfg: TerminalValueConfig,
    g: float | None = None,
    discount_rate_kind: str = "COST_OF_EQUITY",
) -> EquityDCFResult:
    """End-of-year PV of FCFE + Gordon TV, discounted at cost of equity only."""
    g = tv_cfg.terminal_growth if g is None else g
    flags: list[str] = []
    assumptions = cite("TV-GORDON-v1", "FCFE-DCF-v1", "COST-OF-EQUITY-DISCOUNT-v1")
    if discount_rate_kind != "COST_OF_EQUITY":
        return EquityDCFResult(
            valid=False, invalid_reason="WACC_SUBSTITUTION_FORBIDDEN",
            cost_of_equity=cost_of_equity, g=g, cashflows=list(fcfe.values),
            years=list(fcfe.years), pv_cashflows=None, cf_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, flags=["NO_WACC_FOR_FCFE"], assumptions=assumptions,
        )
    if not fcfe.values:
        return EquityDCFResult(
            valid=False, invalid_reason="EMPTY_CASHFLOWS", cost_of_equity=cost_of_equity, g=g,
            cashflows=[], years=list(fcfe.years), pv_cashflows=None, cf_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, flags=flags, assumptions=assumptions,
        )
    if g > tv_cfg.max_terminal_growth + 1e-15:
        return EquityDCFResult(
            valid=False, invalid_reason="TERMINAL_GROWTH_ABOVE_MAX", cost_of_equity=cost_of_equity, g=g,
            cashflows=list(fcfe.values), years=list(fcfe.years), pv_cashflows=None, cf_n1=None,
            tv=None, pv_tv=None, equity_value=None, tv_fraction=None, flags=flags, assumptions=assumptions,
        )
    margin = cost_of_equity - g
    if margin < tv_cfg.min_wacc_minus_g - 1e-15:
        return EquityDCFResult(
            valid=False, invalid_reason="KE_G_MARGIN_FAIL", cost_of_equity=cost_of_equity, g=g,
            cashflows=list(fcfe.values), years=list(fcfe.years), pv_cashflows=None, cf_n1=None,
            tv=None, pv_tv=None, equity_value=None, tv_fraction=None,
            flags=["NO_SILENT_DENOMINATOR_REPAIR"], assumptions=assumptions,
        )
    rate = CostOfEquity(rate=cost_of_equity)
    try:
        pv_cf = present_value(fcfe, rate)
        cf_n = fcfe.values[-1]
        cf_n1 = cf_n * (1.0 + g)
        tv = cf_n1 / (cost_of_equity - g)
        n = len(fcfe.values)
        pv_tv = tv / (1.0 + cost_of_equity) ** n
        eq = pv_cf + pv_tv
    except Exception:  # noqa: BLE001
        return EquityDCFResult(
            valid=False, invalid_reason="NONFINITE_DCF", cost_of_equity=cost_of_equity, g=g,
            cashflows=list(fcfe.values), years=list(fcfe.years), pv_cashflows=None, cf_n1=None,
            tv=None, pv_tv=None, equity_value=None, tv_fraction=None, flags=flags, assumptions=assumptions,
        )
    if not all(math.isfinite(x) for x in (pv_cf, cf_n1, tv, pv_tv, eq)):
        return EquityDCFResult(
            valid=False, invalid_reason="NONFINITE_DCF", cost_of_equity=cost_of_equity, g=g,
            cashflows=list(fcfe.values), years=list(fcfe.years), pv_cashflows=None, cf_n1=None,
            tv=None, pv_tv=None, equity_value=None, tv_fraction=None, flags=flags, assumptions=assumptions,
        )
    tv_frac = pv_tv / eq if eq != 0 else math.nan
    if math.isfinite(tv_frac) and tv_frac > tv_cfg.tv_fraction_warning:
        flags.append("TV_FRACTION_HIGH")
    return EquityDCFResult(
        valid=True, invalid_reason=None, cost_of_equity=cost_of_equity, g=g,
        cashflows=list(fcfe.values), years=list(fcfe.years), pv_cashflows=pv_cf, cf_n1=cf_n1,
        tv=tv, pv_tv=pv_tv, equity_value=eq, tv_fraction=tv_frac, flags=sorted(flags),
        assumptions=assumptions,
    )


def ddm_equity(
    *,
    dividends: Sequence[float],
    years: Sequence[int],
    cost_of_equity: float,
    tv_cfg: TerminalValueConfig,
    g: float | None = None,
    allow_gordon: bool = True,
    net_income: Sequence[float] | None = None,
    max_payout_cv: float = 1.0,
) -> DDMResult:
    """Policy-dependent dividend discount at cost of equity; Gordon only under stability."""
    g = tv_cfg.terminal_growth if g is None else g
    divs = [float(d) for d in dividends]
    yrs = [int(y) for y in years]
    assumptions = cite("DDM-v1", "COST-OF-EQUITY-DISCOUNT-v1", "TV-GORDON-v1")
    flags: list[str] = []
    gate = payout_modelable(dividends=divs, net_income=net_income, max_payout_cv=max_payout_cv)
    if not gate.modelable:
        return DDMResult(
            valid=False, invalid_reason=gate.reason_codes[0], cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible",
            flags=list(gate.reason_codes), assumptions=assumptions,
        )
    if not divs:
        return DDMResult(
            valid=False, invalid_reason="EMPTY_DIVIDENDS", cost_of_equity=cost_of_equity, g=g,
            dividends=[], years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible", flags=flags, assumptions=assumptions,
        )
    if g > tv_cfg.max_terminal_growth + 1e-15:
        return DDMResult(
            valid=False, invalid_reason="TERMINAL_GROWTH_ABOVE_MAX", cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible", flags=flags, assumptions=assumptions,
        )
    margin = cost_of_equity - g
    if margin < tv_cfg.min_wacc_minus_g - 1e-15:
        return DDMResult(
            valid=False, invalid_reason="KE_G_MARGIN_FAIL", cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible",
            flags=["NO_SILENT_DENOMINATOR_REPAIR"], assumptions=assumptions,
        )
    # Gordon terminal only when last dividend positive and allow_gordon
    last = divs[-1]
    if not allow_gordon or last <= 0:
        return DDMResult(
            valid=False, invalid_reason="GORDON_STABILITY_FAIL", cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible",
            flags=["GORDON_REQUIRES_POSITIVE_STABLE_DIVIDEND"], assumptions=assumptions,
        )
    try:
        pv_div = sum(d / (1.0 + cost_of_equity) ** (i + 1) for i, d in enumerate(divs))
        div_n1 = last * (1.0 + g)
        tv = div_n1 / (cost_of_equity - g)
        n = len(divs)
        pv_tv = tv / (1.0 + cost_of_equity) ** n
        eq = pv_div + pv_tv
    except Exception:  # noqa: BLE001
        return DDMResult(
            valid=False, invalid_reason="NONFINITE_DDM", cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible", flags=flags, assumptions=assumptions,
        )
    if not all(math.isfinite(x) for x in (pv_div, div_n1, tv, pv_tv, eq)):
        return DDMResult(
            valid=False, invalid_reason="NONFINITE_DDM", cost_of_equity=cost_of_equity, g=g,
            dividends=divs, years=yrs, pv_dividends=None, div_n1=None, tv=None, pv_tv=None,
            equity_value=None, tv_fraction=None, form="ineligible", flags=flags, assumptions=assumptions,
        )
    tv_frac = pv_tv / eq if eq != 0 else math.nan
    if math.isfinite(tv_frac) and tv_frac > tv_cfg.tv_fraction_warning:
        flags.append("TV_FRACTION_HIGH")
    return DDMResult(
        valid=True, invalid_reason=None, cost_of_equity=cost_of_equity, g=g,
        dividends=divs, years=yrs, pv_dividends=pv_div, div_n1=div_n1, tv=tv, pv_tv=pv_tv,
        equity_value=eq, tv_fraction=tv_frac, form="multi_stage_gordon",
        flags=sorted(flags), assumptions=assumptions,
    )
