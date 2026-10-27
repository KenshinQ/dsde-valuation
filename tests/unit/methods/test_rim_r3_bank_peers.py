"""R3: FI peer PIT universe builder — formula, MISSING_OEI, leakage, funnel."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest

from vms.methods.rim.bank_peers import (
    EXCLUSION_CODE_ALIASES,
    EXCLUSION_MISSING_OEI,
    LEAN_CURATED_DEPOSIT_TAKING_FI,
    build_fi_peer_observations,
    compute_peer_pb_common,
    discover_bank_candidates,
    subject_allows_auto_fi_peers,
)
from vms.methods.rim.hist_pb import PEER_FIELD_PB_COMMON
from vms.pit.asof import parse_as_of
from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
from vms.schemas import (
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
)
from vms.schemas.fields import get_field

CST = timezone(timedelta(hours=8))
SUBJ = "000001.SZ"
PEER_A = "600036.SH"
PEER_B = "601398.SH"
PEER_C = "601288.SH"
PEER_D = "601939.SH"
PEER_E = "601988.SH"
SHARES = 1.0e10


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


def _m(inst: str, d: str, px: float, shares: float = SHARES) -> MarketObservation:
    return MarketObservation(
        instrument_id=inst,
        timestamp=_ts(d, 15),
        raw_close=px,
        adjusted_close=None,
        shares_outstanding=shares,
        currency="CNY",
        source_id="S",
    )


def _bank_cls(inst: str) -> InstrumentClassification:
    return InstrumentClassification(
        instrument_id=inst,
        scheme="SW2021_L1",
        industry=deposit_taking_fi_sw_label(),
        published_at=_ts("2000-01-01"),
        source_id="em_f10_industry",
    )


def _peer_pack(
    inst: str,
    *,
    te: float = 500e9,
    oei: float = 50e9,
    mi: float = 0.0,
    px: float = 40.0,
    shares: float = SHARES,
    pub: str = "2025-03-15",
    mkt: str = "2025-06-30",
    with_oei: bool = True,
) -> tuple[list[FinancialObservation], list[MarketObservation]]:
    fins = [
        _f(inst, "2024-12-31", "total_equity", te, pub),
        _f(inst, "2024-12-31", "minority_interest", mi, pub),
    ]
    if with_oei:
        fins.append(_f(inst, "2024-12-31", "other_equity_instruments", oei, pub))
    mkts = [_m(inst, mkt, px, shares)]
    return fins, mkts


def test_lean_curated_nonempty_and_excludes_subject():
    as_of, _ = parse_as_of("2025-06-30")
    ids = discover_bank_candidates(
        subject_instrument_id=SUBJ,
        classifications=[],
        as_of=as_of,
        use_lean_curated=True,
        fund_db="/nonexistent/r3_lean_curated.duckdb",
    )
    assert SUBJ not in ids
    assert PEER_A in ids
    assert set(LEAN_CURATED_DEPOSIT_TAKING_FI) - {SUBJ} <= set(ids)


def test_formula_pb_common_matches_te_mi_oei():
    as_of, _ = parse_as_of("2025-06-30")
    te, oei, mi, px, shares = 500e9, 50e9, 10e9, 40.0, SHARES
    fins, mkts = _peer_pack(PEER_A, te=te, oei=oei, mi=mi, px=px, shares=shares)
    pb, pub, mts, flags, detail = compute_peer_pb_common(
        peer_instrument_id=PEER_A, as_of=as_of, financial=fins, market=mkts,
    )
    common = te - mi - oei
    expected = px / (common / shares)
    assert pb == pytest.approx(expected)
    assert pub is not None and pub <= as_of
    assert mts is not None and mts <= as_of
    assert "PB_DENOMINATOR_COMMON_BPS" in flags
    assert "MISSING_OEI" not in detail and EXCLUSION_MISSING_OEI not in detail


def test_missing_oei_never_uses_te_as_common():
    as_of, _ = parse_as_of("2025-06-30")
    fins, mkts = _peer_pack(PEER_A, with_oei=False)
    pb, pub, mts, flags, reason = compute_peer_pb_common(
        peer_instrument_id=PEER_A, as_of=as_of, financial=fins, market=mkts,
    )
    assert pb is None
    assert reason == EXCLUSION_MISSING_OEI
    assert EXCLUSION_CODE_ALIASES["MISSING_OEI"] == EXCLUSION_MISSING_OEI
    # TE alone must not produce a pb
    assert pub is None or pb is None


def test_builder_emits_peers_and_funnel():
    as_of, _ = parse_as_of("2025-06-30")
    fins: list[FinancialObservation] = []
    mkts: list[MarketObservation] = []
    for i, pid in enumerate([PEER_A, PEER_B, PEER_C, PEER_D, PEER_E]):
        f, m = _peer_pack(pid, te=400e9 + i * 10e9, oei=40e9, px=30.0 + i, pub="2025-03-20")
        fins.extend(f)
        mkts.extend(m)
    # one thin candidate: TE only → MISSING_OTHER_EQUITY_INSTRUMENTS
    f_thin, m_thin = _peer_pack("601166.SH", with_oei=False)
    fins.extend(f_thin)
    mkts.extend(m_thin)

    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[_bank_cls(p) for p in [PEER_A, PEER_B, PEER_C, PEER_D, PEER_E, "601166.SH"]],
        use_lean_curated=True,
        zeros_explicit=True,
        fund_db="/nonexistent/r3_builder.duckdb",
    )
    assert len(rep.peers) == 5
    assert all(p.field_name == PEER_FIELD_PB_COMMON for p in rep.peers)
    assert all(p.value is not None and p.value > 0 for p in rep.peers)
    assert all(p.source_id == "fi_peer_universe_v2" for p in rep.peers)
    assert rep.source_id == "fi_peer_universe_v2"
    assert "RIM-FI-PEER-UNIVERSE-v2" in rep.assumption_ids
    assert rep.funnel.get("INCLUDED") == 5
    assert rep.funnel.get(EXCLUSION_MISSING_OEI, 0) >= 1
    assert any(e.peer_instrument_id == "601166.SH" and EXCLUSION_MISSING_OEI in e.reasons for e in rep.excluded)


def test_leakage_future_notice_and_price_excluded():
    as_of, _ = parse_as_of("2025-06-30")
    # future NOTICE (financials only known after as_of)
    f_future, m_a = _peer_pack(PEER_A, pub="2025-07-15", mkt="2025-06-30")
    # known books but future price bar only
    f_b, m_future = _peer_pack(PEER_B, pub="2025-03-15", mkt="2025-07-15")
    # valid
    f_ok, m_ok = _peer_pack(PEER_C, pub="2025-03-15", mkt="2025-06-30")

    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=f_future + f_b + f_ok,
        market=m_a + m_future + m_ok,
        classifications=[_bank_cls(PEER_A), _bank_cls(PEER_B), _bank_cls(PEER_C)],
        use_lean_curated=False,
        extra_candidates=[PEER_A, PEER_B, PEER_C],
        fund_db="/nonexistent/r3_leakage.duckdb",
    )
    included_ids = {p.peer_instrument_id for p in rep.peers}
    assert included_ids == {PEER_C}
    reasons = {e.peer_instrument_id: e.reasons for e in rep.excluded}
    assert PEER_A in reasons
    assert PEER_B in reasons
    assert any(r.startswith("MISSING_") or r == "PIT_AFTER_ASOF" for r in reasons[PEER_A])
    assert "MISSING_RAW_CLOSE" in reasons[PEER_B] or "PIT_AFTER_ASOF" in reasons[PEER_B]


def test_thin_panel_empty_peers_with_funnel():
    """AC5: local thin panel → empty peers + exclusion funnel (honest scarcity)."""
    as_of, _ = parse_as_of("2025-06-30")
    # only subject financials present — no peer TE/OEI/market
    fins = [
        _f(SUBJ, "2024-12-31", "total_equity", 494e9, "2025-03-15"),
        _f(SUBJ, "2024-12-31", "other_equity_instruments", 70e9, "2025-03-15"),
        _f(SUBJ, "2024-12-31", "minority_interest", 0.0, "2025-03-15"),
    ]
    mkts = [_m(SUBJ, "2025-06-30", 12.0)]
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[_bank_cls(SUBJ)],
        use_lean_curated=True,
        fund_db="/nonexistent/r3_thin_panel.duckdb",
    )
    assert rep.peers == []
    assert len(rep.excluded) == len(rep.candidate_ids)
    assert rep.funnel
    assert "FI_PEER_UNIVERSE_EMPTY" in rep.flags
    assert sum(rep.funnel.values()) >= len(rep.candidate_ids)


def test_nonbank_veto_uses_latest_pit_classification_only():
    """Stale non-bank row must not veto a curated bank whose latest PIT class is deposit-taking."""
    as_of, _ = parse_as_of("2025-06-30")
    fins, mkts = _peer_pack(PEER_A)
    stale_nonbank = InstrumentClassification(
        instrument_id=PEER_A,
        scheme="SW2021_L1",
        industry="非银金融",
        published_at=_ts("2010-01-01"),
        source_id="em_f10_industry",
    )
    latest_bank = InstrumentClassification(
        instrument_id=PEER_A,
        scheme="SW2021_L1",
        industry=deposit_taking_fi_sw_label(),
        published_at=_ts("2020-01-01"),
        source_id="em_f10_industry",
    )
    # Order: latest first, then stale — must still include (latest wins regardless of order).
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[latest_bank, stale_nonbank],
        use_lean_curated=False,
        extra_candidates=[PEER_A],
        fund_db="/nonexistent/r3_nonbank_veto.duckdb",
    )
    assert {p.peer_instrument_id for p in rep.peers} == {PEER_A}
    assert PEER_A not in {e.peer_instrument_id for e in rep.excluded if "NOT_DEPOSIT_TAKING_FI" in e.reasons}


def test_latest_nonbank_still_vetoes_curated():
    as_of, _ = parse_as_of("2025-06-30")
    fins, mkts = _peer_pack(PEER_A)
    old_bank = InstrumentClassification(
        instrument_id=PEER_A, scheme="SW2021_L1", industry=deposit_taking_fi_sw_label(),
        published_at=_ts("2010-01-01"), source_id="em_f10_industry",
    )
    new_nonbank = InstrumentClassification(
        instrument_id=PEER_A, scheme="SW2021_L1", industry="非银金融",
        published_at=_ts("2024-01-01"), source_id="em_f10_industry",
    )
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[old_bank, new_nonbank],
        use_lean_curated=False,
        extra_candidates=[PEER_A],
        fund_db="/nonexistent/r3_latest_nonbank.duckdb",
    )
    assert rep.peers == []
    assert any("NOT_DEPOSIT_TAKING_FI" in e.reasons for e in rep.excluded if e.peer_instrument_id == PEER_A)


def test_peer_cflags_do_not_pollute_universe_flags():
    as_of, _ = parse_as_of("2025-06-30")
    # MI missing → MINORITY_EQUITY_ASSUMED_ZERO peer flag when zeros_explicit
    fins = [
        _f(PEER_A, "2024-12-31", "total_equity", 500e9, "2025-03-15"),
        _f(PEER_A, "2024-12-31", "other_equity_instruments", 50e9, "2025-03-15"),
    ]
    mkts = [_m(PEER_A, "2025-06-30", 40.0)]
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[_bank_cls(PEER_A)],
        use_lean_curated=False,
        extra_candidates=[PEER_A],
        zeros_explicit=True,
        fund_db="/nonexistent/r3_cflags.duckdb",
    )
    assert len(rep.peers) == 1
    assert not any(f.startswith("MINORITY_EQUITY_ASSUMED_ZERO") for f in rep.flags)
    assert not any(f.startswith("PB_") for f in rep.flags)
    diag = [d for d in rep.peer_diagnostics if d["peer_instrument_id"] == PEER_A and d["included"]]
    assert diag and any(x.startswith("MINORITY_EQUITY_ASSUMED_ZERO") for x in diag[0]["flags"])
    # Universe flags stay universe-scoped
    assert "FI_PEER_UNIVERSE_BUILDER" in rep.flags
    assert "RELATIVE_PRICING_ONLY" in rep.flags


def test_subject_allows_auto_fi_peers_gate():
    """Allow iff latest PIT SW == deposit_taking; never grant on FI profile alone."""
    as_of, _ = parse_as_of("2025-06-30")
    bank_cls = [_bank_cls(SUBJ)]
    # Honest missing-SW path: profile FI alone must NOT grant.
    assert not subject_allows_auto_fi_peers(
        primary_profile="FINANCIAL_INSTITUTION",
        instrument_id=SUBJ, as_of=as_of, classifications=[],
    )
    assert not subject_allows_auto_fi_peers(
        primary_profile="FINANCIAL_INSTITUTION",
        instrument_id=SUBJ, as_of=as_of, classifications=None,
    )
    # Deposit-taking SW grants even if profile is not FI.
    assert subject_allows_auto_fi_peers(
        primary_profile="HOLDING_OR_CONGLOMERATE",
        instrument_id=SUBJ, as_of=as_of, classifications=bank_cls,
    )
    assert subject_allows_auto_fi_peers(
        primary_profile="FINANCIAL_INSTITUTION",
        instrument_id=SUBJ, as_of=as_of, classifications=bank_cls,
    )
    # FI profile + 非银金融 SW must skip (insurance/broker etc.).
    nonbank = InstrumentClassification(
        instrument_id=SUBJ, scheme="SW2021_L1", industry="非银金融",
        published_at=_ts("2000-01-01"), source_id="em_f10_industry",
    )
    assert not subject_allows_auto_fi_peers(
        primary_profile="FINANCIAL_INSTITUTION",
        instrument_id=SUBJ, as_of=as_of, classifications=[nonbank],
    )
    assert not subject_allows_auto_fi_peers(
        primary_profile="GROWTH_OR_REINVESTMENT_HEAVY",
        instrument_id=SUBJ, as_of=as_of, classifications=[nonbank],
    )


# ---- R13: classifications-only default (drop lean dual-universe) ----


def test_r13_ac1_default_empty_plane_no_curated_bleed(tmp_path):
    """AC1: empty classifications + missing store → [] (no curated bleed)."""
    as_of, _ = parse_as_of("2025-06-30")
    missing = tmp_path / "no_such_fund.duckdb"
    ids = discover_bank_candidates(
        subject_instrument_id=SUBJ,
        classifications=[],
        as_of=as_of,
        fund_db=missing,
    )
    assert ids == []
    assert SUBJ not in ids
    assert not (set(LEAN_CURATED_DEPOSIT_TAKING_FI) & set(ids))


def test_r13_ac2_bank_label_classifications_minus_subject(tmp_path):
    """AC2: bank-label classifications → those IDs − subject."""
    as_of, _ = parse_as_of("2025-06-30")
    missing = tmp_path / "no_such_fund.duckdb"
    ids = discover_bank_candidates(
        subject_instrument_id=SUBJ,
        classifications=[_bank_cls(SUBJ), _bank_cls(PEER_A), _bank_cls(PEER_B)],
        as_of=as_of,
        fund_db=missing,
    )
    assert set(ids) == {PEER_A, PEER_B}
    assert SUBJ not in ids


def test_r13_ac3_store_sw_l1_proxy_bank_in_default_candidates(tmp_path):
    """AC3: store rows with sw_l1_proxy=bank_label appear in default candidates."""
    from vms.providers.eastmoney import store as em_store
    from vms.providers.hithink.paths import duckdb_available

    if not duckdb_available():
        pytest.skip("duckdb required for store fixture")
    as_of, _ = parse_as_of("2025-06-30")
    fdb = tmp_path / "fund_r13.duckdb"
    em_store.ensure_tables(fdb)
    bank = deposit_taking_fi_sw_label()
    em_store.upsert_industry(
        PEER_A,
        {"em_board": "主板", "csrc_industry": "货币金融服务", "sw_l1_proxy": bank,
         "listing_date": date(2002, 4, 9), "raw": {}},
        db_path=fdb,
    )
    em_store.upsert_industry(
        "600519.SH",
        {"em_board": "主板", "csrc_industry": "酒", "sw_l1_proxy": "食品饮料",
         "listing_date": date(2001, 8, 27), "raw": {}},
        db_path=fdb,
    )
    ids = discover_bank_candidates(
        subject_instrument_id=SUBJ,
        classifications=[],
        as_of=as_of,
        fund_db=fdb,
    )
    assert PEER_A in ids
    assert "600519.SH" not in ids
    assert SUBJ not in ids
    # curated must not bleed on default (601166 is curated but not in this store fixture)
    assert "601166.SH" not in ids
    assert not (set(LEAN_CURATED_DEPOSIT_TAKING_FI) - {PEER_A, SUBJ}) & set(ids)


def test_r13_ac5_lean_curated_true_still_unions(tmp_path):
    """AC5: use_lean_curated=True still unions curated (compat)."""
    as_of, _ = parse_as_of("2025-06-30")
    missing = tmp_path / "no_such_fund.duckdb"
    ids = discover_bank_candidates(
        subject_instrument_id=SUBJ,
        classifications=[],
        as_of=as_of,
        use_lean_curated=True,
        fund_db=missing,
    )
    assert SUBJ not in ids
    assert set(LEAN_CURATED_DEPOSIT_TAKING_FI) - {SUBJ} <= set(ids)


def test_r13_ac6_default_flags_classifications_only(tmp_path):
    """AC6: default flags include CLASSIFICATIONS_ONLY_CANDIDATES, not LEAN_CURATED."""
    as_of, _ = parse_as_of("2025-06-30")
    fins, mkts = _peer_pack(PEER_A)
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[_bank_cls(PEER_A)],
        fund_db=tmp_path / "no_such_fund.duckdb",
    )
    assert "CLASSIFICATIONS_ONLY_CANDIDATES" in rep.flags
    assert "LEAN_CURATED_CANDIDATES" not in rep.flags
    assert "RIM-FI-PEER-UNIVERSE-v2" in rep.assumption_ids
    lean = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=fins,
        market=mkts,
        classifications=[_bank_cls(PEER_A)],
        use_lean_curated=True,
        fund_db=tmp_path / "no_such_fund.duckdb",
    )
    assert "LEAN_CURATED_CANDIDATES" in lean.flags
    assert "CLASSIFICATIONS_ONLY_CANDIDATES" not in lean.flags


def test_r13_ac8_schema_package_min_iv_static():
    """AC8: SCHEMA / package / MIN / IV unchanged."""
    from vms import SCHEMA_VERSION, __version__
    from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS

    assert SCHEMA_VERSION == "vms-0.2.phase12"
    assert __version__ == "0.2.0rc1"
    assert MIN_HIST_PB_POINTS == 12
    as_of, _ = parse_as_of("2025-06-30")
    rep = build_fi_peer_observations(
        subject_instrument_id=SUBJ,
        as_of=as_of,
        financial=[],
        market=[],
        classifications=[],
        fund_db="/nonexistent/r13_ac8.duckdb",
    )
    assert rep.as_dict()["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_sf2_list_helper_logs_warning_on_query_error(tmp_path, caplog, monkeypatch):
    """SF2: query/schema Exception → [] + warning(exc_info); missing file stays silent."""
    import logging

    from vms.providers.eastmoney import store as em_store

    missing = tmp_path / "no_such_fund.duckdb"
    with caplog.at_level(logging.WARNING, logger="vms.providers.eastmoney.store"):
        assert em_store.list_deposit_taking_fi_thscodes(missing) == []
    assert not any("list_deposit_taking_fi_thscodes failed" in r.message for r in caplog.records)

    if not em_store.duckdb_available():
        return
    fdb = tmp_path / "sf2_fund.duckdb"
    em_store.ensure_tables(fdb)

    class _Boom:
        def execute(self, *_a, **_k):
            raise RuntimeError("sf2_schema_boom")

        def close(self):
            pass

    monkeypatch.setattr(em_store, "_connect", lambda *_a, **_k: _Boom())
    with caplog.at_level(logging.WARNING, logger="vms.providers.eastmoney.store"):
        assert em_store.list_deposit_taking_fi_thscodes(fdb) == []
    hits = [r for r in caplog.records if "list_deposit_taking_fi_thscodes failed" in r.message]
    assert len(hits) == 1
    assert hits[0].levelno == logging.WARNING
    assert hits[0].exc_info is not None
