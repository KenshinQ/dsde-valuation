"""Residual Income Model math (SPEC §12.4).

EquityValue = CurrentBookEquity + PV(future residual income)
ResidualIncome_t = NetIncome_t - CostOfEquity * BeginningBookEquity_t

Clean-surplus deviations must be assessed; if unassessable the method is ineligible
(never silently ignored). Book equity is not assumed clean-surplus without inputs.
"""

from __future__ import annotations

import math
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite

CLEAN_SURPLUS_TREATMENTS = (
    "MODELED",
    "ADJUSTED",
    "INELIGIBLE",
    "UNASSESSABLE",
)

INVALID_RIM_REASONS = (
    "CLEAN_SURPLUS_UNASSESSABLE",
    "CLEAN_SURPLUS_FAIL",
    "MISSING_BOOK_EQUITY",
    "NEGATIVE_BOOK_EQUITY",
    "KE_G_MARGIN_FAIL",
    "TERMINAL_GROWTH_ABOVE_MAX",
    "NONFINITE_RIM",
    "EMPTY_FORECAST",
    "MISSING_COST_OF_EQUITY",
    "MISSING_NET_INCOME_FORECAST",
)


class CleanSurplusReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assessable: bool
    treatment: Literal["MODELED", "ADJUSTED", "INELIGIBLE", "UNASSESSABLE"]
    deviation: float | None = None
    deviation_ratio: float | None = None
    beginning_book: float | None = None
    ending_book_implied: float | None = None
    ending_book_observed: float | None = None
    components: dict[str, float] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    detail: str = ""


class RimPathResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    invalid_reason: str | None = None
    cost_of_equity: float
    g: float
    book_equity_0: float | None
    residual_income: list[float] = Field(default_factory=list)
    book_path: list[float] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    pv_ri: float | None = None
    tv: float | None = None
    pv_tv: float | None = None
    equity_value: float | None = None
    value_per_share: float | None = None
    tv_fraction: float | None = None
    clean_surplus: CleanSurplusReport | None = None
    flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    diagnostics: dict = Field(default_factory=dict)


def assess_clean_surplus(
    *,
    beginning_book: float | None,
    net_income: float | None,
    dividends: float | None,
    net_issuance: float | None,
    oci: float | None,
    ending_book_observed: float | None,
    max_deviation_ratio: float = 0.05,
    zeros_explicit: bool = False,
    adjust_to_clean_surplus: bool = False,
) -> CleanSurplusReport:
    """Assess clean-surplus identity for one period (or terminal observed ending).

    Clean surplus: Ending = Beginning + NI - Div + NetIssuance + OCI.
    Missing NI/beginning, or missing Div/Issuance/OCI without ``zeros_explicit``,
    ⇒ UNASSESSABLE (method ineligible). Large unexplained deviation ⇒ INELIGIBLE
    unless ``adjust_to_clean_surplus`` (treatment ADJUSTED).
    """
    flags: list[str] = []
    if beginning_book is None or not math.isfinite(beginning_book):
        return CleanSurplusReport(
            assessable=False,
            treatment="UNASSESSABLE",
            detail="beginning book equity missing or non-finite",
            flags=["MISSING_BOOK_EQUITY"],
        )
    if net_income is None or not math.isfinite(net_income):
        return CleanSurplusReport(
            assessable=False,
            treatment="UNASSESSABLE",
            detail="net income missing; cannot assess clean surplus",
            flags=["MISSING_NET_INCOME"],
        )
    missing_aux: list[str] = []
    if dividends is None:
        missing_aux.append("dividends")
    if net_issuance is None:
        missing_aux.append("net_issuance")
    if oci is None:
        missing_aux.append("oci")
    if missing_aux and not zeros_explicit:
        return CleanSurplusReport(
            assessable=False,
            treatment="UNASSESSABLE",
            beginning_book=beginning_book,
            detail=(
                f"clean-surplus auxiliaries missing ({missing_aux}); "
                "pass explicit zeros via zeros_explicit=true to model as zero, "
                "otherwise method is ineligible"
            ),
            flags=["CLEAN_SURPLUS_UNASSESSABLE", *[f"MISSING_{x.upper()}" for x in missing_aux]],
        )
    if missing_aux and zeros_explicit:
        flags.append("CLEAN_SURPLUS_ZEROS_ASSUMED")
    div = 0.0 if dividends is None else float(dividends)
    iss = 0.0 if net_issuance is None else float(net_issuance)
    oci_v = 0.0 if oci is None else float(oci)
    implied = float(beginning_book) + float(net_income) - div + iss + oci_v
    components = {
        "beginning_book": float(beginning_book),
        "net_income": float(net_income),
        "dividends": div,
        "net_issuance": iss,
        "oci": oci_v,
        "ending_implied": implied,
    }
    if ending_book_observed is None:
        # Forward model only — clean surplus is the modeled identity
        return CleanSurplusReport(
            assessable=True,
            treatment="MODELED",
            beginning_book=float(beginning_book),
            ending_book_implied=implied,
            ending_book_observed=None,
            deviation=0.0,
            deviation_ratio=0.0,
            components=components,
            flags=flags,
            detail="ending book rolled forward under clean-surplus identity (MODELED)",
        )
    if not math.isfinite(ending_book_observed):
        return CleanSurplusReport(
            assessable=False,
            treatment="UNASSESSABLE",
            beginning_book=float(beginning_book),
            ending_book_implied=implied,
            detail="ending book observed is non-finite",
            flags=["NONFINITE_ENDING_BOOK"],
        )
    deviation = float(ending_book_observed) - implied
    scale = max(abs(float(beginning_book)), abs(float(ending_book_observed)), 1.0)
    ratio = abs(deviation) / scale
    components["ending_observed"] = float(ending_book_observed)
    components["deviation"] = deviation
    if ratio <= max_deviation_ratio:
        return CleanSurplusReport(
            assessable=True,
            treatment="MODELED",
            beginning_book=float(beginning_book),
            ending_book_implied=implied,
            ending_book_observed=float(ending_book_observed),
            deviation=deviation,
            deviation_ratio=ratio,
            components=components,
            flags=flags,
            detail=f"clean-surplus holds within tolerance ratio={ratio:.4f}",
        )
    if adjust_to_clean_surplus:
        flags.append("CLEAN_SURPLUS_ADJUSTED_TO_IMPLIED")
        return CleanSurplusReport(
            assessable=True,
            treatment="ADJUSTED",
            beginning_book=float(beginning_book),
            ending_book_implied=implied,
            ending_book_observed=float(ending_book_observed),
            deviation=deviation,
            deviation_ratio=ratio,
            components=components,
            flags=flags,
            detail=(
                f"deviation_ratio={ratio:.4f} exceeds {max_deviation_ratio}; "
                "using clean-surplus implied ending (ADJUSTED)"
            ),
        )
    flags.append("CLEAN_SURPLUS_FAIL")
    return CleanSurplusReport(
        assessable=False,
        treatment="INELIGIBLE",
        beginning_book=float(beginning_book),
        ending_book_implied=implied,
        ending_book_observed=float(ending_book_observed),
        deviation=deviation,
        deviation_ratio=ratio,
        components=components,
        flags=flags,
        detail=(
            f"clean-surplus deviation_ratio={ratio:.4f} exceeds {max_deviation_ratio}; "
            "method ineligible (set adjust_to_clean_surplus to model adjustment)"
        ),
    )


def residual_income_value(
    *,
    book_equity_0: float,
    net_income: Sequence[float],
    cost_of_equity: float,
    dividends: Sequence[float] | None = None,
    net_issuance: Sequence[float] | None = None,
    oci: Sequence[float] | None = None,
    years: Sequence[int] | None = None,
    terminal_growth: float = 0.0,
    max_terminal_growth: float = 0.05,
    min_ke_minus_g: float = 0.005,
    diluted_shares: float | None = None,
    ending_book_observed: float | None = None,
    zeros_explicit: bool = False,
    adjust_to_clean_surplus: bool = False,
    max_deviation_ratio: float = 0.05,
    goodwill: float | None = None,
    goodwill_haircut: float = 0.0,
) -> RimPathResult:
    """Multi-period RIM with Gordon terminal on continuing residual income."""
    assumptions = cite(
        "RIM-CLEAN-SURPLUS-v1",
        "RIM-COST-OF-EQUITY-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
    )
    flags: list[str] = []
    if cost_of_equity is None or not math.isfinite(cost_of_equity) or cost_of_equity <= -1:
        return RimPathResult(
            valid=False, invalid_reason="MISSING_COST_OF_EQUITY",
            cost_of_equity=float(cost_of_equity or 0.0), g=terminal_growth,
            book_equity_0=None, assumptions=assumptions,
        )
    if book_equity_0 is None or not math.isfinite(book_equity_0):
        return RimPathResult(
            valid=False, invalid_reason="MISSING_BOOK_EQUITY",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=None, assumptions=assumptions,
        )
    if book_equity_0 < 0:
        return RimPathResult(
            valid=False, invalid_reason="NEGATIVE_BOOK_EQUITY",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=book_equity_0, assumptions=assumptions,
            flags=["NEGATIVE_BOOK_EQUITY"],
        )
    ni = [float(x) for x in net_income]
    if not ni:
        return RimPathResult(
            valid=False, invalid_reason="EMPTY_FORECAST",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=book_equity_0, assumptions=assumptions,
        )
    if any(not math.isfinite(x) for x in ni):
        return RimPathResult(
            valid=False, invalid_reason="NONFINITE_RIM",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=book_equity_0, assumptions=assumptions,
        )
    n = len(ni)
    yrs = list(years) if years is not None else list(range(1, n + 1))
    if len(yrs) != n:
        return RimPathResult(
            valid=False, invalid_reason="EMPTY_FORECAST",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=book_equity_0, assumptions=assumptions,
            diagnostics={"detail": "years length mismatch"},
        )

    def _seq(seq: Sequence[float] | None, name: str) -> list[float] | None:
        if seq is None:
            return None
        out = [float(x) for x in seq]
        if len(out) != n:
            raise ValueError(f"{name} length {len(out)} != forecast length {n}")
        return out

    try:
        divs = _seq(dividends, "dividends")
        iss = _seq(net_issuance, "net_issuance")
        oci_s = _seq(oci, "oci")
    except ValueError as e:
        return RimPathResult(
            valid=False, invalid_reason="EMPTY_FORECAST",
            cost_of_equity=cost_of_equity, g=terminal_growth,
            book_equity_0=book_equity_0, assumptions=assumptions,
            diagnostics={"detail": str(e)},
        )

    # Historical / opening clean-surplus check when ending observed supplied (last period)
    # Also require auxiliaries assessable for the forecast horizon.
    if divs is None or iss is None or oci_s is None:
        if not zeros_explicit:
            cs = assess_clean_surplus(
                beginning_book=book_equity_0,
                net_income=ni[0],
                dividends=None if divs is None else divs[0],
                net_issuance=None if iss is None else iss[0],
                oci=None if oci_s is None else oci_s[0],
                ending_book_observed=ending_book_observed,
                max_deviation_ratio=max_deviation_ratio,
                zeros_explicit=False,
                adjust_to_clean_surplus=adjust_to_clean_surplus,
            )
            return RimPathResult(
                valid=False,
                invalid_reason="CLEAN_SURPLUS_UNASSESSABLE",
                cost_of_equity=cost_of_equity,
                g=terminal_growth,
                book_equity_0=book_equity_0,
                clean_surplus=cs,
                assumptions=assumptions,
                flags=list(cs.flags),
            )
        divs = divs or [0.0] * n
        iss = iss or [0.0] * n
        oci_s = oci_s or [0.0] * n
        flags.append("CLEAN_SURPLUS_ZEROS_ASSUMED")

    # Opening CS check vs optional observed ending (e.g. last reported FY)
    if ending_book_observed is not None:
        # Optional trailing reconciliation: observed ending vs year-1 clean-surplus roll.
        trailing = assess_clean_surplus(
            beginning_book=book_equity_0,
            net_income=ni[0],
            dividends=divs[0],
            net_issuance=iss[0],
            oci=oci_s[0],
            ending_book_observed=ending_book_observed,
            max_deviation_ratio=max_deviation_ratio,
            zeros_explicit=True,
            adjust_to_clean_surplus=adjust_to_clean_surplus,
        )
        if trailing.treatment == "UNASSESSABLE":
            return RimPathResult(
                valid=False, invalid_reason="CLEAN_SURPLUS_UNASSESSABLE",
                cost_of_equity=cost_of_equity, g=terminal_growth,
                book_equity_0=book_equity_0, clean_surplus=trailing,
                assumptions=assumptions, flags=list(trailing.flags),
            )
        if trailing.treatment == "INELIGIBLE":
            return RimPathResult(
                valid=False, invalid_reason="CLEAN_SURPLUS_FAIL",
                cost_of_equity=cost_of_equity, g=terminal_growth,
                book_equity_0=book_equity_0, clean_surplus=trailing,
                assumptions=assumptions, flags=list(trailing.flags),
            )
        flags.extend(trailing.flags)
        cs_report = trailing
    else:
        cs_report = assess_clean_surplus(
            beginning_book=book_equity_0,
            net_income=ni[0],
            dividends=divs[0],
            net_issuance=iss[0],
            oci=oci_s[0],
            ending_book_observed=None,
            zeros_explicit=True,
        )
        flags.extend(cs_report.flags)

    g = float(terminal_growth)
    if g > max_terminal_growth:
        return RimPathResult(
            valid=False, invalid_reason="TERMINAL_GROWTH_ABOVE_MAX",
            cost_of_equity=cost_of_equity, g=g, book_equity_0=book_equity_0,
            clean_surplus=cs_report, assumptions=assumptions, flags=flags,
        )
    if cost_of_equity - g < min_ke_minus_g:
        return RimPathResult(
            valid=False, invalid_reason="KE_G_MARGIN_FAIL",
            cost_of_equity=cost_of_equity, g=g, book_equity_0=book_equity_0,
            clean_surplus=cs_report, assumptions=assumptions,
            flags=flags + ["NO_SILENT_DENOMINATOR_REPAIR"],
        )

    be = float(book_equity_0)
    if goodwill is not None and goodwill > 0:
        flags.append("GOODWILL_PRESENT")
        if goodwill_haircut > 0:
            be = be - float(goodwill) * float(goodwill_haircut)
            flags.append("GOODWILL_HAIRCUT_APPLIED")
            assumptions = cite(
                "RIM-CLEAN-SURPLUS-v1", "RIM-COST-OF-EQUITY-v1",
                "NO-DOUBLE-EV-BRIDGE-v1", "RIM-GOODWILL-HAIRCUT-v1",
            )
        else:
            flags.append("GOODWILL_UNHAIRCUTTED")

    book_path = [be]
    ri_list: list[float] = []
    for t in range(n):
        beg = book_path[-1]
        ri = ni[t] - cost_of_equity * beg
        ri_list.append(ri)
        end = beg + ni[t] - divs[t] + iss[t] + oci_s[t]
        book_path.append(end)

    pv_ri = sum(ri_list[i] / (1.0 + cost_of_equity) ** (i + 1) for i in range(n))
    # Terminal: continuing RI grows at g from last RI
    ri_n1 = ri_list[-1] * (1.0 + g)
    tv = ri_n1 / (cost_of_equity - g)
    pv_tv = tv / (1.0 + cost_of_equity) ** n
    equity = be + pv_ri + pv_tv
    if not all(math.isfinite(x) for x in (pv_ri, tv, pv_tv, equity)):
        return RimPathResult(
            valid=False, invalid_reason="NONFINITE_RIM",
            cost_of_equity=cost_of_equity, g=g, book_equity_0=book_equity_0,
            residual_income=ri_list, book_path=book_path, years=list(yrs),
            clean_surplus=cs_report, assumptions=assumptions, flags=flags,
        )
    tv_frac = abs(pv_tv) / abs(equity) if equity != 0 else None
    if tv_frac is not None and tv_frac > 0.75:
        flags.append("TV_FRACTION_HIGH")
    vps = (equity / diluted_shares) if diluted_shares and diluted_shares > 0 else None
    return RimPathResult(
        valid=True,
        invalid_reason=None,
        cost_of_equity=cost_of_equity,
        g=g,
        book_equity_0=be,
        residual_income=ri_list,
        book_path=book_path,
        years=list(yrs),
        pv_ri=pv_ri,
        tv=tv,
        pv_tv=pv_tv,
        equity_value=equity,
        value_per_share=vps,
        tv_fraction=tv_frac,
        clean_surplus=cs_report,
        flags=sorted(set(flags)),
        assumptions=assumptions,
        diagnostics={
            "net_income": list(ni),
            "dividends": list(divs),
            "net_issuance": list(iss),
            "oci": list(oci_s),
            "ev_bridge_applied": False,
            "formula": "EquityValue = BookEquity_0 + PV(RI) + PV(TV_RI)",
        },
    )
