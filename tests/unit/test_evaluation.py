"""Phase 9: chronological-only splits, forecast-before-outcome, separate targets, investment labels."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from vms.evaluation import RandomSplitProhibitedError, require_chronological, run_evaluation
from vms.evaluation.labels import assign_labels
from vms.evaluation.protocol import enumerate_fy_origins
from vms.evaluation.universe import generate_eval_panel, load_universe
from vms.engine import ValuationEngine

L = loaded_config()
TZ = ZoneInfo("Asia/Shanghai")
UNI = Path(__file__).resolve().parents[2] / "config" / "universe.synthetic.yaml"


def test_refuse_random_splits():
    with pytest.raises(RandomSplitProhibitedError):
        require_chronological("random")
    with pytest.raises(RandomSplitProhibitedError):
        require_chronological("shuffle")
    require_chronological("chronological")  # ok


def test_refuse_random_splits_via_run_evaluation(tmp_path: Path):
    with pytest.raises(RandomSplitProhibitedError):
        run_evaluation(universe=UNI, loaded=L, start=date(2018, 1, 1), end=date(2023, 12, 31),
                       out_dir=tmp_path / "bad", split_mode="random")


def test_forecasts_persisted_before_outcomes(tmp_path: Path):
    report = run_evaluation(universe=UNI, loaded=L, start=date(2018, 1, 1), end=date(2022, 12, 31),
                            out_dir=tmp_path / "ev", evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ))
    assert report.n_forecasts_persisted > 0
    # inspect a forecast file for the flag
    fdir = tmp_path / "ev" / "forecasts"
    files = list(fdir.rglob("*.json"))
    assert files
    for f in files[:3]:
        body = json.loads(f.read_text())
        assert body.get("persisted_before_outcomes") is True
        assert "forecasts" in body and "baselines" in body


def test_targets_scored_separately_and_iv_not_price(tmp_path: Path):
    report = run_evaluation(universe=UNI, loaded=L, start=date(2018, 1, 1), end=date(2022, 12, 31),
                            out_dir=tmp_path / "ev2", evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ))
    s = report.scores_unbiased
    for key in ("operating_cash_flow", "intrinsic_value", "market_price", "total_shareholder_return"):
        assert key in s
    assert s["intrinsic_value"].get("price_mae_forbidden") is True
    assert "central_dcf" in report.baselines_present
    assert "exit_multiple" in report.baselines_present or "historical_median" in report.baselines_present


def test_investment_value_not_established_on_synthetic(tmp_path: Path):
    report = run_evaluation(universe=UNI, loaded=L, start=date(2018, 1, 1), end=date(2022, 12, 31),
                            out_dir=tmp_path / "ev3", evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ))
    assert report.labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert report.labels["ENGINEERING_PASS"] is True
    # assign_labels guard
    lab = assign_labels(engineering_ok=True, data_quality_ok=True, calibration_ok=True,
                        data_label="SYNTHETIC", predeclared_oos_alpha=True)
    assert lab["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"


def test_pit_incomplete_excluded_from_unbiased(tmp_path: Path):
    # panel has FULL_HISTORY so excluded may be 0; still ensure field exists and unbiased <= all
    report = run_evaluation(universe=UNI, loaded=L, start=date(2018, 1, 1), end=date(2022, 12, 31),
                            out_dir=tmp_path / "ev4", evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ))
    assert report.scores_unbiased["n_records"] <= report.scores["n_records"]
    assert isinstance(report.excluded_pit_incomplete, list)


def test_origins_chronological():
    panel = generate_eval_panel(seed=1, n_instruments=1, start_year=2015, n_years=8)
    iid, load = next(iter(panel.items()))
    origins = enumerate_fy_origins(load, instrument_id=iid, start=date(2018, 1, 1), end=date(2023, 12, 31),
                                   min_history_years=3)
    assert origins
    years = [y for y, _ in origins]
    assert years == sorted(years)


def test_engine_evaluate(tmp_path: Path):
    eng = ValuationEngine(L)
    report = eng.evaluate(universe=UNI, start=date(2018, 1, 1), end=date(2021, 12, 31),
                          out_dir=tmp_path / "eng", evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ))
    assert report.content_hash
