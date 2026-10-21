"""Bridge PITSnapshot → residual-income inputs (R1: real A-share FINANCIAL_INSTITUTION).

Design A+C: does **not** lift ``industry.unsupported`` / legacy industrial FCFF.
Book equity uses documented FY total_equity rule; NI policy P1 = constant last-FY
parent_net_income (ASSUMPTION). Missing OCI / net_issuance require
``zeros_explicit=True`` (flag ``CLEAN_SURPLUS_ZEROS_ASSUMED``) — never silent zeros.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vms.assumptions import cite
from vms.drivers.history import AnnualHistory, extract_annual
from vms.methods.cash_flow.common import point_wacc
from vms.pit.snapshot import local_date
from vms.pit.snapshot import PITSnapshot
from vms.profiles.features import ProfileFeatureBundle
from vms.schemas.config import LoadedConfig

BOOK_EQUITY_TE_RULE = (
    "book_equity_0 = last complete fiscal-year total_equity (period_end 12-31) "
    "present in PIT annual history at as_of via extract_annual / ANNUAL-BASE-v1. "
    "Not interim (H1) equity; consolidated total_equity as reported (includes "
    "minority interest when the source field does)."
)

NI_POLICY = "P1_CONSTANT_LAST_FY_PARENT_NET_INCOME"


class RimBridgeError(ValueError):
    """Hard refusal (e.g. silent CS zeros requested)."""


class RimBridgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    rim_inputs: dict[str, Any] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    assumption_labels: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    book_equity_year: int | None = None
    last_fy_ni: float | None = None
    last_fy_dividends: float | None = None
    te_rule: str = BOOK_EQUITY_TE_RULE
    ni_policy: str = NI_POLICY
    ineligible_reason: str | None = None
    detail: str = ""


def features_from_snapshot(snap: PITSnapshot) -> ProfileFeatureBundle:
    """Build classifier features from PIT annual history + industry aux.

    FINANCIAL_INSTITUTION names often lack interest_income in the canonical field set;
    industry-aux keywords alone yield FINANCIAL_INSTITUTION with low_confidence (allowed).
    Does not invent ratios that would push MATURE_OPERATING.
    """
    h = extract_annual(snap)
    as_of = local_date(snap.as_of).isoformat()
    cls = snap.classification
    industry = cls.industry if cls is not None else None
    scheme = cls.scheme if cls is not None else None

    last = h.years[-1] if h.years else None
    te = h.value(last, "total_equity") if last is not None else None
    ni = h.value(last, "parent_net_income") if last is not None else None
    rev = h.value(last, "revenue") if last is not None else None
    ta = h.value(last, "total_assets") if last is not None else None
    tl = h.value(last, "total_liabilities") if last is not None else None
    div = h.value(last, "dividends_paid") if last is not None else None
    debt = h.value(last, "interest_bearing_debt") if last is not None else None
    cash = h.value(last, "cash") if last is not None else None

    def _ratio(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return float(num) / float(den)

    # Do not fabricate FCF / EBIT margins (would risk MATURE_OPERATING hard-class).
    return ProfileFeatureBundle(
        instrument_id=snap.instrument_id,
        as_of=as_of,
        revenue_cagr_3y=None,
        fcf_to_revenue=None,
        ebit_margin=None,
        ebit_margin_stdev_3y=None,
        net_income_to_revenue=_ratio(ni, rev),
        interest_income_to_revenue=None,  # field usually absent on A-share ingest
        financial_assets_to_assets=None,
        investment_assets_to_assets=None,
        equity_method_income_to_pretax=None,
        ppe_to_assets=None,
        debt_to_assets=_ratio(debt, ta) if debt is not None else _ratio(tl, ta),
        cash_to_assets=_ratio(cash, ta),
        net_cash_to_assets=None,
        dividend_payout=_ratio(div, ni),
        book_equity=te,
        n_segments=None,
        has_listed_subsidiaries=None,
        history_years=float(len(h.years)) if h.years else None,
        industry_scheme=scheme,
        industry_name=industry,
        low_data_quality=not bool(snap.pit_complete),
        fixture_id=None,
    )


def _last_fy_with(h: AnnualHistory, field: str) -> tuple[int | None, float | None]:
    for y in reversed(h.years):
        v = h.value(y, field)
        if v is not None:
            return y, float(v)
    return None, None


def _diluted_shares(snap: PITSnapshot) -> float | None:
    obs = [m for m in snap.market if m.shares_outstanding is not None and m.shares_outstanding > 0]
    if not obs:
        return None
    return float(obs[-1].shares_outstanding)


def rim_inputs_from_snapshot(
    snap: PITSnapshot,
    *,
    loaded: LoadedConfig,
    years: int | None = None,
    zeros_explicit: bool = True,
) -> RimBridgeResult:
    """Build rim_inputs from PIT annual history (P1 NI + explicit CS zeros policy)."""
    if years is None:
        years = int(loaded.config.projection.default_years)
    if years <= 0:
        raise RimBridgeError(f"years must be > 0 (got {years})")

    h = extract_annual(snap)
    flags: list[str] = []
    labels: list[str] = [
        "INVESTMENT_VALUE_NOT_ESTABLISHED",
        "ASSUMPTION:ke_from_config_wacc",
        "ASSUMPTION:terminal_growth_from_config",
        "ASSUMPTION:ni_constant_last_fy_parent_net_income",
    ]
    assumption_ids = cite(
        "RIM-CLEAN-SURPLUS-v1",
        "RIM-COST-OF-EQUITY-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
        "RIM-NI-CONSTANT-LAST-FY-v1",
        "RIM-REAL-PIT-BRIDGE-v1",
    )

    be_year, be0 = _last_fy_with(h, "total_equity")
    if be0 is None or be_year is None:
        return RimBridgeResult(
            ok=False,
            flags=["MISSING_BOOK_EQUITY"],
            assumption_labels=labels,
            assumption_ids=assumption_ids,
            ineligible_reason="MISSING_BOOK_EQUITY",
            detail="no FY total_equity in PIT annual history",
        )
    if be0 < 0:
        return RimBridgeResult(
            ok=False,
            flags=["NEGATIVE_BOOK_EQUITY"],
            assumption_labels=labels,
            assumption_ids=assumption_ids,
            book_equity_year=be_year,
            ineligible_reason="NEGATIVE_BOOK_EQUITY",
            detail=f"total_equity@{be_year}={be0}",
        )

    ni_year, ni = _last_fy_with(h, "parent_net_income")
    if ni is None or ni_year is None:
        return RimBridgeResult(
            ok=False,
            flags=["MISSING_PARENT_NET_INCOME"],
            assumption_labels=labels,
            assumption_ids=assumption_ids,
            book_equity_year=be_year,
            ineligible_reason="MISSING_PARENT_NET_INCOME",
            detail="no FY parent_net_income for P1 constant NI forecast",
        )
    flags.append("NI_CONSTANT_LAST_FY_ASSUMPTION")

    div_year, div = _last_fy_with(h, "dividends_paid")
    # OCI / net_issuance: not in canonical A-share field set today
    oci_missing = True
    issuance_missing = True
    if oci_missing or issuance_missing:
        if not zeros_explicit:
            raise RimBridgeError(
                "clean-surplus auxiliaries oci/net_issuance missing; refuse silent zeros "
                "(pass zeros_explicit=True to model as zero and flag CLEAN_SURPLUS_ZEROS_ASSUMED)"
            )
        flags.append("CLEAN_SURPLUS_ZEROS_ASSUMED")
        labels.append("ASSUMPTION:clean_surplus_oci_net_issuance_zeros_explicit")
        assumption_ids = cite(
            "RIM-CLEAN-SURPLUS-v1",
            "RIM-COST-OF-EQUITY-v1",
            "NO-DOUBLE-EV-BRIDGE-v1",
            "RIM-NI-CONSTANT-LAST-FY-v1",
            "RIM-REAL-PIT-BRIDGE-v1",
            "RIM-CS-ZEROS-EXPLICIT-v1",
        )

    if div is None:
        if not zeros_explicit:
            raise RimBridgeError(
                "dividends_paid missing; refuse silent zeros "
                "(pass zeros_explicit=True or supply dividends)"
            )
        div = 0.0
        flags.append("DIVIDENDS_ZEROS_ASSUMED")
        labels.append("ASSUMPTION:dividends_zeros_explicit")
    else:
        labels.append("ASSUMPTION:dividends_constant_last_fy")
        flags.append("DIVIDENDS_CONSTANT_LAST_FY_ASSUMPTION")

    wacc = point_wacc(loaded)
    ke = float(wacc.cost_of_equity)
    g = float(loaded.config.terminal_value.terminal_growth)
    max_g = float(loaded.config.terminal_value.max_terminal_growth)
    min_margin = float(loaded.config.terminal_value.min_wacc_minus_g)
    shares = _diluted_shares(snap)

    forecast_years = [be_year + i for i in range(1, years + 1)]
    # Omit oci/net_issuance sequences (unknown in PIT) — zeros_explicit makes math
    # flag CLEAN_SURPLUS_ZEROS_ASSUMED rather than silently inventing zeros upstream.
    rim_inputs: dict[str, Any] = {
        "book_equity_0": be0,
        "net_income": [float(ni)] * years,
        "dividends": [float(div)] * years,
        "zeros_explicit": True,
        "cost_of_equity": ke,
        "terminal_growth": g,
        "max_terminal_growth": max_g,
        "min_ke_minus_g": min_margin,
        "years": forecast_years,
        "diluted_shares": shares,
        "ni_policy": NI_POLICY,
        "te_rule": BOOK_EQUITY_TE_RULE,
        "book_equity_year": be_year,
        "ni_source_year": ni_year,
        "dividends_source_year": div_year,
        "ke_provenance": dict(wacc.provenance),
        "ev_bridge_applied": False,
    }
    return RimBridgeResult(
        ok=True,
        rim_inputs=rim_inputs,
        flags=sorted(set(flags)),
        assumption_labels=labels,
        assumption_ids=assumption_ids,
        book_equity_year=be_year,
        last_fy_ni=float(ni),
        last_fy_dividends=float(div),
        detail=(
            f"TE@{be_year}={be0}; NI@{ni_year}={ni} x {years}y; "
            f"ke={ke}; g={g}; zeros_explicit=True"
        ),
    )
