"""R5: subject own-hist TE+OEI+shares+raw_close depth for Track B (RIM-SUBJECT-HIST-DEPTH-v1)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS, historical_common_pb
from vms.methods.rim.subject_hist_depth import (
    build_subject_hist_depth,
    merge_subject_hist_into_load,
)
from vms.methods.rim.track_b_exit import run_rim_track_b
from vms.methods.rim.from_snapshot import rim_inputs_from_snapshot
from vms.pit.asof import parse_as_of
from vms.pit.snapshot import build_snapshot
from vms.providers.hithink.paths import fund_db_path, market_db_path
from vms.reporting.value_rim_bundle import build_value_rim_bundle
from vms.schemas import (
    CorporateActionEvent,
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.fields import get_field
from vms.schemas.observations import ReportingConvention, Versioning

CST = timezone(timedelta(hours=8))
INST = "000001.SZ"
SHARES = 1.9405918198e10


def _ts(d: str, hh: int = 15) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(period_end: str, field: str, value, pub: str, *, inst: str = INST) -> FinancialObservation:
    cf = get_field(field)
    return FinancialObservation(
        instrument_id=inst,
        period_end=date.fromisoformat(period_end),
        published_at=_ts(pub, 18),
        statement_type=cf.statement_type if cf else "balance_sheet",
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        source_id="S",
        revision_id="r0",
        quality_status="observed",
    )


def _m(d: str, px: float, shares: float | None = SHARES, *, inst: str = INST) -> MarketObservation:
    return MarketObservation(
        instrument_id=inst,
        timestamp=_ts(d, 15),
        raw_close=px,
        adjusted_close=None,
        shares_outstanding=shares,
        currency="CNY",
        source_id="S",
    )


def _series(n_years: int, *, start: int = 2010):
    """Return (fins, mkts, cas, cls, sources, as_of) with deep common-equity history."""
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
        px = 8.0 + 0.2 * i
        mkts.append(_m(f"{y}-12-30", px))
    last_y = start + n_years - 1
    mkts.append(_m(f"{last_y+1}-06-30", 12.0))
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
            source_id="S", reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
            versioning=Versioning.FULL_HISTORY,
        ),
        "em_sharebonus": SourceDescriptor(
            source_id="em_sharebonus", reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
            versioning=Versioning.FULL_HISTORY,
        ),
        "em_f10_industry": SourceDescriptor(
            source_id="em_f10_industry", reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
            versioning=Versioning.FULL_HISTORY,
        ),
    }
    as_of, _ = parse_as_of(f"{last_y+1}-06-30")
    return fins, mkts, cas, cls, sources, as_of


def _build_years(n_years: int, *, start: int = 2010):
    fins, mkts, cas, cls, sources, as_of = _series(n_years, start=start)
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=fins, market=mkts,
        corporate_actions=cas, sources=sources, classifications=[cls],
    )
    return snap


def _load_result(n_years: int = 14, *, start: int = 2010) -> tuple[LoadResult, datetime]:
    fins, mkts, cas, cls, sources, as_of = _series(n_years, start=start)
    load = LoadResult(
        financial=fins,
        market=mkts,
        corporate_actions=cas,
        classifications=[cls],
        sources=sources,
        corporate_actions_provided=True,
        sources_provided=True,
    )
    return load, as_of


def test_min_hist_pb_points_unchanged():
    assert MIN_HIST_PB_POINTS == 12


def test_year_funnel_marks_missing_oei_and_included(repo):
    """Year-level funnel: TE without OEI → SKIP; complete year → INCLUDED."""
    # 3 years TE; only last 2 have OEI; shares+px for all
    fins = []
    mkts = []
    for y, oei in [(2018, None), (2019, 10e9), (2020, 12e9)]:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.append(_f(pe, "total_equity", 100e9, pub))
        fins.append(_f(pe, "minority_interest", 0.0, pub))
        if oei is not None:
            fins.append(_f(pe, "other_equity_instruments", oei, pub))
        fins.append(_f(pe, "basic_eps", 1.0, pub))
        fins.append(_f(pe, "parent_net_income", SHARES, pub))
        fins.append(_f(pe, "revenue", 50e9, pub))
        fins.append(_f(pe, "total_assets", 1e12, pub))
        fins.append(_f(pe, "total_liabilities", 0.9e12, pub))
        fins.append(_f(pe, "goodwill", 1e9, pub))
        fins.append(_f(pe, "other_comprehensive_income", 0.0, pub))
        mkts.append(_m(f"{y}-12-30", 10.0))
    mkts.append(_m("2021-06-30", 11.0))
    sources = {
        "S": SourceDescriptor(
            source_id="S", reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
            versioning=Versioning.FULL_HISTORY,
        ),
    }
    as_of, _ = parse_as_of("2021-06-30")
    snap, _, _ = build_snapshot(
        instrument_id=INST, as_of=as_of, financial=fins, market=mkts,
        corporate_actions=[], sources=sources, classifications=[],
    )
    hist = historical_common_pb(snap, zeros_explicit=True, min_points=12)
    by = {e.year: e for e in hist.year_funnel}
    assert by[2018].status == "SKIP_NO_COMMON_EQUITY"
    assert by[2018].reason == "MISSING_OTHER_EQUITY_INSTRUMENTS"
    assert by[2019].status == "INCLUDED"
    assert by[2020].status == "INCLUDED"
    assert hist.n == 2
    assert not hist.ok
    assert hist.ineligible_reason == "INSUFFICIENT_OWN_PB_HISTORY"


def test_track_b_valid_when_hist_ge_12_after_deep_series(repo):
    loaded = load_config(repo / "config/default.yaml")
    snap = _build_years(14)
    hist = historical_common_pb(snap, zeros_explicit=True)
    assert hist.ok
    assert hist.n >= MIN_HIST_PB_POINTS
    assert any(e.status == "INCLUDED" for e in hist.year_funnel)
    bridge = rim_inputs_from_snapshot(snap, loaded=loaded, equity_basis="common")
    assert bridge.ok
    tb = run_rim_track_b(
        snap, bridge=bridge, loaded=loaded, years=3, n_paths=20, seed=42, horizons_years=(1, 3),
    )
    assert tb.ok
    assert tb.status == "VALID"
    assert tb.pb_center_used is not None
    assert abs(float(tb.pb_center_used) - 2.0) > 0.5
    assert tb.hist_pb.get("year_funnel")


def test_merge_appends_missing_years_does_not_overwrite(repo):
    existing = _f("2020-12-31", "total_equity", 111.0, "2021-03-15")
    load = LoadResult(
        financial=[existing],
        market=[_m("2020-12-30", 9.0, shares=None)],
        sources={
            "S": SourceDescriptor(
                source_id="S", reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
                versioning=Versioning.FULL_HISTORY,
            ),
        },
        sources_provided=True,
    )
    from vms.methods.rim.subject_hist_depth import SubjectHistDepthReport
    from vms.methods.rim.bank_peer_panel import TickerPathDiag as TPD

    depth_fin = [
        _f("2020-12-31", "total_equity", 999.0, "2021-03-15"),  # must NOT overwrite
        _f("2019-12-31", "total_equity", 80e9, "2020-03-15"),
        _f("2019-12-31", "other_equity_instruments", 5e9, "2020-03-15"),
    ]
    depth_mkt = [_m("2020-12-30", 9.0, shares=SHARES), _m("2019-12-30", 8.0)]
    depth = SubjectHistDepthReport(
        instrument_id=INST,
        as_of="2021-06-30T15:00:00+08:00",
        financial=depth_fin,
        market=depth_mkt,
        path_diag=TPD(instrument_id=INST),
        flags=["SUBJECT_HIST_DEPTH_BUILDER"],
        assumption_ids=["RIM-SUBJECT-HIST-DEPTH-v1"],
    )
    merged = merge_subject_hist_into_load(load, depth)
    te_2020 = [o for o in merged.financial if o.field_name == "total_equity" and o.period_end.year == 2020]
    assert len(te_2020) == 1
    assert te_2020[0].value == 111.0
    assert any(o.period_end.year == 2019 and o.field_name == "total_equity" for o in merged.financial)
    # shares stamped on existing bar
    bar = next(o for o in merged.market if o.timestamp.date() == date(2020, 12, 30))
    assert bar.shares_outstanding == SHARES
    assert depth.n_financial_added == 2
    assert "SUBJECT_HIST_MERGED_INTO_LOAD" in depth.flags


def test_prefer_local_zero_rest_when_local_present(monkeypatch):
    fdb = fund_db_path()
    mdb = market_db_path()
    if not fdb.is_file() or not mdb.is_file():
        pytest.skip("local DuckDB not mounted")

    def _boom(*_a, **_k):
        raise AssertionError("REST must not be called when prefer_local")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_datacenter_all", _boom,
    )
    as_of = _ts("2025-06-30", 15)
    rep = build_subject_hist_depth(
        instrument_id=INST, as_of=as_of, prefer_local=True, fund_db=fdb, market_db=mdb,
    )
    assert rep.rest_calls == 0
    assert "SUBJECT_HIST_PREFER_LOCAL" in rep.flags
    assert rep.path_diag.te_path in ("local", "local_miss_no_rest", "fund_db_missing") or rep.path_diag.te_obs >= 0


def test_refresh_fail_falls_back_or_empty(tmp_path, monkeypatch):
    """--refresh path: REST fail → local fallback or empty; never invent OEI."""
    from vms.providers.eastmoney import store as em_store
    from vms.providers.hithink.paths import duckdb_available

    fdb = tmp_path / "fund.duckdb"
    mdb = tmp_path / "market.duckdb"
    if duckdb_available():
        em_store.ensure_tables(fdb)

    def _boom(*_a, **_k):
        raise RuntimeError("forced_rest_fail")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_datacenter_all", _boom,
    )
    as_of = _ts("2025-06-30", 15)
    rep = build_subject_hist_depth(
        instrument_id=INST, as_of=as_of, prefer_local=False, fund_db=fdb, market_db=mdb,
    )
    assert "SUBJECT_HIST_REFRESH_ALLOWED" in rep.flags
    assert not any(o.field_name == "other_equity_instruments" for o in rep.financial)
    assert "rest_failed" in rep.path_diag.bank_f10_path or rep.path_diag.bank_f10_obs == 0


def test_wiring_deepens_before_track_b_and_exposes_funnel(repo, tmp_path, monkeypatch):
    """value-rim auto subject hist ON; Track B hist payload carries year_funnel."""
    loaded = load_config(repo / "config/default.yaml")
    load, as_of = _load_result(14)

    # Stub deepen to no-op merge of empty (synthetic already deep) but set flags
    from vms.methods.rim.subject_hist_depth import SubjectHistDepthReport
    from vms.methods.rim.bank_peer_panel import TickerPathDiag

    def _fake_depth(**kwargs):
        return SubjectHistDepthReport(
            instrument_id=kwargs["instrument_id"],
            as_of=kwargs["as_of"].isoformat(),
            financial=[],
            market=[],
            path_diag=TickerPathDiag(instrument_id=kwargs["instrument_id"]),
            flags=["SUBJECT_HIST_DEPTH_BUILDER", "SUBJECT_HIST_PREFER_LOCAL"],
            assumption_ids=["RIM-SUBJECT-HIST-DEPTH-v1"],
            prefer_local=True,
            detail="stub",
        )

    monkeypatch.setattr(
        "vms.reporting.value_rim_bundle.build_subject_hist_depth", _fake_depth,
    )
    out = tmp_path / "rim_r5"
    summary = build_value_rim_bundle(
        out_dir=out,
        load=load,
        input_dir=tmp_path,
        instrument_id=INST,
        as_of=as_of,
        as_of_note="test",
        loaded=loaded,
        mode="exploratory",
        override_reason="R5 wiring: subject hist depth + year funnel",
        equity_basis="common",
        run_distribution=False,
        run_pb_roe=False,
        auto_fi_peers=False,
        deepen_subject_hist=True,
        prefer_local_subject_hist=True,
        n_paths=20,
        seed=42,
        track_b_paths=20,
    )
    assert summary["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert "AUTO_SUBJECT_HIST_DEPTH" in summary["flags"]
    assert summary.get("subject_hist") is not None
    assert (out / "rim_subject_hist.json").is_file()
    tb = summary.get("track_b") or {}
    assert tb.get("year_funnel") is not None
    assert tb.get("hist_pb_n", 0) >= MIN_HIST_PB_POINTS
    assert tb.get("status") == "VALID"


def test_wiring_disabled_sets_flag(repo, tmp_path, monkeypatch):
    loaded = load_config(repo / "config/default.yaml")
    load, as_of = _load_result(14)

    def _should_not_run(**_k):
        raise AssertionError("deepen must not run when disabled")

    monkeypatch.setattr(
        "vms.reporting.value_rim_bundle.build_subject_hist_depth", _should_not_run,
    )
    summary = build_value_rim_bundle(
        out_dir=tmp_path / "rim_r5_off",
        load=load,
        input_dir=tmp_path,
        instrument_id=INST,
        as_of=as_of,
        as_of_note="test",
        loaded=loaded,
        mode="exploratory",
        override_reason="R5 wiring: subject hist depth disabled",
        equity_basis="common",
        run_distribution=False,
        run_pb_roe=False,
        auto_fi_peers=False,
        deepen_subject_hist=False,
        n_paths=20,
        seed=42,
        track_b_paths=20,
    )
    assert "SUBJECT_HIST_DEPTH_DISABLED" in summary["flags"]
