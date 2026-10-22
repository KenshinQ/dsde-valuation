"""Bridge PITSnapshot → residual-income inputs (R1/R2: real A-share FINANCIAL_INSTITUTION).

Design A+C: does **not** lift ``industry.unsupported`` / legacy industrial FCFF.

R2a defaults (``equity_basis="common"``):
  common_equity_0 = total_equity − minority − other_equity_instruments
  common NI from basic_eps × diluted shares (primary); P1 constant last-FY common NI as control
  dividends from em_sharebonus FY DPS × shares (not mixed CF interest field)
  real OCI when present; zeros only with zeros_explicit

Missing required deposit-taking FI fields for common basis → INELIGIBLE (no silent fill).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

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

BOOK_EQUITY_COMMON_RULE = (
    "book_equity_0 = common equity to ordinary shareholders = last FY total_equity "
    "- minority_interest - other_equity_instruments (preferred+perpetual). "
    "RIM-COMMON-EQUITY-v1; goodwill is sensitivity-only (not subtracted by default)."
)

NI_POLICY_P1 = "P1_CONSTANT_LAST_FY_COMMON_NET_INCOME"
NI_POLICY_P2 = "P2_CONSTANT_ROE_TIMES_BEGINNING_COMMON_EQUITY"
# R1 alias kept for docs / older callers reading ni_policy string on total basis
NI_POLICY = "P1_CONSTANT_LAST_FY_PARENT_NET_INCOME"
EquityBasis = Literal["common", "total"]

_ACTION_REPORT_RE = re.compile(
    r"^em:[^:]+:(?P<report>\d{4}-\d{2}-\d{2}):(?:cash|bonus)$"
)


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
    last_fy_dps: float | None = None
    common_equity_0: float | None = None
    total_equity_0: float | None = None
    goodwill_0: float | None = None
    tangible_common_equity_0: float | None = None
    te_rule: str = BOOK_EQUITY_COMMON_RULE
    ni_policy: str = NI_POLICY_P1
    equity_basis: str = "common"
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
    ii = h.value(last, "interest_income") if last is not None else None

    def _ratio(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return float(num) / float(den)

    return ProfileFeatureBundle(
        instrument_id=snap.instrument_id,
        as_of=as_of,
        revenue_cagr_3y=None,
        fcf_to_revenue=None,
        ebit_margin=None,
        ebit_margin_stdev_3y=None,
        net_income_to_revenue=_ratio(ni, rev),
        interest_income_to_revenue=_ratio(ii, rev),
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


def _oei_for_year(h: AnnualHistory, year: int) -> float | None:
    oei = h.value(year, "other_equity_instruments")
    if oei is not None:
        return float(oei)
    pref = h.value(year, "preferred_shares")
    perp = h.value(year, "perpetual_bond")
    if pref is None and perp is None:
        return None
    return float(pref or 0.0) + float(perp or 0.0)


def fy_dps_from_sharebonus(
    snap: PITSnapshot,
    *,
    fiscal_year: int,
) -> tuple[float | None, list[str]]:
    """Sum ordinary cash DPS for FY interim (06-30) + final (12-31) from em_sharebonus.

    Only events with announced_at.date() <= as_of local date. Returns (dps, flags).
    """
    as_of_d = local_date(snap.as_of)
    targets = {date(fiscal_year, 12, 31), date(fiscal_year, 6, 30)}
    total = 0.0
    n = 0
    flags: list[str] = []
    for ca in snap.corporate_actions:
        ev = ca.event
        if ev.action_type != "cash_dividend" or ev.cash_per_share is None:
            continue
        m = _ACTION_REPORT_RE.match(ev.action_id)
        if m is None:
            continue
        report = date.fromisoformat(m.group("report"))
        if report not in targets:
            continue
        announced = local_date(ev.announced_at) if isinstance(ev.announced_at, datetime) else ev.announced_at
        if announced > as_of_d:
            flags.append("DPS_SKIPPED_NOT_YET_ANNOUNCED")
            continue
        total += float(ev.cash_per_share)
        n += 1
    if n == 0:
        return None, flags
    return total, flags


def common_equity_components(
    h: AnnualHistory,
    *,
    year: int,
    zeros_explicit: bool,
) -> tuple[float | None, dict[str, float | None], list[str], str | None]:
    """Return (common_equity, components, flags, ineligible_reason)."""
    flags: list[str] = []
    te = h.value(year, "total_equity")
    if te is None:
        return None, {}, flags, "MISSING_BOOK_EQUITY"
    oei = _oei_for_year(h, year)
    if oei is None:
        return None, {"total_equity": float(te)}, flags, "MISSING_OTHER_EQUITY_INSTRUMENTS"
    mi = h.value(year, "minority_interest")
    if mi is None:
        if not zeros_explicit:
            return None, {"total_equity": float(te), "other_equity_instruments": float(oei)}, flags, \
                "MISSING_MINORITY_INTEREST"
        mi = 0.0
        flags.append("MINORITY_EQUITY_ASSUMED_ZERO")
    common = float(te) - float(mi) - float(oei)
    comps = {
        "total_equity": float(te),
        "minority_interest": float(mi),
        "other_equity_instruments": float(oei),
        "preferred_shares": h.value(year, "preferred_shares"),
        "perpetual_bond": h.value(year, "perpetual_bond"),
        "common_equity": common,
        "goodwill": h.value(year, "goodwill"),
    }
    return common, comps, flags, None


def common_ni_from_eps(
    h: AnnualHistory,
    snap: PITSnapshot,
    *,
    year: int,
) -> tuple[float | None, dict[str, float | None], str | None]:
    eps = h.value(year, "basic_eps")
    shares = _diluted_shares(snap)
    sh_pt = h.shares.get(year)
    if sh_pt is not None and sh_pt.value is not None and sh_pt.value > 0:
        shares = float(sh_pt.value)
    if eps is None:
        return None, {}, "MISSING_BASIC_EPS"
    if shares is None or shares <= 0:
        return None, {"basic_eps": float(eps)}, "MISSING_SHARES_FOR_COMMON_NI"
    ni = float(eps) * float(shares)
    return ni, {"basic_eps": float(eps), "shares_for_ni": float(shares), "common_ni": ni}, None


def rim_inputs_from_snapshot(
    snap: PITSnapshot,
    *,
    loaded: LoadedConfig,
    years: int | None = None,
    zeros_explicit: bool = True,
    equity_basis: EquityBasis = "common",
    ni_policy: Literal["P1", "P2_CONTROL_ONLY"] = "P1",
) -> RimBridgeResult:
    """Build rim_inputs from PIT annual history.

    Default equity_basis=common (R2a). Pass equity_basis=\"total\" for R1-compatible
    total_equity book (regression / control). Primary point NI for the single-path
    bridge remains P1 constant last-FY common NI; P2 distribution is R2b.
    """
    del ni_policy  # reserved; point bridge is always P1; P2 lives in distribution module
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
    ]
    assumption_ids = cite(
        "RIM-CLEAN-SURPLUS-v1",
        "RIM-COST-OF-EQUITY-v1",
        "NO-DOUBLE-EV-BRIDGE-v1",
        "RIM-REAL-PIT-BRIDGE-v1",
    )

    be_year, te0 = _last_fy_with(h, "total_equity")
    if te0 is None or be_year is None:
        return RimBridgeResult(
            ok=False,
            flags=["MISSING_BOOK_EQUITY"],
            assumption_labels=labels,
            assumption_ids=assumption_ids,
            equity_basis=equity_basis,
            ineligible_reason="MISSING_BOOK_EQUITY",
            detail="no FY total_equity in PIT annual history",
        )

    comps: dict[str, float | None] = {"total_equity": float(te0)}
    goodwill = h.value(be_year, "goodwill")
    if equity_basis == "common":
        assumption_ids = cite(
            "RIM-CLEAN-SURPLUS-v1",
            "RIM-COST-OF-EQUITY-v1",
            "NO-DOUBLE-EV-BRIDGE-v1",
            "RIM-REAL-PIT-BRIDGE-v1",
            "RIM-COMMON-EQUITY-v1",
        )
        be0, comps, cflags, inelig = common_equity_components(
            h, year=be_year, zeros_explicit=zeros_explicit,
        )
        flags.extend(cflags)
        if inelig or be0 is None:
            return RimBridgeResult(
                ok=False,
                flags=sorted(set(flags + [inelig or "MISSING_COMMON_EQUITY"])),
                assumption_labels=labels,
                assumption_ids=assumption_ids,
                book_equity_year=be_year,
                total_equity_0=float(te0),
                goodwill_0=None if goodwill is None else float(goodwill),
                equity_basis=equity_basis,
                te_rule=BOOK_EQUITY_COMMON_RULE,
                ineligible_reason=inelig or "MISSING_COMMON_EQUITY",
                detail=f"common-equity basis failed: {inelig}",
            )
        te_rule = BOOK_EQUITY_COMMON_RULE
        labels.append("ASSUMPTION:book_equity_common_ex_oei_minority")
        if be0 < 0:
            return RimBridgeResult(
                ok=False,
                flags=sorted(set(flags + ["NEGATIVE_BOOK_EQUITY"])),
                assumption_labels=labels,
                assumption_ids=assumption_ids,
                book_equity_year=be_year,
                total_equity_0=float(te0),
                common_equity_0=float(be0),
                goodwill_0=None if goodwill is None else float(goodwill),
                equity_basis=equity_basis,
                te_rule=te_rule,
                ineligible_reason="NEGATIVE_BOOK_EQUITY",
                detail=f"common_equity@{be_year}={be0}",
            )
    else:
        be0 = float(te0)
        te_rule = BOOK_EQUITY_TE_RULE
        labels.append("ASSUMPTION:book_equity_total_equity_legacy")
        if be0 < 0:
            return RimBridgeResult(
                ok=False,
                flags=["NEGATIVE_BOOK_EQUITY"],
                assumption_labels=labels,
                assumption_ids=assumption_ids,
                book_equity_year=be_year,
                total_equity_0=float(te0),
                equity_basis=equity_basis,
                te_rule=te_rule,
                ineligible_reason="NEGATIVE_BOOK_EQUITY",
                detail=f"total_equity@{be_year}={be0}",
            )

    ni: float | None
    ni_meta: dict[str, float | None] = {}
    if equity_basis == "common":
        ni, ni_meta, ni_err = common_ni_from_eps(h, snap, year=be_year)
        if ni is None:
            return RimBridgeResult(
                ok=False,
                flags=sorted(set(flags + [ni_err or "MISSING_COMMON_NI"])),
                assumption_labels=labels,
                assumption_ids=assumption_ids,
                book_equity_year=be_year,
                total_equity_0=float(te0),
                common_equity_0=float(be0) if be0 is not None else None,
                goodwill_0=None if goodwill is None else float(goodwill),
                equity_basis=equity_basis,
                te_rule=te_rule,
                ineligible_reason=ni_err or "MISSING_COMMON_NI",
                detail=f"common NI from EPS failed: {ni_err}",
            )
        flags.append("NI_FROM_BASIC_EPS_TIMES_SHARES")
        labels.append("ASSUMPTION:ni_common_from_basic_eps")
        assumption_ids = cite(
            "RIM-CLEAN-SURPLUS-v1",
            "RIM-COST-OF-EQUITY-v1",
            "NO-DOUBLE-EV-BRIDGE-v1",
            "RIM-REAL-PIT-BRIDGE-v1",
            "RIM-COMMON-EQUITY-v1",
            "RIM-NI-CONSTANT-LAST-FY-v1",
        )
        ni_year = be_year
        ni_policy_str = NI_POLICY_P1
    else:
        ni_year, ni = _last_fy_with(h, "parent_net_income")
        if ni is None or ni_year is None:
            return RimBridgeResult(
                ok=False,
                flags=["MISSING_PARENT_NET_INCOME"],
                assumption_labels=labels,
                assumption_ids=assumption_ids,
                book_equity_year=be_year,
                total_equity_0=float(te0),
                equity_basis=equity_basis,
                te_rule=te_rule,
                ineligible_reason="MISSING_PARENT_NET_INCOME",
                detail="no FY parent_net_income for P1 constant NI forecast",
            )
        flags.append("NI_CONSTANT_LAST_FY_ASSUMPTION")
        labels.append("ASSUMPTION:ni_constant_last_fy_parent_net_income")
        assumption_ids = cite(
            "RIM-CLEAN-SURPLUS-v1",
            "RIM-COST-OF-EQUITY-v1",
            "NO-DOUBLE-EV-BRIDGE-v1",
            "RIM-NI-CONSTANT-LAST-FY-v1",
            "RIM-REAL-PIT-BRIDGE-v1",
        )
        ni_policy_str = NI_POLICY

    flags.append("NI_CONSTANT_LAST_FY_ASSUMPTION")

    shares = _diluted_shares(snap)
    dps, dps_flags = fy_dps_from_sharebonus(snap, fiscal_year=be_year)
    flags.extend(dps_flags)
    div: float | None
    div_year: int | None = be_year
    if dps is not None and shares is not None and shares > 0:
        div = float(dps) * float(shares)
        flags.append("DIVIDENDS_FROM_SHAREBONUS_DPS")
        labels.append("ASSUMPTION:dividends_from_sharebonus_dps")
        assumption_ids = list(sorted(set(assumption_ids + cite("RIM-DPS-SHAREBONUS-v1"))))
    else:
        div_year, div = _last_fy_with(h, "dividends_paid")
        if div is not None:
            flags.append("DIVIDENDS_CONSTANT_LAST_FY_ASSUMPTION")
            flags.append("DIVIDENDS_PAID_MAY_INCLUDE_INTEREST")
            labels.append("ASSUMPTION:dividends_constant_last_fy_cf_fallback")

    oci_year, oci_val = _last_fy_with(h, "other_comprehensive_income")
    del oci_year
    oci_missing = oci_val is None
    issuance_missing = True
    oci_seq: list[float] | None = None
    if not oci_missing:
        oci_seq = [float(oci_val)] * years
        flags.append("OCI_CONSTANT_LAST_FY_ASSUMPTION")
        labels.append("ASSUMPTION:oci_constant_last_fy")
    if oci_missing or issuance_missing:
        if not zeros_explicit:
            raise RimBridgeError(
                "clean-surplus auxiliaries oci/net_issuance missing; refuse silent zeros "
                "(pass zeros_explicit=True to model as zero and flag CLEAN_SURPLUS_ZEROS_ASSUMED)"
            )
        flags.append("CLEAN_SURPLUS_ZEROS_ASSUMED")
        labels.append("ASSUMPTION:clean_surplus_oci_net_issuance_zeros_explicit")
        assumption_ids = list(sorted(set(assumption_ids + cite("RIM-CS-ZEROS-EXPLICIT-v1"))))
        if oci_missing:
            oci_seq = None

    if div is None:
        if not zeros_explicit:
            raise RimBridgeError(
                "dividends missing; refuse silent zeros "
                "(pass zeros_explicit=True or supply sharebonus DPS / dividends)"
            )
        div = 0.0
        flags.append("DIVIDENDS_ZEROS_ASSUMED")
        labels.append("ASSUMPTION:dividends_zeros_explicit")
    else:
        if "DIVIDENDS_FROM_SHAREBONUS_DPS" not in flags:
            labels.append("ASSUMPTION:dividends_constant_last_fy")
            flags.append("DIVIDENDS_CONSTANT_LAST_FY_ASSUMPTION")

    wacc = point_wacc(loaded)
    ke = float(wacc.cost_of_equity)
    g = float(loaded.config.terminal_value.terminal_growth)
    max_g = float(loaded.config.terminal_value.max_terminal_growth)
    min_margin = float(loaded.config.terminal_value.min_wacc_minus_g)

    forecast_years = [be_year + i for i in range(1, years + 1)]
    tangible = None
    if be0 is not None and goodwill is not None:
        tangible = float(be0) - float(goodwill)
        flags.append("GOODWILL_SENSITIVITY_AVAILABLE")
        if goodwill > 0:
            flags.append("GOODWILL_PRESENT")
            assumption_ids = list(sorted(set(assumption_ids + cite("RIM-GOODWILL-HAIRCUT-v1"))))

    rim_inputs: dict[str, Any] = {
        "book_equity_0": float(be0),
        "net_income": [float(ni)] * years,
        "dividends": [float(div)] * years,
        "zeros_explicit": True,
        "cost_of_equity": ke,
        "terminal_growth": g,
        "max_terminal_growth": max_g,
        "min_ke_minus_g": min_margin,
        "years": forecast_years,
        "diluted_shares": shares,
        "ni_policy": ni_policy_str,
        "te_rule": te_rule,
        "equity_basis": equity_basis,
        "book_equity_year": be_year,
        "ni_source_year": ni_year,
        "dividends_source_year": div_year,
        "dps": None if dps is None else float(dps),
        "ke_provenance": dict(wacc.provenance),
        "ev_bridge_applied": False,
        "total_equity_0": float(te0),
        "common_equity_0": float(be0) if equity_basis == "common" else None,
        "goodwill_0": None if goodwill is None else float(goodwill),
        "tangible_common_equity_0": tangible,
        "common_equity_components": {k: (None if v is None else float(v)) for k, v in comps.items()},
        "ni_meta": ni_meta,
        "control_p1_net_income": [float(ni)] * years,
    }
    if oci_seq is not None:
        rim_inputs["oci"] = oci_seq

    return RimBridgeResult(
        ok=True,
        rim_inputs=rim_inputs,
        flags=sorted(set(flags)),
        assumption_labels=labels,
        assumption_ids=assumption_ids,
        book_equity_year=be_year,
        last_fy_ni=float(ni),
        last_fy_dividends=float(div),
        last_fy_dps=None if dps is None else float(dps),
        common_equity_0=float(be0) if equity_basis == "common" else None,
        total_equity_0=float(te0),
        goodwill_0=None if goodwill is None else float(goodwill),
        tangible_common_equity_0=tangible,
        te_rule=te_rule,
        ni_policy=ni_policy_str,
        equity_basis=equity_basis,
        detail=(
            f"basis={equity_basis}; BE@{be_year}={be0}; TE={te0}; "
            f"NI@{ni_year}={ni} x {years}y; DPS={dps}; div={div}; "
            f"ke={ke}; g={g}; zeros_explicit=True"
        ),
    )
