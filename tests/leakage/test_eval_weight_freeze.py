"""Leakage: ensemble weights/thresholds frozen before test window; no future peer/price into eval."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from vms.evaluation import assert_weights_unchanged, freeze_weights_before_test, run_evaluation
from vms.evaluation.universe import generate_eval_panel

L = loaded_config()
TZ = ZoneInfo("Asia/Shanghai")
UNI = Path(__file__).resolve().parents[2] / "config" / "universe.synthetic.yaml"


def test_frozen_weights_hash_stable_across_scoring(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
        ensemble_weights={"a": 0.5, "b": 0.5},
    )
    freeze_path = tmp_path / "ev" / "frozen_weights.json"
    assert freeze_path.is_file()
    freeze = json.loads(freeze_path.read_text())
    assert freeze["frozen_before_test"] is True
    assert freeze["test_window_start"] == "2018-01-01"
    assert report.frozen_weights["content_hash"] == freeze["content_hash"]
    # All persisted forecasts reference the same freeze hash
    hashes = set()
    for f in (tmp_path / "ev" / "forecasts").rglob("*.json"):
        hashes.add(json.loads(f.read_text())["frozen_weights_hash"])
    assert hashes == {freeze["content_hash"]}


def test_mutating_weights_after_freeze_detected(tmp_path: Path):
    freeze = freeze_weights_before_test(
        weights={"fcff_dcf": 1.0},
        thresholds={},
        test_window_start=date(2019, 1, 1),
        out_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="ENSEMBLE_WEIGHTS_MUTATED_AFTER_FREEZE"):
        assert_weights_unchanged(freeze, {"fcff_dcf": 0.0, "pe": 1.0})


def test_no_future_price_in_forecast_payload(tmp_path: Path):
    """Forecast files at persist time must not embed realized future prices as truth."""
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2021, 12, 31),
        out_dir=tmp_path / "ev2",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    assert report.n_forecasts_persisted > 0
    for f in (tmp_path / "ev2" / "forecasts").rglob("*.json"):
        body = json.loads(f.read_text())
        # Intrinsic block must forbid price MAE as truth even after outcomes attached
        assert "forecasts" in body
        # Outcomes may exist now, but IV note forbids price-as-truth
        if body.get("outcomes") and not body["outcomes"].get("pending"):
            iv = body["outcomes"].get("intrinsic_value") or {}
            assert iv.get("realized_price_not_used_as_truth") is True


def test_panel_origins_use_only_past_publications():
    panel = generate_eval_panel(seed=3, n_instruments=1, start_year=2015, n_years=8)
    iid, load = next(iter(panel.items()))
    # Every FY publication must be strictly after period_end (no look-ahead publish)
    for f in load.financial:
        if f.field_name == "revenue" and f.period_end.month == 12:
            assert f.published_at.date() > f.period_end
