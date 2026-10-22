"""R2c: P/B-ROE relative sidecar — common BPS, raw close, PEER_SCARCITY."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
from vms.methods.rim.pb_roe import make_pb_common_peer, run_pb_roe_relative
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
        instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=_ts(pub),
        statement_type=f.statement_type if f else "income", field_name=field, value=value,
        currency="CNY", unit_scale="unit", source_id="S", revision_id="r0", quality_status="observed",
    )


def _snap(repo):
    y, te, oei, eps = 2024, 494.842e9, 69.948e9, 2.15
    pe, pub = f"{y}-12-31", f"{y+1}-03-15"
    fins = [
        _f("2023-12-31", "total_equity", 472e9, "2024-03-15"),
        _f("2023-12-31", "other_equity_instruments", 69.55e9, "2024-03-15"),
        _f("2023-12-31", "minority_interest", 0.0, "2024-03-15"),
        _f("2023-12-31", "basic_eps", 2.25, "2024-03-15"),
        _f("2023-12-31", "parent_net_income", 2.25 * SHARES, "2024-03-15"),
        _f("2023-12-31", "revenue", 100e9, "2024-03-15"),
        _f("2023-12-31", "total_assets", 4e12, "2024-03-15"),
        _f("2023-12-31", "total_liabilities", 3.5e12, "2024-03-15"),
        _f(pe, "total_equity", te, pub),
        _f(pe, "other_equity_instruments", oei, pub),
        _f(pe, "minority_interest", 0.0, pub),
        _f(pe, "basic_eps", eps, pub),
        _f(pe, "parent_net_income", eps * SHARES, pub),
        _f(pe, "revenue", 100e9, pub),
        _f(pe, "total_assets", te * 10, pub),
        _f(pe, "total_liabilities", te * 9, pub),
        _f(pe, "goodwill", 7.568e9, pub),
        _f(pe, "other_comprehensive_income", -0.374e9, pub),
    ]
    mkts = [
        MarketObservation(
            instrument_id=INST, timestamp=_ts("2023-12-29", 15), raw_close=10.5,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ),
        MarketObservation(
            instrument_id=INST, timestamp=_ts("2024-12-31", 15), raw_close=11.7,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ),
        MarketObservation(
            instrument_id=INST, timestamp=_ts("2025-06-30", 15), raw_close=12.07,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ),
    ]
    cas = [
        CorporateActionEvent(
            action_id="em:000001:2024-12-31:cash", instrument_id=INST,
            action_type="cash_dividend", announced_at=_ts("2025-03-15", 15),
            ex_date=date(2025, 6, 12), cash_per_share=0.362, currency="CNY",
            source_id="em_sharebonus",
        ),
        CorporateActionEvent(
            action_id="em:000001:2024-06-30:cash", instrument_id=INST,
            action_type="cash_dividend", announced_at=_ts("2024-08-16", 15),
            ex_date=date(2024, 10, 10), cash_per_share=0.246, currency="CNY",
            source_id="em_sharebonus",
        ),
    ]
    cls = InstrumentClassification(
        instrument_id=INST, scheme="SW2021_L1", industry="银行",
        published_at=_ts("1991-04-03", 15), source_id="em_f10_industry",
    )
    sources = {
        "S": SourceDescriptor(
            source_id="S", reporting_convention="CN_CUMULATIVE_YTD", versioning="FULL_HISTORY",
        ),
    }
    as_of, _ = parse_as_of("2025-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=fins, market=mkts,
        corporate_actions=cas, sources=sources, classifications=[cls],
    )
    return snap


def test_peer_scarcity_when_no_peers(repo):
    snap = _snap(repo)
    loaded = load_config(repo / "config/default.yaml")
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    rep = run_pb_roe_relative(snap, bridge=bridge, peer_observations=[], rim_vps_crosscheck=21.24)
    assert rep.status == "INELIGIBLE"
    assert rep.ineligible_reason == "PEER_SCARCITY"
    assert "PEER_SCARCITY" in rep.flags
    assert "SHARED_BOOK_MATH_NOT_INDEPENDENT_EVIDENCE" in rep.flags
    assert rep.subject_pb is not None and rep.subject_pb > 0
    assert 0.4 < rep.subject_pb < 0.8
    assert rep.relative_vps is None


def test_peer_relative_vps_with_synthetic_peers(repo):
    snap = _snap(repo)
    loaded = load_config(repo / "config/default.yaml")
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    pub = _ts("2025-03-15", 15)
    peers = [
        make_pb_common_peer(
            subject_instrument_id=INST, peer_instrument_id=f"60000{i}.SH",
            pb=0.6 + 0.05 * i, published_at=pub,
        )
        for i in range(5)
    ]
    rep = run_pb_roe_relative(
        snap, bridge=bridge, peer_observations=peers, rim_vps_crosscheck=21.24, peer_min_count=5,
    )
    assert rep.ok and rep.status == "VALID"
    assert rep.peer_n_included == 5
    assert rep.relative_vps is not None and rep.relative_vps > 0
    assert abs(rep.relative_vps - rep.peer_multiple * rep.subject_bps) < 1e-6
    assert rep.rim_vps_crosscheck == pytest.approx(21.24)
    assert "RIM-PB-ROE-PEER-v1" in rep.assumption_ids


def test_pit_excludes_future_peer_metric(repo):
    snap = _snap(repo)
    loaded = load_config(repo / "config/default.yaml")
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    future = _ts("2025-07-01", 15)
    peers = [
        make_pb_common_peer(
            subject_instrument_id=INST, peer_instrument_id=f"60000{i}.SH",
            pb=0.7, published_at=future,
        )
        for i in range(5)
    ]
    rep = run_pb_roe_relative(snap, bridge=bridge, peer_observations=peers, peer_min_count=5)
    assert not rep.ok
    assert rep.ineligible_reason == "PEER_SCARCITY"
    assert rep.peer_n_included == 0
