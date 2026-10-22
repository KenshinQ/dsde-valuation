"""R2d: own-hist common P/B exit → Track B; UNAVAILABLE when hist < 12; no silent intrinsic."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS, historical_common_pb
from vms.methods.rim.track_b_exit import run_rim_track_b
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


def _ts(d: str, hh: int = 15) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(period_end: str, field: str, value, pub: str) -> FinancialObservation:
    f = get_field(field)
    return FinancialObservation(
        instrument_id=INST, period_end=date.fromisoformat(period_end), published_at=_ts(pub, 18),
        statement_type=f.statement_type if f else "income", field_name=field, value=value,
        currency="CNY", unit_scale="unit", source_id="S", revision_id="r0", quality_status="observed",
    )


def _build_years(n_years: int, *, start: int = 2010):
    fins = []
    mkts = []
    for i in range(n_years):
        y = start + i
        te = 200e9 + i * 20e9
        oei = 20e9 + (5e9 if i >= 5 else 0.0)
        eps = 1.0 + 0.05 * i
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(pe, "total_equity", te, pub),
            _f(pe, "other_equity_instruments", oei, pub),
            _f(pe, "minority_interest", 0.0, pub),
            _f(pe, "basic_eps", eps, pub),
            _f(pe, "parent_net_income", eps * SHARES, pub),
            _f(pe, "revenue", 100e9, pub),
            _f(pe, "total_assets", te * 10, pub),
            _f(pe, "total_liabilities", te * 9, pub),
            _f(pe, "goodwill", 1e9, pub),
            _f(pe, "other_comprehensive_income", -0.1e9, pub),
        ])
        # raw close grows slowly; pb around 0.5–0.8
        px = 8.0 + 0.2 * i
        mkts.append(MarketObservation(
            instrument_id=INST, timestamp=_ts(f"{y}-12-30"), raw_close=px,
            adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
        ))
    last_y = start + n_years - 1
    mkts.append(MarketObservation(
        instrument_id=INST, timestamp=_ts(f"{last_y+1}-06-30"), raw_close=12.0,
        adjusted_close=None, shares_outstanding=SHARES, currency="CNY", source_id="S",
    ))
    cas = [
        CorporateActionEvent(
            action_id=f"em:000001:{last_y}-12-31:cash", instrument_id=INST,
            action_type="cash_dividend", announced_at=_ts(f"{last_y+1}-03-15", 15),
            ex_date=date(last_y + 1, 6, 12), cash_per_share=0.40, currency="CNY",
            source_id="em_sharebonus",
        ),
        CorporateActionEvent(
            action_id=f"em:000001:{last_y}-06-30:cash", instrument_id=INST,
            action_type="cash_dividend", announced_at=_ts(f"{last_y}-08-16", 15),
            ex_date=date(last_y, 10, 10), cash_per_share=0.20, currency="CNY",
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
    as_of, _ = parse_as_of(f"{last_y+1}-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=fins, market=mkts,
        corporate_actions=cas, sources=sources, classifications=[cls],
    )
    return snap


def test_hist_pb_unavailable_when_lt_12(repo):
    snap = _build_years(8)  # < 12
    hist = historical_common_pb(snap, zeros_explicit=True)
    assert not hist.ok
    assert hist.ineligible_reason == "INSUFFICIENT_OWN_PB_HISTORY"
    assert hist.n < MIN_HIST_PB_POINTS
    assert "OWN_PB_HISTORY_UNAVAILABLE" in hist.flags


def test_track_b_unavailable_when_hist_lt_12(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _build_years(8)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    tb = run_rim_track_b(
        snap, bridge=bridge, loaded=loaded, years=3, n_paths=20, seed=42, horizons_years=(1, 3),
    )
    assert tb.status == "UNAVAILABLE"
    assert tb.ineligible_reason == "INSUFFICIENT_OWN_PB_HISTORY"
    assert tb.exit_prices is None
    assert tb.returns is None
    assert "FORBID_DEFAULT_PB_CENTER_2" in tb.flags


def test_track_b_valid_with_ge_12_hist_no_intrinsic_copy(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _build_years(14)  # >= 12
    hist = historical_common_pb(snap, zeros_explicit=True)
    assert hist.ok and hist.n >= MIN_HIST_PB_POINTS
    assert hist.median is not None
    # must not equal the forbidden default center 2.0 for this synthetic (~0.5–0.8)
    assert hist.median < 1.5

    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    tb = run_rim_track_b(
        snap, bridge=bridge, loaded=loaded, years=3, n_paths=40, seed=7, horizons_years=(1, 3),
    )
    assert tb.ok and tb.status == "VALID"
    assert tb.pb_center_used == pytest.approx(hist.median)
    assert abs(tb.pb_center_used - 2.0) > 0.5  # not default 2.0
    assert tb.exit_prices is not None
    assert tb.exit_prices["metric_id"] == "pb"
    assert tb.exit_prices["default_forbids_intrinsic_copy"] is True
    assert tb.exit_prices["n_valid"] > 0
    assert tb.returns is not None
    assert tb.returns["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert "RIM-EXIT-OWN-PB-HIST-v1" in tb.assumption_ids
    assert "NO_SILENT_INTRINSIC_EXIT" in tb.flags
