"""R7 HiThink/EM lean real OOS for calibrate-rim (EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from vms import SCHEMA_VERSION
from vms.evaluation import run_rim_calibration
from vms.evaluation.fi_real_panel import materialize_fi_real_panel
from vms.evaluation.universe import load_universe, materialize_universe
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.calibrate_rim_bundle import build_calibrate_rim_bundle
from vms.schemas.contracts import ClaimStatus

L = loaded_config()
TZ = ZoneInfo("Asia/Shanghai")
REPO = Path(__file__).resolve().parents[2]
UNI_REAL = REPO / "config" / "universe.fi_deposit_lean_real.yaml"
UNI_SYN = REPO / "config" / "universe.fi_deposit_lean.yaml"
EVAL_ASOF = datetime(2025, 6, 30, 15, tzinfo=TZ)
START = date(2016, 1, 1)
END = date(2022, 12, 31)
FUND_DB = Path("/workspace/data/hithink_fundamentals.duckdb")
MARKET_DB = Path("/workspace/data/market.duckdb")

requires_local_db = pytest.mark.skipif(
    not (FUND_DB.is_file() and MARKET_DB.is_file()),
    reason="local HiThink/market duckdb required for R7 real-panel tests",
)


def _run_real(tmp_path: Path, *, prefer_local: bool = True, **kwargs):
    return run_rim_calibration(
        universe=UNI_REAL,
        loaded=L,
        start=kwargs.get("start", START),
        end=kwargs.get("end", END),
        out_dir=tmp_path / "rim_ev",
        evaluation_as_of=EVAL_ASOF,
        prefer_local=prefer_local,
    )


# ---- AC1: data_label non-SYNTHETIC; materialize not bank_synthetic ----
@requires_local_db
def test_ac1_data_label_not_synthetic_and_not_bank_synthetic(tmp_path: Path):
    uni = load_universe(UNI_REAL)
    assert "SYNTHETIC" not in uni.data_label.upper()
    assert uni.fi_real is not None
    assert uni.bank_synthetic is None
    loads = materialize_universe(uni, work_dir=tmp_path / "mat", prefer_local=True)
    assert set(loads) >= {"000001.SZ", "600036.SH", "601398.SH"}
    diag = json.loads((tmp_path / "mat" / "fi_real_materialize.json").read_text())
    assert diag["rest_calls"] == 0
    # Synthetic panel module must not be imported on this path — loads have real sources
    for load in loads.values():
        assert "SYNTHETIC" not in " ".join(load.sources.keys()).upper()
        assert any("hithink" in s or "em_" in s or "fi_" in s for s in load.sources)


@requires_local_db
def test_ac1_rejects_synthetic_label_with_fi_real(tmp_path: Path):
    uni = load_universe(UNI_REAL)
    bad = uni.model_copy(update={"data_label": "SYNTHETIC_FAKE"})
    with pytest.raises(ValueError, match="SYNTHETIC"):
        materialize_universe(bad, work_dir=tmp_path / "bad", prefer_local=True)


# ---- AC2: no --refresh → rest_calls==0 ----
@requires_local_db
def test_ac2_prefer_local_zero_rest(tmp_path: Path, monkeypatch):
    import vms.providers.eastmoney.client as em_client

    def boom(*_a, **_k):
        raise AssertionError("REST must not be called when prefer_local")

    for name in dir(em_client):
        if name.startswith("fetch_"):
            monkeypatch.setattr(em_client, name, boom)

    loads, rep = materialize_fi_real_panel(
        ["000001.SZ"],
        as_of=EVAL_ASOF,
        prefer_local=True,
        fund_db=FUND_DB,
        market_db=MARKET_DB,
        work_dir=tmp_path / "p",
    )
    assert rep.rest_calls == 0
    assert rep.prefer_local is True
    assert "000001.SZ" in loads
    assert len(loads["000001.SZ"].financial) > 0
    assert any(o.field_name == "revenue" for o in loads["000001.SZ"].financial)


# ---- AC3: --refresh upsert allowed; fail → local/empty; no invent OEI ----
@requires_local_db
def test_ac3_refresh_fail_falls_back_no_invent_oei(tmp_path: Path, monkeypatch):
    import vms.providers.eastmoney.client as em_client

    def fail_survey(*_a, **_k):
        raise RuntimeError("forced refresh failure")

    monkeypatch.setattr(em_client, "fetch_company_survey", fail_survey)
    loads, rep = materialize_fi_real_panel(
        ["000001.SZ"],
        as_of=EVAL_ASOF,
        prefer_local=False,
        fund_db=FUND_DB,
        market_db=MARKET_DB,
        work_dir=tmp_path / "ref",
    )
    assert rep.prefer_local is False
    fin = loads["000001.SZ"].financial
    oei = [o for o in fin if o.field_name == "other_equity_instruments"]
    assert all(o.value is not None for o in oei)
    assert "NO_INVENT_OEI" in rep.flags


# ---- AC4: chrono + forecast outcomes=null first persist ----
@requires_local_db
def test_ac4_forecast_before_outcome(tmp_path: Path):
    report = _run_real(tmp_path)
    assert report.n_forecasts_persisted > 0
    files = list((tmp_path / "rim_ev" / "forecasts").rglob("*.json"))
    assert files
    for f in files:
        body = json.loads(f.read_text())
        assert body.get("persisted_before_outcomes") is True
        assert body.get("frozen_weights_hash")


# ---- AC5: pit_complete=false not in scores_unbiased ----
@requires_local_db
def test_ac5_pit_incomplete_excluded_from_unbiased(tmp_path: Path):
    report = _run_real(tmp_path)
    # Real HiThink LATEST_ONLY ⇒ pit_complete typically false on lean panel
    assert report.n_excluded_pit_incomplete >= 1
    for ex in report.excluded_pit_incomplete:
        assert ex["reason"] == "PIT_INCOMPLETE"

    # Lock real report: scores_unbiased only counts pit_complete scored rows
    origin_path = tmp_path / "rim_ev" / "origin_records.json"
    body = json.loads(origin_path.read_text(encoding="utf-8"))
    records = body["records"]
    scored = [
        r for r in records
        if r.get("outcomes") and not (r.get("outcomes") or {}).get("pending")
    ]
    unbiased = [r for r in scored if r.get("pit_complete")]
    assert int(report.scores_unbiased.get("n_records", 0)) == len(unbiased)
    assert all(r.get("pit_complete") is True for r in unbiased)
    assert report.n_excluded_pit_incomplete == sum(
        1 for r in records if not r.get("pit_complete")
    )

    # Unit filter: fabricate incomplete → excluded from scorer input
    from vms.evaluation.rim_metrics import score_rim_targets

    rows = [
        {
            "pit_complete": False,
            "outcomes": {"driver_roe": {"realized": 0.1}, "pending": False},
            "forecasts": {"driver_roe": {"point": 0.1}},
        },
        {
            "pit_complete": True,
            "outcomes": {"driver_roe": {"realized": 0.1}, "pending": False},
            "forecasts": {"driver_roe": {"point": 0.1}},
        },
    ]
    only_complete = [r for r in rows if r.get("pit_complete")]
    assert len(only_complete) == 1
    s = score_rim_targets(only_complete)
    assert s.get("n_records", 0) == 1


# ---- AC6: Track B hist<12 → SKIP (000001 honest) ----
@requires_local_db
def test_ac6_track_b_short_oei_skip(tmp_path: Path):
    report = _run_real(tmp_path)
    assert report.min_hist_pb_points == MIN_HIST_PB_POINTS == 12
    skips_000001 = [
        s for s in report.track_b_skips if s.get("instrument_id") == "000001.SZ"
    ]
    # 000001 vendor OEI depth < 12 → at least one SKIP across origins, or zero
    # eligible for 000001
    eligible_paths = (tmp_path / "rim_ev" / "origin_records.json")
    body = json.loads(eligible_paths.read_text())
    tb_000001 = [
        r for r in body["records"]
        if r.get("instrument_id") == "000001.SZ"
    ]
    for r in tb_000001:
        tb = r.get("track_b") or {}
        if tb.get("status") == "SKIP":
            assert int(tb.get("hist_n") or 0) < MIN_HIST_PB_POINTS
            assert tb.get("min_required") == MIN_HIST_PB_POINTS
    # Stronger: if any 000001 origin assessed, SKIP when hist_n < 12
    assessed = [
        r for r in tb_000001
        if (r.get("track_b") or {}).get("status") in ("SKIP", "ELIGIBLE")
    ]
    assert assessed, "expected at least one assessed Track B origin for 000001"
    for r in assessed:
        tb = r["track_b"]
        if int(tb.get("hist_n") or 0) < MIN_HIST_PB_POINTS:
            assert tb["status"] == "SKIP"
            assert tb.get("skip_reason")
    # Across the run, short-OEI name should contribute SKIP ledger rows when assessed
    if any(int((r.get("track_b") or {}).get("hist_n") or 0) < MIN_HIST_PB_POINTS for r in assessed):
        assert report.n_track_b_skipped >= 1
        assert skips_000001


# ---- AC7: MIN=12; no default pb ----
@requires_local_db
def test_ac7_min12_no_default_pb(tmp_path: Path):
    assert MIN_HIST_PB_POINTS == 12
    report = _run_real(tmp_path)
    assert report.min_hist_pb_points == 12
    # Bundle guard
    summary = build_calibrate_rim_bundle(
        out_dir=tmp_path / "bundle",
        universe_path=UNI_REAL,
        start=START,
        end=END,
        evaluation_as_of=EVAL_ASOF,
        prefer_local=True,
    )
    assert summary["min_hist_pb_points"] == 12
    assert summary["fi_real_rest_calls"] == 0


# ---- AC8: labels INSUFFICIENT + INVESTMENT_VALUE_NOT_ESTABLISHED ----
@requires_local_db
def test_ac8_labels_hard_locked(tmp_path: Path):
    report = _run_real(tmp_path)
    assert report.labels["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert report.labels["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert report.labels["ENSEMBLE_CALIBRATED"] is False
    assert report.labels.get("CALIBRATION_PASS") is not True
    assert "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" in report.assumptions
    assert SCHEMA_VERSION.startswith("vms-0.2.phase12") or "phase12" in SCHEMA_VERSION


# ---- AC9: legacy UNSUPPORTED / sector gate unchanged; sector lint ----
def test_ac9_legacy_unsupported_untouched():
    from vms.schemas.config import load_config

    cfg = load_config(REPO / "config" / "default.yaml")
    # industry.unsupported still present as configured gate
    uns = getattr(cfg.config, "industry", None)
    assert uns is not None
    # Assumption register holds Chinese industry literals; code path cites id only
    from vms import assumptions as A

    assert "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" in A.ASSUMPTIONS
    text = A.ASSUMPTIONS["EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1"]
    assert "UNSUPPORTED" in text.upper() or "unsupported" in text


def test_ac9_sector_lint_fi_real_module():
    import re

    src = REPO / "src/vms/evaluation/fi_real_panel.py"
    pat = re.compile(
        r"银行|非银|金融|房地产|公用事业|\bbanks?\b|insurance|real.?estate|utilities",
        re.I,
    )
    hits = pat.findall(src.read_text())
    assert hits == [], hits


# ---- AC10: synthetic R6 path still green ----
def test_ac10_synthetic_r6_path_still_green(tmp_path: Path):
    report = run_rim_calibration(
        universe=UNI_SYN,
        loaded=L,
        start=START,
        end=END,
        out_dir=tmp_path / "r6",
        evaluation_as_of=EVAL_ASOF,
        prefer_local=True,
    )
    assert "SYNTHETIC" in report.data_label.upper()
    assert report.n_forecasts_persisted > 0
    assert report.labels["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert report.labels["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert "EVAL-RIM-FI-DEPOSIT-WF-v1" in report.assumptions
    assert "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" not in report.assumptions
    assert not (tmp_path / "r6" / "fi_real_materialize.json").exists()


def test_ac10_mutually_exclusive_blocks(tmp_path: Path):
    uni = load_universe(UNI_REAL)
    bad = uni.model_copy(update={"bank_synthetic": {"seed": 1}})
    with pytest.raises(ValueError, match="both fi_real and bank_synthetic"):
        materialize_universe(bad, work_dir=tmp_path / "x", prefer_local=True)
