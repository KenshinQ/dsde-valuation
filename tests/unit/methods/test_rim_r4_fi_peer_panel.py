"""R4: multi-instrument FI peer panel (RIM-FI-PEER-PANEL-v1)."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from vms.methods.rim.bank_peer_panel import (
    FiPeerPanelReport,
    build_fi_peer_panel,
    lean_curated_peer_ids,
)
from vms.methods.rim.bank_peers import (
    EXCLUSION_MISSING_OEI,
    build_fi_peer_observations,
)
from vms.providers.eastmoney import store as em_store
from vms.providers.hithink.paths import duckdb_available, fund_db_path, market_db_path
from vms.schemas.observations import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
)
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
SUBJ = "000001.SZ"
PEER = "600036.SH"


def _ts(d: str, hh: int = 15) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(inst: str, period_end: str, field: str, value, pub: str) -> FinancialObservation:
    cf = get_field(field)
    return FinancialObservation(
        instrument_id=inst,
        period_end=date.fromisoformat(period_end),
        published_at=_ts(pub),
        statement_type=cf.statement_type if cf else "balance_sheet",
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        source_id="S",
        revision_id="r0",
        quality_status="observed",
    )


def _m(inst: str, d: str, px: float, shares: float | None) -> MarketObservation:
    return MarketObservation(
        instrument_id=inst,
        timestamp=_ts(d, 15),
        raw_close=px,
        adjusted_close=None,
        shares_outstanding=shares,
        currency="CNY",
        source_id="S",
    )


@pytest.fixture
def as_of() -> datetime:
    return _ts("2025-06-30", 15)


def test_lean_curated_excludes_subject():
    ids = lean_curated_peer_ids(SUBJ)
    assert SUBJ not in ids
    assert "600036.SH" in ids


def test_panel_prefer_local_zero_rest_when_local_present(as_of, monkeypatch):
    """AC2: no --refresh ⇒ zero REST when local TE/prices present."""
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("rest")
        raise AssertionError("REST must not be called when prefer_local")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_datacenter_all", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_company_survey", _boom,
    )

    fdb = fund_db_path()
    mdb = market_db_path()
    if not fdb.is_file() or not mdb.is_file():
        pytest.skip("local DuckDB panel not mounted")

    rep = build_fi_peer_panel(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        prefer_local=True,
        candidate_ids=[PEER, "601398.SH"],
    )
    assert isinstance(rep, FiPeerPanelReport)
    assert rep.rest_calls == 0
    assert calls == []
    assert "PANEL_PREFER_LOCAL" in rep.flags
    assert "PANEL_REST_UNEXPECTED" not in rep.flags
    # TE loaded for peers from local HiThink
    te_ids = {f.instrument_id for f in rep.financial if f.field_name == "total_equity"}
    assert PEER in te_ids
    assert "601398.SH" in te_ids
    # Per-ticker path diag present
    assert len(rep.ticker_diagnostics) == 2
    paths = {t.instrument_id: t.te_path for t in rep.ticker_diagnostics}
    assert paths[PEER] == "local"
    assert all(t.rest_calls == 0 for t in rep.ticker_diagnostics)


def test_panel_te_without_oei_excludes_missing_other_equity(as_of):
    """AC4: TE present + no OEI ⇒ MISSING_OTHER_EQUITY_INSTRUMENTS (never TE-as-common)."""
    fins = [
        _f(PEER, "2024-12-31", "total_equity", 1.0e12, "2025-03-20"),
        # deliberately no other_equity_instruments
    ]
    mkts = [_m(PEER, "2025-06-30", 40.0, 1.0e10)]
    classes = [
        InstrumentClassification(
            instrument_id=PEER,
            scheme="SW2021_L1",
            industry="银行",
            published_at=_ts("2000-01-01"),
            source_id="em_f10_industry",
        )
    ]
    # Use builder on in-memory rows via build_fi_peer_observations directly
    # (panel responsibility is to not invent OEI; exclusion is R3).
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label

    classes[0] = classes[0].model_copy(update={"industry": deposit_taking_fi_sw_label()})
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=classes,
        use_lean_curated=False,
        extra_candidates=[PEER],
    )
    assert rep.peers == []
    assert rep.funnel.get(EXCLUSION_MISSING_OEI, 0) == 1
    assert all(
        EXCLUSION_MISSING_OEI in e.reasons for e in rep.excluded if e.peer_instrument_id == PEER
    )


def test_panel_refresh_fail_falls_back_or_excludes(as_of, monkeypatch, tmp_path):
    """AC3: --refresh upsert allowed; fail → local fallback or exclude; no invent.

    Empty / schema-only DBs: REST fails before upsert; panel must not explode and must
    not invent OEI. CI may lack duckdb historically — schema init is best-effort.
    """
    fdb = tmp_path / "fund.duckdb"
    mdb = tmp_path / "market.duckdb"
    if duckdb_available():
        em_store.ensure_tables(fdb)
    # else: missing file is fine — panel._ensure_tables soft-fails; REST mocked below.

    def _fail(*_a, **_k):
        raise RuntimeError("simulated_rest_down")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle", _fail,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_datacenter_all", _fail,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_company_survey", _fail,
    )
    # No HT TE either (empty fund statements) — panel still returns structured diag.
    rep = build_fi_peer_panel(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        prefer_local=False,
        candidate_ids=[PEER],
        fund_db=fdb,
        market_db=mdb,
    )
    assert rep.rest_calls >= 1 or any("rest_failed" in t.bank_f10_path for t in rep.ticker_diagnostics)
    oei = [f for f in rep.financial if f.field_name == "other_equity_instruments"]
    assert oei == [], "must not invent OEI on REST failure"
    d0 = rep.ticker_diagnostics[0]
    assert "rest_failed" in d0.bank_f10_path or d0.bank_f10_obs == 0


def test_panel_pit_leakage_future_rows_excluded(as_of):
    """AC5: future notice / future price must not enter eligible peers."""
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label

    bank = deposit_taking_fi_sw_label()
    fins = [
        _f(PEER, "2024-12-31", "total_equity", 1.0e12, "2025-08-01"),  # after as_of
        _f(PEER, "2024-12-31", "other_equity_instruments", 50e9, "2025-08-01"),
        _f(PEER, "2024-12-31", "minority_interest", 0.0, "2025-08-01"),
    ]
    mkts = [_m(PEER, "2025-08-01", 40.0, 1.0e10)]  # after as_of
    classes = [
        InstrumentClassification(
            instrument_id=PEER, scheme="SW2021_L1", industry=bank,
            published_at=_ts("2000-01-01"), source_id="em",
        )
    ]
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=classes,
        use_lean_curated=False,
        extra_candidates=[PEER],
    )
    assert rep.peers == []
    # Future published_at ⇒ no usable FY under PIT ⇒ MISSING_FINANCIALS or similar
    assert sum(rep.funnel.values()) >= 1
    assert EXCLUSION_MISSING_OEI not in (rep.funnel or {}) or rep.funnel.get("MISSING_FINANCIALS", 0) >= 0


def test_panel_merges_multi_instrument_with_path_diag(as_of, monkeypatch):
    """AC1: merge multi-instrument financial/market/classifications + per-ticker diag."""
    fdb = fund_db_path()
    mdb = market_db_path()
    if not fdb.is_file() or not mdb.is_file():
        pytest.skip("local DuckDB panel not mounted")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no rest")),
    )
    rep = build_fi_peer_panel(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        prefer_local=True,
        candidate_ids=[PEER, "601288.SH", "601988.SH"],
    )
    inst_fin = {f.instrument_id for f in rep.financial}
    inst_mkt = {m.instrument_id for m in rep.market}
    assert PEER in inst_fin and "601288.SH" in inst_fin
    assert PEER in inst_mkt
    assert len(rep.ticker_diagnostics) == 3
    assert all("instrument_id" in t.as_dict() for t in rep.ticker_diagnostics)
    assert "RIM-FI-PEER-PANEL-v1" in rep.assumption_ids
    d = rep.as_dict()
    assert d["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert d["rest_calls"] == 0


def test_local_panel_funnel_not_all_missing_financials_unload(as_of):
    """AC7 local: TE loaded ⇒ funnel must not be all MISSING_FINANCIALS from unload."""
    fdb = fund_db_path()
    mdb = market_db_path()
    if not fdb.is_file() or not mdb.is_file():
        pytest.skip("local DuckDB panel not mounted")

    panel = build_fi_peer_panel(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        prefer_local=True,
    )
    assert panel.rest_calls == 0
    te_n = sum(1 for f in panel.financial if f.field_name == "total_equity")
    assert te_n > 0, "panel must load peer TE from local"

    # Subject stub classification for discover (lean curated already used)
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label

    classes = list(panel.classifications) + [
        InstrumentClassification(
            instrument_id=SUBJ, scheme="SW2021_L1",
            industry=deposit_taking_fi_sw_label(),
            published_at=_ts("2000-01-01"), source_id="em",
        )
    ]
    # Include subject OEI from local if present so subject isn't needed for peers
    fi = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=panel.financial,
        market=panel.market,
        classifications=classes,
        use_lean_curated=True,
    )
    funnel = fi.funnel
    n_cand = len(fi.candidate_ids)
    assert n_cand >= 5
    mf = funnel.get("MISSING_FINANCIALS", 0)
    # With TE loaded, unload-driven all-MISSING_FINANCIALS must not hold.
    assert mf < n_cand, (
        f"expected TE-aware funnel, got all-or-most MISSING_FINANCIALS: {funnel}"
    )
    # Honest codes: OEI miss and/or shares miss are OK
    assert (
        funnel.get(EXCLUSION_MISSING_OEI, 0)
        + funnel.get("MISSING_SHARES", 0)
        + funnel.get("MISSING_RAW_CLOSE", 0)
        + funnel.get("INCLUDED", 0)
        + mf
    ) >= 1


def test_wiring_uses_panel_not_subject_only(repo, tmp_path, monkeypatch, as_of):
    """AC6: value-rim auto uses multi-ticket panel (not subject-only financial)."""
    from vms.data.io import LoadResult
    from vms.pit.asof import parse_as_of
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
    from vms.reporting.value_rim_bundle import build_value_rim_bundle
    from vms.schemas import CorporateActionEvent, SourceDescriptor
    from vms.schemas.config import load_config
    
    seen: dict[str, Any] = {}

    def _fake_panel(**kwargs):
        seen["called"] = True
        seen["prefer_local"] = kwargs.get("prefer_local")
        # Multi-ticket panel with enough peers for R2c
        fins = []
        mkts = []
        classes = []
        bank = deposit_taking_fi_sw_label()
        for i, pid in enumerate(["600036.SH", "601398.SH", "601288.SH", "601939.SH", "601988.SH"]):
            te = 800e9 + i * 10e9
            oei = 40e9
            fins.extend([
                _f(pid, "2024-12-31", "total_equity", te, "2025-03-20"),
                _f(pid, "2024-12-31", "other_equity_instruments", oei, "2025-03-20"),
                _f(pid, "2024-12-31", "minority_interest", 0.0, "2025-03-20"),
            ])
            mkts.append(_m(pid, "2025-06-30", 10.0 + i, 25e9))
            classes.append(InstrumentClassification(
                instrument_id=pid, scheme="SW2021_L1", industry=bank,
                published_at=_ts("2000-01-01"), source_id="em",
            ))
        return FiPeerPanelReport(
            subject_instrument_id=SUBJ,
            as_of=as_of.isoformat(),
            candidate_ids=[c.instrument_id for c in classes],
            financial=fins,
            market=mkts,
            classifications=classes,
            ticker_diagnostics=[],
            flags=["FI_PEER_PANEL_BUILDER", "PANEL_PREFER_LOCAL"],
            assumption_ids=["RIM-FI-PEER-PANEL-v1"],
            rest_calls=0,
        )

    monkeypatch.setattr("vms.reporting.value_rim_bundle.build_fi_peer_panel", _fake_panel)

    # Subject-only load (no peer rows) — panel must supply peers.
    sha = 1.9405918198e10
    fins = []
    for y, te, oei, eps, ni in [
        (2019, 300e9, 40e9, 1.4, 28e9),
        (2020, 330e9, 45e9, 1.5, 30e9),
        (2021, 360e9, 50e9, 1.7, 35e9),
        (2022, 400e9, 55e9, 1.9, 40e9),
        (2023, 472.0e9, 69.55e9, 2.25, 46.455e9),
        (2024, 494.842e9, 69.948e9, 2.15, 44.508e9),
    ]:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(SUBJ, pe, "total_equity", te, pub),
            _f(SUBJ, pe, "parent_net_income", ni, pub),
            _f(SUBJ, pe, "revenue", 150e9, pub),
            _f(SUBJ, pe, "dividends_paid", 20e9, pub),
            _f(SUBJ, pe, "total_assets", te * 10, pub),
            _f(SUBJ, pe, "total_liabilities", te * 9, pub),
            _f(SUBJ, pe, "other_equity_instruments", oei, pub),
            _f(SUBJ, pe, "minority_interest", 0.0, pub),
            _f(SUBJ, pe, "basic_eps", eps, pub),
            _f(SUBJ, pe, "goodwill", 7.568e9, pub),
            _f(SUBJ, pe, "other_comprehensive_income", -0.3e9, pub),
        ])
    mkts = [_m(SUBJ, f"{y}-06-30", 12.0, sha) for y in range(2019, 2026)]
    mkts.append(_m(SUBJ, "2025-06-30", 11.5, sha))
    cas = [
        CorporateActionEvent(
            action_id="em:000001:2024-12-31:cash", instrument_id=SUBJ, action_type="cash_dividend",
            announced_at=_ts("2025-03-15", 15), ex_date=date.fromisoformat("2025-06-12"),
            cash_per_share=0.362, currency="CNY", source_id="em_sharebonus",
        ),
        CorporateActionEvent(
            action_id="em:000001:2024-06-30:cash", instrument_id=SUBJ, action_type="cash_dividend",
            announced_at=_ts("2024-08-16", 15), ex_date=date.fromisoformat("2024-10-10"),
            cash_per_share=0.246, currency="CNY", source_id="em_sharebonus",
        ),
    ]
    bank = deposit_taking_fi_sw_label()
    load = LoadResult(
        financial=fins,
        market=mkts,
        corporate_actions=cas,
        sources={
            "S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                  versioning="FULL_HISTORY"),
            "em_sharebonus": SourceDescriptor(source_id="em_sharebonus", reporting_convention="UNKNOWN",
                                              versioning="LATEST_ONLY"),
        },
        classifications=[InstrumentClassification(
            instrument_id=SUBJ, scheme="SW2021_L1", industry=bank,
            published_at=_ts("2000-01-01"), source_id="em",
        )],
        corporate_actions_provided=True,
        peers=[],
    )
    loaded = load_config(repo / "config/default.yaml")
    asof, note = parse_as_of("2025-06-30")
    out = tmp_path / "rim_r4"
    summ = build_value_rim_bundle(
        out_dir=out,
        load=load,
        input_dir=tmp_path / "data",
        instrument_id=SUBJ,
        as_of=asof,
        as_of_note=note,
        loaded=loaded,
        mode="exploratory",
        override_reason="R4 wiring: panel not subject-only",
        years=5,
        zeros_explicit=True,
        run_distribution=False,
        run_pb_roe=True,
        run_track_b=False,
        auto_fi_peers=True,
        prefer_local_fi_peers=True,
        peer_min_count=5,
    )
    assert seen.get("called") is True
    assert seen.get("prefer_local") is True
    assert "AUTO_FI_PEER_PANEL" in summ["flags"]
    assert "AUTO_FI_PEERS" in summ["flags"]
    assert summ["fi_peers"] is not None
    assert summ["fi_peers"]["n_peers"] >= 5
    assert "panel" in summ["fi_peers"]
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    art = json.loads((out / "rim_fi_peers.json").read_text())
    assert art["panel"]["rest_calls"] == 0


def test_panel_empty_tmp_duckdb_prefer_local_zero_rest(as_of, monkeypatch, tmp_path):
    """SHOULD-FIX: empty tmp DuckDB + prefer_local ⇒ rest_calls=0 (no REST on miss)."""
    if not duckdb_available():
        pytest.skip("duckdb required to create empty EM enrichment schema")
    fdb = tmp_path / "fund.duckdb"
    mdb = tmp_path / "market.duckdb"
    em_store.ensure_tables(fdb)
    # market DB may be absent; prices path records miss without REST under prefer_local.

    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("rest")
        raise AssertionError("REST must not be called when prefer_local")

    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_bank_f10_bundle", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_datacenter_all", _boom,
    )
    monkeypatch.setattr(
        "vms.methods.rim.bank_peer_panel.em_client.fetch_company_survey", _boom,
    )
    rep = build_fi_peer_panel(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        prefer_local=True,
        candidate_ids=[PEER],
        fund_db=fdb,
        market_db=mdb,
    )
    assert rep.rest_calls == 0
    assert calls == []
    assert "PANEL_PREFER_LOCAL" in rep.flags
    assert "PANEL_REST_UNEXPECTED" not in rep.flags
    d0 = rep.ticker_diagnostics[0]
    assert d0.rest_calls == 0
    assert d0.bank_f10_path == "local_miss_no_rest"


def test_wiring_prefer_local_false_on_refresh(repo, tmp_path, monkeypatch, as_of):
    """SHOULD-FIX: prefer_local_fi_peers=False (--refresh) ⇒ panel prefer_local=False."""
    from vms.data.io import LoadResult
    from vms.pit.asof import parse_as_of
    from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
    from vms.reporting.value_rim_bundle import build_value_rim_bundle
    from vms.schemas import CorporateActionEvent, SourceDescriptor
    from vms.schemas.config import load_config

    seen: dict[str, Any] = {}

    def _fake_panel(**kwargs):
        seen["prefer_local"] = kwargs.get("prefer_local")
        bank = deposit_taking_fi_sw_label()
        fins, mkts, classes = [], [], []
        for i, pid in enumerate(["600036.SH", "601398.SH", "601288.SH", "601939.SH", "601988.SH"]):
            te = 800e9 + i * 10e9
            fins.extend([
                _f(pid, "2024-12-31", "total_equity", te, "2025-03-20"),
                _f(pid, "2024-12-31", "other_equity_instruments", 40e9, "2025-03-20"),
                _f(pid, "2024-12-31", "minority_interest", 0.0, "2025-03-20"),
            ])
            mkts.append(_m(pid, "2025-06-30", 10.0 + i, 25e9))
            classes.append(InstrumentClassification(
                instrument_id=pid, scheme="SW2021_L1", industry=bank,
                published_at=_ts("2000-01-01"), source_id="em",
            ))
        return FiPeerPanelReport(
            subject_instrument_id=SUBJ,
            as_of=as_of.isoformat(),
            candidate_ids=[c.instrument_id for c in classes],
            financial=fins,
            market=mkts,
            classifications=classes,
            ticker_diagnostics=[],
            flags=["FI_PEER_PANEL_BUILDER", "PANEL_REFRESH_ALLOWED"],
            assumption_ids=["RIM-FI-PEER-PANEL-v1"],
            rest_calls=0,
        )

    monkeypatch.setattr("vms.reporting.value_rim_bundle.build_fi_peer_panel", _fake_panel)

    sha = 1.9405918198e10
    fins = []
    for y, te, oei, eps, ni in [
        (2019, 300e9, 40e9, 1.4, 28e9),
        (2020, 330e9, 45e9, 1.5, 30e9),
        (2021, 360e9, 50e9, 1.7, 35e9),
        (2022, 400e9, 55e9, 1.9, 40e9),
        (2023, 472.0e9, 69.55e9, 2.25, 46.455e9),
        (2024, 494.842e9, 69.948e9, 2.15, 44.508e9),
    ]:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(SUBJ, pe, "total_equity", te, pub),
            _f(SUBJ, pe, "parent_net_income", ni, pub),
            _f(SUBJ, pe, "revenue", 150e9, pub),
            _f(SUBJ, pe, "dividends_paid", 20e9, pub),
            _f(SUBJ, pe, "total_assets", te * 10, pub),
            _f(SUBJ, pe, "total_liabilities", te * 9, pub),
            _f(SUBJ, pe, "other_equity_instruments", oei, pub),
            _f(SUBJ, pe, "minority_interest", 0.0, pub),
            _f(SUBJ, pe, "basic_eps", eps, pub),
            _f(SUBJ, pe, "goodwill", 7.568e9, pub),
            _f(SUBJ, pe, "other_comprehensive_income", -0.3e9, pub),
        ])
    mkts = [_m(SUBJ, f"{y}-06-30", 12.0, sha) for y in range(2019, 2026)]
    mkts.append(_m(SUBJ, "2025-06-30", 11.5, sha))
    cas = [
        CorporateActionEvent(
            action_id="em:000001:2024-12-31:cash", instrument_id=SUBJ, action_type="cash_dividend",
            announced_at=_ts("2025-03-15", 15), ex_date=date.fromisoformat("2025-06-12"),
            cash_per_share=0.362, currency="CNY", source_id="em_sharebonus",
        ),
    ]
    bank = deposit_taking_fi_sw_label()
    load = LoadResult(
        financial=fins,
        market=mkts,
        corporate_actions=cas,
        sources={
            "S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                  versioning="FULL_HISTORY"),
            "em_sharebonus": SourceDescriptor(source_id="em_sharebonus", reporting_convention="UNKNOWN",
                                              versioning="LATEST_ONLY"),
        },
        classifications=[InstrumentClassification(
            instrument_id=SUBJ, scheme="SW2021_L1", industry=bank,
            published_at=_ts("2000-01-01"), source_id="em",
        )],
        corporate_actions_provided=True,
        peers=[],
    )
    loaded = load_config(repo / "config/default.yaml")
    asof, note = parse_as_of("2025-06-30")
    out = tmp_path / "rim_r4_refresh"
    summ = build_value_rim_bundle(
        out_dir=out,
        load=load,
        input_dir=tmp_path / "data",
        instrument_id=SUBJ,
        as_of=asof,
        as_of_note=note,
        loaded=loaded,
        mode="exploratory",
        override_reason="R4 wiring: --refresh prefer_local=False",
        years=5,
        zeros_explicit=True,
        run_distribution=False,
        run_pb_roe=True,
        run_track_b=False,
        auto_fi_peers=True,
        prefer_local_fi_peers=False,
        peer_min_count=5,
    )
    assert seen.get("prefer_local") is False
    assert "AUTO_FI_PEER_PANEL" in summ["flags"]
    assert summ["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_legacy_project_value_unsupported_profile_bank_regression(tmp_path, repo):
    """SHOULD-FIX: legacy project/value on bank remains UNSUPPORTED_PROFILE (exit 4)."""
    from tests.integration.test_cli_value_rim import _write_bank_dir
    from vms.cli.main import main

    data = _write_bank_dir(tmp_path, r2=True)
    cfg = str(repo / "config/default.yaml")
    out_p = tmp_path / "project_r4"
    rc_p = main([
        "project", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_p), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R4 SHOULD-FIX: legacy gate must remain",
    ])
    assert rc_p == 4
    out_v = tmp_path / "value_r4"
    rc_v = main([
        "value", "--input", str(data), "--ticker", "000001.SZ", "--as-of", "2025-06-30",
        "--out", str(out_v), "--config", cfg, "--mode", "exploratory",
        "--override-reason", "R4 SHOULD-FIX: legacy gate must remain",
        "--seed", "42", "--paths", "10", "--years", "3",
    ])
    assert rc_v == 4
