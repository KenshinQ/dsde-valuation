"""R1: PITSnapshot → RIM bridge (real bank path; no industrial FCFF lift)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.from_snapshot import (
    BOOK_EQUITY_TE_RULE,
    RimBridgeError,
    features_from_snapshot,
    rim_inputs_from_snapshot,
)
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot
from vms.profiles import classify_profile
from vms.schemas import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.contracts import ProfileLabel
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
INST = "BANK001.SZ"


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


def _m(d: str, close: float, shares: float) -> MarketObservation:
    return MarketObservation(
        instrument_id=INST,
        timestamp=_ts(d, 15),
        raw_close=close,
        adjusted_close=None,
        shares_outstanding=shares,
        currency="CNY",
        source_id="S",
    )


def _bank_load(*, with_div: bool = True) -> LoadResult:
    fins = []
    for y, te, ni, rev, div, ta in [
        (2022, 400.0, 40.0, 100.0, 10.0, 2000.0),
        (2023, 450.0, 45.0, 110.0, 12.0, 2200.0),
        (2024, 500.0, 50.0, 120.0, 15.0, 2400.0),
    ]:
        pe = f"{y}-12-31"
        pub = f"{y + 1}-03-15"
        fins.extend([
            _f(pe, "total_equity", te, pub),
            _f(pe, "parent_net_income", ni, pub),
            _f(pe, "revenue", rev, pub),
            _f(pe, "total_assets", ta, pub),
            _f(pe, "total_liabilities", ta - te, pub),
        ])
        if with_div:
            fins.append(_f(pe, "dividends_paid", div, pub))
    mkts = [_m(f"{y}-12-30", 10.0, 100.0) for y in (2022, 2023, 2024)]
    mkts.append(_m("2025-06-30", 12.0, 100.0))
    cls = InstrumentClassification(
        instrument_id=INST,
        scheme="SW2021_L1",
        industry="银行",
        published_at=_ts("1991-04-03", 15),
        source_id="test",
    )
    return LoadResult(
        financial=fins,
        market=mkts,
        corporate_actions=[],
        sources={"S": SourceDescriptor(
            source_id="S", reporting_convention="CN_CUMULATIVE_YTD", versioning="FULL_HISTORY",
        )},
        classifications=[cls],
    )


def _snap(load: LoadResult):
    as_of, _ = parse_as_of("2025-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST,
        as_of=as_of,
        financial=load.financial,
        market=load.market,
        corporate_actions=list(load.corporate_actions),
        sources=load.sources,
        classifications=load.classifications,
    )
    return snap


def test_book_equity_te_rule_documented():
    assert "total_equity" in BOOK_EQUITY_TE_RULE
    assert ("12-31" in BOOK_EQUITY_TE_RULE) or ("fiscal" in BOOK_EQUITY_TE_RULE.lower())


def test_features_from_bank_snapshot_are_financial_not_mature():
    snap = _snap(_bank_load())
    feats = features_from_snapshot(snap)
    report = classify_profile(feats)
    assert report.primary_profile is ProfileLabel.FINANCIAL_INSTITUTION
    assert report.primary_profile is not ProfileLabel.MATURE_OPERATING


def test_rim_inputs_constant_ni_and_explicit_cs_zeros(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load())
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=5, zeros_explicit=True, equity_basis="total")
    assert bridge.ok
    ri = bridge.rim_inputs
    assert ri["book_equity_0"] == 500.0
    assert ri["net_income"] == [50.0] * 5
    assert ri["zeros_explicit"] is True
    assert "CLEAN_SURPLUS_ZEROS_ASSUMED" in bridge.flags
    assert "oci" not in ri and "net_issuance" not in ri
    assert ri["dividends"] == [15.0] * 5
    assert ri["diluted_shares"] == 100.0
    assert bridge.book_equity_year == 2024
    assert any("ASSUMPTION" in a for a in bridge.assumption_labels)
    ke = loaded.config.valuation.risk_free_rate + loaded.config.valuation.beta * loaded.config.valuation.erp
    assert ri["cost_of_equity"] == pytest.approx(ke)


def test_rim_inputs_refuse_silent_cs_zeros(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _snap(_bank_load())
    with pytest.raises(RimBridgeError) as ei:
        rim_inputs_from_snapshot(snap, loaded=loaded, years=3, zeros_explicit=False, equity_basis="total")
    msg = str(ei.value)
    assert ("zeros_explicit" in msg) or ("CLEAN_SURPLUS" in msg)


def test_rim_inputs_missing_ni_ineligible(repo):
    loaded = load_config(repo / "config/default.yaml")
    load = _bank_load()
    load = LoadResult(
        financial=[f for f in load.financial if f.field_name != "parent_net_income"],
        market=load.market,
        corporate_actions=[],
        sources=load.sources,
        classifications=load.classifications,
    )
    snap = _snap(load)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, years=3, zeros_explicit=True, equity_basis="total")
    assert not bridge.ok
    assert bridge.ineligible_reason in {"MISSING_NET_INCOME_FORECAST", "MISSING_PARENT_NET_INCOME"}
