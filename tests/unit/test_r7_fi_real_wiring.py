"""R7 fi_real wiring / prefer_local / refresh — always-on (mocked; no duckdb)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vms.data.io import LoadResult
from vms.evaluation.fi_real_panel import FiRealMaterializeReport, materialize_fi_real_panel
from vms.evaluation.universe import UniverseConfig, UniverseInstrument, materialize_universe
from vms.methods.rim.bank_peer_panel import TickerPathDiag
from vms.methods.rim.subject_hist_depth import SubjectHistDepthReport
from vms.schemas import ReportingConvention, SourceDescriptor, Versioning

TZ = ZoneInfo("Asia/Shanghai")
ASOF = datetime(2025, 6, 30, 15, tzinfo=TZ)


def _empty_depth(iid: str, *, prefer_local: bool, rest: int = 0) -> SubjectHistDepthReport:
    diag = TickerPathDiag(instrument_id=iid)
    diag.rest_calls = rest
    return SubjectHistDepthReport(
        instrument_id=iid,
        as_of=ASOF.isoformat(),
        financial=[],
        market=[],
        path_diag=diag,
        flags=["SUBJECT_HIST_DEPTH_BUILDER"],
        assumption_ids=["RIM-SUBJECT-HIST-DEPTH-v1"],
        rest_calls=rest,
        prefer_local=prefer_local,
        detail=f"rest_calls={rest}",
    )


def _empty_load() -> LoadResult:
    return LoadResult(
        sources={
            "hithink_em_notice": SourceDescriptor(
                source_id="hithink_em_notice",
                reporting_convention=ReportingConvention.CN_CUMULATIVE_YTD,
                versioning=Versioning.LATEST_ONLY,
            )
        },
        sources_provided=True,
    )


class _Diag:
    rest_notes: list = []
    enrichment: dict = {}
    price_diag: dict = {"rest_used": False}


def test_prefer_local_true_rest_calls_zero(monkeypatch, tmp_path):
    seen = {}

    def fake_fetch(thscode, **kwargs):
        seen["fetch_prefer_local"] = kwargs.get("prefer_local")
        seen["min_local"] = kwargs.get("min_local")
        assert kwargs.get("prefer_local") is True
        assert kwargs.get("min_local") == 0
        return _empty_load(), _Diag()

    def fake_depth(**kwargs):
        seen["depth_prefer_local"] = kwargs.get("prefer_local")
        return _empty_depth(kwargs["instrument_id"], prefer_local=True, rest=0)

    def fake_merge(load, depth):
        return load

    monkeypatch.setattr("vms.evaluation.fi_real_panel.fetch_bundle", fake_fetch)
    monkeypatch.setattr("vms.evaluation.fi_real_panel.build_subject_hist_depth", fake_depth)
    monkeypatch.setattr("vms.evaluation.fi_real_panel.merge_subject_hist_into_load", fake_merge)

    loads, rep = materialize_fi_real_panel(
        ["000001.SZ"], as_of=ASOF, prefer_local=True, work_dir=tmp_path,
    )
    assert seen["fetch_prefer_local"] is True
    assert seen["depth_prefer_local"] is True
    assert seen["min_local"] == 0
    assert rep.rest_calls == 0
    assert "000001.SZ" in loads


def test_prefer_local_false_refresh_wiring(monkeypatch, tmp_path):
    seen = {}

    class DiagRest(_Diag):
        rest_notes = ["income/annual: Recipe E HiThink upsert + re-read"]
        enrichment = {"bank_f10": {"path": "rest_upsert"}}
        price_diag = {"rest_used": True}

    def fake_fetch(thscode, **kwargs):
        seen["fetch_prefer_local"] = kwargs.get("prefer_local")
        seen["min_local"] = kwargs.get("min_local")
        return _empty_load(), DiagRest()

    def fake_depth(**kwargs):
        seen["depth_prefer_local"] = kwargs.get("prefer_local")
        return _empty_depth(kwargs["instrument_id"], prefer_local=False, rest=2)

    monkeypatch.setattr("vms.evaluation.fi_real_panel.fetch_bundle", fake_fetch)
    monkeypatch.setattr("vms.evaluation.fi_real_panel.build_subject_hist_depth", fake_depth)
    monkeypatch.setattr(
        "vms.evaluation.fi_real_panel.merge_subject_hist_into_load",
        lambda load, depth: load,
    )

    loads, rep = materialize_fi_real_panel(
        ["000001.SZ"], as_of=ASOF, prefer_local=False, work_dir=tmp_path,
    )
    assert seen["fetch_prefer_local"] is False
    assert seen["depth_prefer_local"] is False
    assert seen["min_local"] == 4
    assert rep.prefer_local is False
    assert rep.rest_calls >= 2


def test_materialize_universe_threads_prefer_local(monkeypatch, tmp_path):
    seen = {}

    def fake_panel(ids, **kwargs):
        seen["prefer_local"] = kwargs.get("prefer_local")
        seen["ids"] = list(ids)
        load = _empty_load()
        rep = FiRealMaterializeReport(
            instrument_ids=list(ids),
            prefer_local=bool(kwargs.get("prefer_local")),
            rest_calls=0 if kwargs.get("prefer_local") else 1,
            as_of=ASOF.isoformat(),
            fund_db="/tmp/f.duckdb",
            market_db="/tmp/m.duckdb",
        )
        return {"000001.SZ": load}, rep

    monkeypatch.setattr(
        "vms.evaluation.fi_real_panel.materialize_fi_real_panel", fake_panel,
    )
    uni = UniverseConfig(
        universe_id="t",
        data_label="HITHINK_EM_LEAN_FI",
        instruments=[UniverseInstrument(instrument_id="000001.SZ")],
        fi_real={"instrument_ids": ["000001.SZ"]},
    )
    materialize_universe(uni, work_dir=tmp_path / "a", prefer_local=True)
    assert seen["prefer_local"] is True
    assert (tmp_path / "a" / "fi_real_materialize.json").is_file()
    materialize_universe(uni, work_dir=tmp_path / "b", prefer_local=False)
    assert seen["prefer_local"] is False


def test_cli_refresh_sets_prefer_local_false(monkeypatch, tmp_path):
    from vms.cli import main as cli_main

    seen = {}

    def fake_bundle(**kwargs):
        seen.update(kwargs)
        return {
            "status": "R6_BANK_RIM_WALK_FORWARD_CALIBRATION_NOT_INVESTMENT_ADVICE",
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            "labels": {
                "ENSEMBLE_CALIBRATED": False,
                "CALIBRATION_PASS": None,
                "CALIBRATION_CLAIM": "CALIBRATION_INSUFFICIENT",
            },
            "calibration_claim": "CALIBRATION_INSUFFICIENT",
            "min_hist_pb_points": 12,
            "schema_version": "vms-0.2.phase12",
            "split_mode": "chronological",
            "prefer_local": kwargs.get("prefer_local"),
            "fi_real_rest_calls": 0,
        }

    monkeypatch.setattr(cli_main, "build_calibrate_rim_bundle", fake_bundle)
    monkeypatch.setattr(
        cli_main,
        "dump_calibrate_rim_summary",
        lambda s: json.dumps(s) + "\n",
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "rim_calibration_report.json").write_text("{}")
    (out / "frozen_weights.json").write_text("{}")

    rc = cli_main.main([
        "calibrate-rim",
        "--out", str(out),
        "--universe", str(tmp_path / "u.yaml"),
        "--refresh",
    ])
    assert rc == 0
    assert seen.get("prefer_local") is False

    rc = cli_main.main([
        "calibrate-rim",
        "--out", str(out),
        "--universe", str(tmp_path / "u.yaml"),
    ])
    assert rc == 0
    assert seen.get("prefer_local") is True
