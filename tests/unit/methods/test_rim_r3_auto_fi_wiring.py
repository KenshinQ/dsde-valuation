"""R3 wiring: value-rim auto FI peers gate, skip-when-peers-present, CLI disable flag."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from vms.data.io import LoadResult
from vms.methods.rim.bank_peers import EXCLUSION_MISSING_OEI
from vms.methods.rim.hist_pb import PEER_FIELD_PB_COMMON
from vms.pit.asof import parse_as_of
from vms.providers.eastmoney.industry import deposit_taking_fi_sw_label
from vms.reporting.value_rim_bundle import build_value_rim_bundle
from vms.schemas import (
    CorporateActionEvent,
    FinancialObservation,
    InstrumentClassification,
    MarketObservation,
    PeerObservation,
    SourceDescriptor,
)
from vms.schemas.config import load_config
from vms.schemas.fields import get_field
from vms.schemas.observations import QualityStatus

CST = timezone(timedelta(hours=8))
INST = "000001.SZ"
PEER_A = "600036.SH"
PEER_B = "601398.SH"
PEER_C = "601288.SH"
PEER_D = "601939.SH"
PEER_E = "601988.SH"
SHARES = 1.9405918198e10
PEER_SHARES = 1.0e10


def _ts(d: str, hh: int = 18) -> datetime:
    return datetime.combine(date.fromisoformat(d), time(hh), CST)


def _f(inst: str, period_end: str, field: str, value, pub: str) -> FinancialObservation:
    cf = get_field(field)
    return FinancialObservation(
        instrument_id=inst,
        period_end=date.fromisoformat(period_end),
        published_at=_ts(pub),
        statement_type=cf.statement_type if cf else "income",
        field_name=field,
        value=value,
        currency="CNY",
        unit_scale="unit",
        source_id="S",
        revision_id="r0",
        quality_status="observed",
    )


def _m(inst: str, d: str, px: float, shares: float) -> MarketObservation:
    return MarketObservation(
        instrument_id=inst, timestamp=_ts(d, 15), raw_close=px,
        adjusted_close=None, shares_outstanding=shares, currency="CNY", source_id="S",
    )


def _bank_cls(inst: str, industry: str | None = None) -> InstrumentClassification:
    return InstrumentClassification(
        instrument_id=inst,
        scheme="SW2021_L1",
        industry=industry or deposit_taking_fi_sw_label(),
        published_at=_ts("2000-01-01", 15),
        source_id="em_f10_industry",
    )


def _subject_pack() -> tuple[list[FinancialObservation], list[MarketObservation], list[CorporateActionEvent]]:
    fins: list[FinancialObservation] = []
    series = [
        (2019, 300e9, 40e9, 1.4, 28e9),
        (2020, 330e9, 45e9, 1.5, 30e9),
        (2021, 360e9, 50e9, 1.7, 35e9),
        (2022, 400e9, 55e9, 1.9, 40e9),
        (2023, 472.0e9, 69.55e9, 2.25, 46.455e9),
        (2024, 494.842e9, 69.948e9, 2.15, 44.508e9),
    ]
    for y, te, oei, eps, ni in series:
        pe, pub = f"{y}-12-31", f"{y+1}-03-15"
        fins.extend([
            _f(INST, pe, "total_equity", te, pub),
            _f(INST, pe, "parent_net_income", ni, pub),
            _f(INST, pe, "revenue", 150e9, pub),
            _f(INST, pe, "dividends_paid", 20e9, pub),
            _f(INST, pe, "total_assets", te * 10, pub),
            _f(INST, pe, "total_liabilities", te * 9, pub),
            _f(INST, pe, "other_equity_instruments", oei, pub),
            _f(INST, pe, "minority_interest", 0.0, pub),
            _f(INST, pe, "basic_eps", eps, pub),
            _f(INST, pe, "goodwill", 7.568e9, pub),
            _f(INST, pe, "other_comprehensive_income", -0.3e9, pub),
            _f(INST, pe, "interest_income", 180e9, pub),
        ])
    mkts = [
        _m(INST, f"{y}-12-30", 12.0, SHARES) for y, *_ in series
    ]
    mkts.append(_m(INST, "2025-06-30", 12.07, SHARES))
    cas = [
        CorporateActionEvent(
            action_id="em:000001:2024-12-31:cash", instrument_id=INST, action_type="cash_dividend",
            announced_at=_ts("2025-03-15", 15), ex_date=date.fromisoformat("2025-06-12"),
            cash_per_share=0.362, currency="CNY", source_id="em_sharebonus",
        ),
        CorporateActionEvent(
            action_id="em:000001:2024-06-30:cash", instrument_id=INST, action_type="cash_dividend",
            announced_at=_ts("2024-08-16", 15), ex_date=date.fromisoformat("2024-10-10"),
            cash_per_share=0.246, currency="CNY", source_id="em_sharebonus",
        ),
    ]
    return fins, mkts, cas


def _peer_rows(pid: str, *, te: float = 500e9, oei: float = 50e9, px: float = 40.0):
    fins = [
        _f(pid, "2024-12-31", "total_equity", te, "2025-03-15"),
        _f(pid, "2024-12-31", "other_equity_instruments", oei, "2025-03-15"),
        _f(pid, "2024-12-31", "minority_interest", 0.0, "2025-03-15"),
    ]
    mkts = [_m(pid, "2025-06-30", px, PEER_SHARES)]
    return fins, mkts


def _load(*, with_peers_panel: bool = True, peers: list[PeerObservation] | None = None,
          subject_industry: str | None = None) -> LoadResult:
    fins, mkts, cas = _subject_pack()
    classes = [_bank_cls(INST, subject_industry)]
    if with_peers_panel:
        for i, pid in enumerate([PEER_A, PEER_B, PEER_C, PEER_D, PEER_E]):
            pf, pm = _peer_rows(pid, te=400e9 + i * 10e9, oei=40e9, px=30.0 + i)
            fins.extend(pf)
            mkts.extend(pm)
            classes.append(_bank_cls(pid))
    return LoadResult(
        financial=fins, market=mkts, corporate_actions=cas,
        sources={
            "S": SourceDescriptor(source_id="S", reporting_convention="CN_CUMULATIVE_YTD",
                                  versioning="FULL_HISTORY"),
            "em_sharebonus": SourceDescriptor(source_id="em_sharebonus", reporting_convention="UNKNOWN",
                                              versioning="LATEST_ONLY"),
        },
        classifications=classes,
        corporate_actions_provided=True,
        peers=list(peers or []),
    )


def _run(repo: Path, tmp_path: Path, load: LoadResult, *, auto_fi_peers: bool = True,
         run_distribution: bool = False, run_track_b: bool = False):
    loaded = load_config(repo / "config/default.yaml")
    as_of, note = parse_as_of("2025-06-30")
    out = tmp_path / "rim_out"
    return build_value_rim_bundle(
        out_dir=out,
        load=load,
        input_dir=tmp_path / "data",
        instrument_id=INST,
        as_of=as_of,
        as_of_note=note,
        loaded=loaded,
        mode="exploratory",
        override_reason="R3 wiring unit: synthetic bank PIT",
        years=5,
        zeros_explicit=True,
        run_distribution=run_distribution,
        run_pb_roe=True,
        run_track_b=run_track_b,
        n_paths=20,
        seed=7,
        auto_fi_peers=auto_fi_peers,
        peer_min_count=5,
    ), out


def test_wiring_empty_peers_auto_on_builds(repo, tmp_path):
    load = _load(with_peers_panel=True, peers=[])
    summ, out = _run(repo, tmp_path, load, auto_fi_peers=True)
    assert "AUTO_FI_PEERS" in summ["flags"]
    assert "AUTO_FI_PEERS_DISABLED" not in summ["flags"]
    assert "AUTO_FI_PEERS_SKIPPED_NON_FI" not in summ["flags"]
    assert summ["fi_peers"] is not None
    assert summ["fi_peers"]["n_peers"] >= 5
    assert (out / "rim_fi_peers.json").exists()
    import json
    fi = json.loads((out / "rim_fi_peers.json").read_text())
    # Peer-level cflags must not land in universe flags (nor solely from auto-merge).
    assert not any(f.startswith("MINORITY_EQUITY_ASSUMED_ZERO") for f in fi["flags"])
    assert not any(f.startswith("PB_NUMERATOR_") or f.startswith("PB_DENOMINATOR_") for f in fi["flags"])
    assert fi["peer_diagnostics"], "peer cflags belong in peer_diagnostics"
    # Universe flags that auto-merge into bundle are OK; peer cflags must not be the only source
    assert "FI_PEER_UNIVERSE_BUILDER" in fi["flags"]
    assert summ["pb_roe"]["ok"] is True or summ["pb_roe"]["peer_n_included"] >= 5


def test_wiring_existing_load_peers_skips_auto(repo, tmp_path):
    as_of, _ = parse_as_of("2025-06-30")
    preexisting = [
        PeerObservation(
            subject_instrument_id=INST,
            peer_instrument_id=pid,
            published_at=_ts("2025-03-15"),
            field_name=PEER_FIELD_PB_COMMON,
            value=1.2 + i * 0.1,
            currency="CNY",
            unit_scale="unit",
            metric_timestamp=_ts("2025-06-30", 15),
            source_id="manual",
            quality_status=QualityStatus.OBSERVED,
            revision_id="preexisting",
        )
        for i, pid in enumerate([PEER_A, PEER_B, PEER_C, PEER_D, PEER_E])
    ]
    load = _load(with_peers_panel=False, peers=preexisting)
    summ, out = _run(repo, tmp_path, load, auto_fi_peers=True)
    assert "AUTO_FI_PEERS" not in summ["flags"]
    assert summ["fi_peers"] is None
    assert not (out / "rim_fi_peers.json").exists()
    assert summ["pb_roe"] is not None


def test_wiring_no_auto_fi_peers_flag(repo, tmp_path):
    load = _load(with_peers_panel=True, peers=[])
    summ, out = _run(repo, tmp_path, load, auto_fi_peers=False)
    assert "AUTO_FI_PEERS_DISABLED" in summ["flags"]
    assert "AUTO_FI_PEERS" not in summ["flags"]
    assert summ["fi_peers"] is None
    assert not (out / "rim_fi_peers.json").exists()


def test_wiring_fi_gate_skips_non_fi_subject(repo, tmp_path, monkeypatch):
    """Non-FI / non-deposit subject must not scan bank peer universe."""
    from vms.reporting import value_rim_bundle as vrb

    load = _load(with_peers_panel=True, peers=[])
    monkeypatch.setattr(vrb, "subject_allows_auto_fi_peers", lambda **kw: False)
    summ, out = _run(repo, tmp_path, load, auto_fi_peers=True)
    assert "AUTO_FI_PEERS_SKIPPED_NON_FI" in summ["flags"]
    assert "AUTO_FI_PEERS" not in summ["flags"]
    assert summ["fi_peers"] is None
    assert not (out / "rim_fi_peers.json").exists()


def test_wiring_fi_gate_on_for_financial_institution(repo, tmp_path):
    load = _load(with_peers_panel=True, peers=[])
    summ, _ = _run(repo, tmp_path, load, auto_fi_peers=True)
    assert summ["profile_primary"] == "FINANCIAL_INSTITUTION"
    assert "AUTO_FI_PEERS" in summ["flags"]
    assert "AUTO_FI_PEERS_SKIPPED_NON_FI" not in summ["flags"]


def test_exclusion_alias_table_exported():
    assert EXCLUSION_MISSING_OEI == "MISSING_OTHER_EQUITY_INSTRUMENTS"
    from vms.methods.rim.bank_peers import EXCLUSION_CODE_ALIASES
    assert EXCLUSION_CODE_ALIASES["MISSING_OEI"] == EXCLUSION_MISSING_OEI
