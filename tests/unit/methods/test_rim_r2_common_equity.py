"""R2a: common-equity basis, EPS common NI, sharebonus DPS."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.from_snapshot import (
    BOOK_EQUITY_COMMON_RULE,
    RimBridgeError,
    fy_dps_from_sharebonus,
    rim_inputs_from_snapshot,
)
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot
from vms.schemas import (
    CorporateActionEvent,
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
INST = "000001.SZ"
SHARES = 1.9405918198e10


def _ts(d: str, hh: int = 18) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(period_end: str, field: str, value, pub: str) -> FinancialObservation:
    f = get_field(field)
    return FinancialObservation(
        instrument_id=INST,
        period_end=date.fromisoformat(period_end),
        published_at=_ts(pub),
        statement_type=f.statement_type if f else "income",
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        source_id="S",
        revision_id="r0",
        quality_status="observed",
    )


def _ca(report: str, cash: float, announced: str, ex: str) -> CorporateActionEvent:
    return CorporateActionEvent(
        action_id=f"em:000001:{report}:cash",
        instrument_id=INST,
        action_type="cash_dividend",
        announced_at=_ts(announced, 15),
        ex_date=date.fromisoformat(ex),
        cash_per_share=cash,
        currency="CNY",
        source_id="em_sharebonus",
    )


def _bank_load(*, with_oei: bool = True, with_eps: bool = True, with_mi: bool = False,
               with_oci: bool = True, multi_year: bool = True):
    fins = []
    years = [
        # y, te, oei, pref, perp, gw, ni, eps, oci, rev, mi
        (2019, 300e9, 40e9, 10e9, 30e9, 7e9, 28e9, 1.4, -0.1e9, 120e9, 0.0),
        (2020, 330e9, 45e9, 12e9, 33e9, 7e9, 30e9, 1.5, -0.2e9, 125e9, 0.0),
        (2021, 360e9, 50e9, 15e9, 35e9, 7.5e9, 35e9, 1.7, 0.1e9, 130e9, 0.0),
        (2022, 400e9, 55e9, 18e9, 37e9, 7.5e9, 40e9, 1.9, -0.3e9, 140e9, 0.0),
        (2023, 472.0e9, 69.55e9, 19.953e9, 49.597e9, 7.568e9, 46.455e9, 2.25, -0.376e9, 164.699e9, 0.0),
        (2024, 494.842e9, 69.948e9, 19.953e9, 49.995e9, 7.568e9, 44.508e9, 2.15, -0.374e9, 146.695e9, 0.0),
    ]
    if not multi_year:
        years = years[-2:]
    for y, te, oei, pref, perp, gw, ni, eps, oci, rev, mi in years:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(pe, "total_equity", te, pub),
            _f(pe, "parent_net_income", ni, pub),
            _f(pe, "revenue", rev, pub),
            _f(pe, "total_assets", te * 10, pub),
            _f(pe, "total_liabilities", te * 9, pub),
            _f(pe, "dividends_paid", 20e9, pub),
        ])
        if with_oei:
            fins.append(_f(pe, "other_equity_instruments", oei, pub))
            fins.append(_f(pe, "preferred_shares", pref, pub))
            fins.append(_f(pe, "perpetual_bond", perp, pub))
        if with_mi:
            fins.append(_f(pe, "minority_interest", mi, pub))
        fins.append(_f(pe, "goodwill", gw, pub))
        if with_eps:
            fins.append(_f(pe, "basic_eps", eps, pub))
        if with_oci:
            fins.append(_f(pe, "other_comprehensive_income", oci, pub))
        fins.append(_f(pe, "interest_income", 180e9, pub))

    # shares each year-end for annual history
    mkts = [
        MarketObservation(
            instrument_id=INST, timestamp=_ts(f"{y}-12-30", 15), raw_close=12.0,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        )
        for y in range(2019, 2025)
    ]
    mkts.append(MarketObservation(
        instrument_id=INST, timestamp=_ts("2025-06-30", 15), raw_close=12.07,
        adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
    ))
    cas = [
        _ca("2024-12-31", 0.362, "2025-03-15", "2025-06-12"),
        _ca("2024-06-30", 0.246, "2024-08-16", "2024-10-10"),
        _ca("2023-12-31", 0.719, "2024-03-15", "2024-06-14"),
    ]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=_ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    return LoadResult(
        financial=fins, market=mkts, corporate_actions=cas,
        sources={
            "S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                  versioning="FULL_HISTORY"),
            "em_bank_f10": SourceDescriptor(source_id="em_bank_f10", reporting_convention="CN_CUMULATIVE_YTD",
                                            versioning="LATEST_ONLY"),
            "em_sharebonus": SourceDescriptor(source_id="em_sharebonus", reporting_convention="UNKNOWN",
                                              versioning="LATEST_ONLY"),
        },
        classifications=[cls],
        corporate_actions_provided=True,
    )


def _snap(load: LoadResult):
    as_of, _ = parse_as_of("2025-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=load.financial, market=load.market,
        corporate_actions=list(load.corporate_actions), sources=load.sources,
        classifications=load.classifications,
    )
    return snap


def test_common_equity_rule_documented():
    assert "other_equity_instruments" in BOOK_EQUITY_COMMON_RULE
    assert "minority" in BOOK_EQUITY_COMMON_RULE.lower()


def test_ac_common_equity_0_matches_000001_fy24(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load())
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok, bridge.detail
    assert bridge.common_equity_0 == pytest.approx(424_894_000_000.0, rel=0, abs=1.0)
    assert bridge.rim_inputs["book_equity_0"] == pytest.approx(424_894_000_000.0, rel=0, abs=1.0)
    assert bridge.total_equity_0 == pytest.approx(494_842_000_000.0, rel=0, abs=1.0)
    assert bridge.goodwill_0 == pytest.approx(7_568_000_000.0)
    assert bridge.tangible_common_equity_0 == pytest.approx(424_894_000_000.0 - 7_568_000_000.0)
    assert "RIM-COMMON-EQUITY-v1" in bridge.assumption_ids


def test_ac_common_ni_from_eps(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load())
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    expected = 2.15 * SHARES
    assert bridge.last_fy_ni == pytest.approx(expected, rel=1e-9)
    assert bridge.rim_inputs["net_income"] == [pytest.approx(expected)] * 5
    assert "NI_FROM_BASIC_EPS_TIMES_SHARES" in bridge.flags


def test_ac_dps_sharebonus_0_608(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load())
    dps, _ = fy_dps_from_sharebonus(snap, fiscal_year=2024)
    assert dps == pytest.approx(0.608, abs=1e-9)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    assert bridge.last_fy_dps == pytest.approx(0.608, abs=1e-9)
    assert bridge.last_fy_dividends == pytest.approx(0.608 * SHARES, rel=1e-9)
    assert "DIVIDENDS_FROM_SHAREBONUS_DPS" in bridge.flags
    assert "RIM-DPS-SHAREBONUS-v1" in bridge.assumption_ids


def test_ac_missing_oei_ineligible(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load(with_oei=False))
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert not bridge.ok
    assert bridge.ineligible_reason == "MISSING_OTHER_EQUITY_INSTRUMENTS"


def test_ac_missing_eps_ineligible(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load(with_eps=False))
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert not bridge.ok
    assert bridge.ineligible_reason == "MISSING_BASIC_EPS"


def test_ac_oci_used_when_present(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load(with_oci=True))
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True)
    assert bridge.ok
    assert bridge.rim_inputs.get("oci") == [pytest.approx(-0.374e9)] * 5
    assert "OCI_CONSTANT_LAST_FY_ASSUMPTION" in bridge.flags


def test_legacy_total_basis_still_works(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load(with_oei=False, with_eps=False))
    bridge = rim_inputs_from_snapshot(
        snap, loaded=loaded, years=5, zeros_explicit=True, equity_basis="total",
    )
    assert bridge.ok
    assert bridge.rim_inputs["book_equity_0"] == pytest.approx(494.842e9)


def test_refuse_silent_cs_zeros(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load(with_oci=False, with_mi=True))
    with pytest.raises(RimBridgeError, match="refuse silent zeros"):
        rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=False)
