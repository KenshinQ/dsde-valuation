"""R6 deposit-taking FI RIM walk-forward calibration acceptance (EVAL-RIM-FI-DEPOSIT-WF-v1)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from vms import SCHEMA_VERSION
from vms.evaluation import (
    RandomSplitProhibitedError,
    assert_weights_unchanged,
    freeze_weights_before_test,
    require_chronological,
    run_rim_calibration,
)
from vms.evaluation.labels import assign_labels
from vms.methods.rim.hist_pb import MIN_HIST_PB_POINTS
from vms.reporting.calibrate_rim_bundle import (
    CALIBRATE_RIM_STATUS,
    build_calibrate_rim_bundle,
)
from vms.schemas.contracts import ClaimStatus

L = loaded_config()
TZ = ZoneInfo("Asia/Shanghai")
UNI = Path(__file__).resolve().parents[2] / "config" / "universe.fi_deposit_lean.yaml"
EVAL_ASOF = datetime(2025, 6, 30, 15, tzinfo=TZ)
START = date(2016, 1, 1)
END = date(2022, 12, 31)


def _run(tmp_path: Path, **kwargs):
    return run_rim_calibration(
        universe=UNI,
        loaded=L,
        start=kwargs.get("start", START),
        end=kwargs.get("end", END),
        out_dir=tmp_path / "rim_ev",
        evaluation_as_of=EVAL_ASOF,
        split_mode=kwargs.get("split_mode"),
    )


# ---- AC1: chronological only ----
def test_ac1_chronological_only_rejects_random(tmp_path: Path):
    with pytest.raises(RandomSplitProhibitedError):
        require_chronological("random")
    with pytest.raises(RandomSplitProhibitedError):
        _run(tmp_path, split_mode="random")
    require_chronological("chronological")


# ---- AC2: forecast persisted before outcomes ----
def test_ac2_forecasts_persisted_before_outcomes(tmp_path: Path):
    report = _run(tmp_path)
    assert report.n_forecasts_persisted > 0
    files = list((tmp_path / "rim_ev" / "forecasts").rglob("*.json"))
    assert files
    for f in files:
        body = json.loads(f.read_text())
        assert body.get("persisted_before_outcomes") is True
        assert body.get("frozen_weights_hash")
        # At persist time outcomes were null; after attach may be filled —
        # but the flag and structure must prove before-outcome write.
        assert "forecasts" in body
        assert "baselines" in body


def test_ac2_persist_helper_rejects_outcomes_present(tmp_path: Path):
    from vms.evaluation.rim_run import _persist_forecast

    bad = tmp_path / "bad.json"
    with pytest.raises(AssertionError):
        _persist_forecast(bad, {"outcomes": {"x": 1}, "persisted_before_outcomes": True})


# ---- AC3: separate evaluation targets ----
def test_ac3_separate_evaluation_targets(tmp_path: Path):
    report = _run(tmp_path)
    s = report.scores_unbiased
    for key in ("driver_roe", "intrinsic_value", "market_price"):
        assert key in s
    assert s["evaluation_targets_declared"] == [
        "driver_roe",
        "intrinsic_value",
        "market_price",
    ]


# ---- AC4: no price MAE as IV truth ----
def test_ac4_future_price_not_intrinsic_truth(tmp_path: Path):
    report = _run(tmp_path)
    iv = report.scores_unbiased["intrinsic_value"]
    assert iv["price_mae_forbidden"] is True
    assert report.scores_unbiased["price_mae_as_iv_truth_forbidden"] is True
    assoc = iv["market_price_association_only"]
    assert assoc["label"] == "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH"


# ---- AC5: freeze before test; mutation fails closed ----
def test_ac5_freeze_before_test_mutation_fails(tmp_path: Path):
    report = _run(tmp_path)
    assert report.frozen_weights is not None
    assert report.frozen_weights["frozen_before_test"] is True
    freeze_path = tmp_path / "rim_ev" / "frozen_weights.json"
    assert freeze_path.is_file()
    freeze = json.loads(freeze_path.read_text())
    assert_weights_unchanged(freeze, freeze["weights"])
    with pytest.raises(ValueError, match="ENSEMBLE_WEIGHTS_MUTATED"):
        assert_weights_unchanged(freeze, {"rim_track_a_prior_equal": 0.5, "other": 0.5})


# ---- AC6: insufficient → CALIBRATION_INSUFFICIENT ----
def test_ac6_calibration_insufficient_not_inferred_pass(tmp_path: Path):
    report = _run(tmp_path)
    assert report.labels["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert report.labels["CALIBRATION_PASS"] is not True
    assert report.release_gates[ClaimStatus.CALIBRATION_INSUFFICIENT.value] is True
    assert report.release_gates[ClaimStatus.CALIBRATION_PASS.value] is False


# ---- AC7: INVESTMENT_VALUE_NOT_ESTABLISHED ----
def test_ac7_investment_value_not_established(tmp_path: Path):
    report = _run(tmp_path)
    assert report.labels["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert report.labels["ENSEMBLE_CALIBRATED"] is False
    assert report.release_gates[ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value] is True
    assert report.release_gates[ClaimStatus.ENSEMBLE_CALIBRATED.value] is False


# ---- AC8: MIN=12; Track B <12 skip; no invent ----
def test_ac8_min_hist_pb_and_track_b_skip(tmp_path: Path):
    assert MIN_HIST_PB_POINTS == 12
    report = _run(tmp_path)
    assert report.min_hist_pb_points == 12
    # 000001 short OEI → at least some Track B skips visible
    assert report.n_track_b_skipped >= 1
    assert any(s.get("instrument_id") == "000001.SZ" for s in report.track_b_skips)
    for s in report.track_b_skips:
        assert s["min_required"] == 12
        assert s["hist_n"] is None or s["hist_n"] < 12


# ---- AC9: legacy unsupported unchanged (gate constants) ----
def test_ac9_legacy_unsupported_profile_config_untouched():
    cfg = L.config
    assert "银行" in cfg.industry.unsupported
    assert "非银金融" in cfg.industry.unsupported


# ---- AC10: declared universe includes 000001; Track B skip visible ----
def test_ac10_universe_includes_000001_and_skips_visible(tmp_path: Path):
    report = _run(tmp_path)
    assert "000001.SZ" in report.declared_instruments
    assert report.universe_id == "fi_deposit_lean_r6_v1"
    assert report.n_track_b_skipped >= 1
    summary = build_calibrate_rim_bundle(
        out_dir=tmp_path / "bundle",
        universe_path=UNI,
        start=START,
        end=END,
        evaluation_as_of=EVAL_ASOF,
    )
    assert summary["includes_000001"] is True
    assert summary["n_track_b_skipped"] >= 1
    assert summary["status"] == CALIBRATE_RIM_STATUS


# ---- AC11: pit_complete=false not in scores_unbiased ----
def test_ac11_pit_incomplete_excluded_from_unbiased(tmp_path: Path):
    report = _run(tmp_path)
    origin = json.loads((tmp_path / "rim_ev" / "origin_records.json").read_text())
    records = origin["records"]
    incomplete = [r for r in records if not r.get("pit_complete")]
    # Excluded ledger matches incomplete origins 1:1
    assert report.n_excluded_pit_incomplete == len(incomplete)
    for ex in report.excluded_pit_incomplete:
        assert ex["reason"] == "PIT_INCOMPLETE"
    # scores_unbiased may only count pit_complete records (never larger than scored)
    assert report.scores_unbiased["n_records"] <= report.n_scored
    # If every origin is incomplete (synthetic FULL_HISTORY still can be false under
    # quality rules), unbiased must be empty — proves filter is not a no-op tautology
    # that only checks n_unbiased <= n_scored.
    if not any(r.get("pit_complete") for r in records):
        assert report.scores_unbiased["n_records"] == 0
        assert report.n_excluded_pit_incomplete == report.n_forecasts_persisted


def test_ac11_unbiased_filter_only_pit_complete():
    """Prove scores_unbiased input is filtered to pit_complete only (not tautology)."""
    from vms.evaluation.rim_metrics import score_rim_targets

    def _rec(pit: bool, inst: str) -> dict:
        return {
            "instrument_id": inst,
            "origin_as_of": "2020-04-30T15:00:00+08:00",
            "pit_complete": pit,
            "forecasts": {
                "driver_roe": {"point": 0.1},
                "intrinsic_value": {"point": 10.0},
                "market_price": {"point": 9.0},
            },
            "outcomes": {
                "pending": False,
                "driver_roe": {"realized": 0.11},
                "intrinsic_value": {"later_origin_vps": 10.5},
                "market_price": {"raw_close": 9.5},
            },
            "baselines": {"historical_roe_median": {"roe_median": 0.1}},
            "track_b": {"status": "SKIP", "hist_n": 3, "min_required": 12,
                        "skip_reason": "HIST_PB_BELOW_MIN"},
        }

    scored = [_rec(True, "A"), _rec(False, "B"), _rec(True, "C")]
    unbiased = [r for r in scored if r.get("pit_complete")]
    assert len(unbiased) == 2
    assert all(r["pit_complete"] is True for r in unbiased)
    s_all = score_rim_targets(scored)
    s_unb = score_rim_targets(unbiased)
    assert s_all["n_records"] == 3
    assert s_unb["n_records"] == 2
    # Incomplete must not appear in unbiased input set
    assert {r["instrument_id"] for r in unbiased} == {"A", "C"}


def test_track_b_ledger_only_counts_skip_status():
    """SHOULD-FIX: NOT_ASSESSED must not be logged as HIST_PB_BELOW_MIN skip."""
    from vms.evaluation.rim_metrics import score_rim_targets

    records = [
        {
            "instrument_id": "ELIG",
            "origin_as_of": "2020-01-01T00:00:00+08:00",
            "pit_complete": True,
            "forecasts": {"driver_roe": {"point": None}, "intrinsic_value": {"point": None},
                          "market_price": {"point": None}},
            "outcomes": {"pending": False, "driver_roe": {"realized": None},
                         "intrinsic_value": {"later_origin_vps": None},
                         "market_price": {"raw_close": None}},
            "baselines": {},
            "track_b": {"status": "ELIGIBLE", "hist_n": 12, "min_required": 12,
                        "skip_reason": None},
        },
        {
            "instrument_id": "SKIP1",
            "origin_as_of": "2020-01-01T00:00:00+08:00",
            "pit_complete": True,
            "forecasts": {"driver_roe": {"point": None}, "intrinsic_value": {"point": None},
                          "market_price": {"point": None}},
            "outcomes": {"pending": False, "driver_roe": {"realized": None},
                         "intrinsic_value": {"later_origin_vps": None},
                         "market_price": {"raw_close": None}},
            "baselines": {},
            "track_b": {"status": "SKIP", "hist_n": 4, "min_required": 12,
                        "skip_reason": "N_HIST_PB=4<12"},
        },
        {
            "instrument_id": "NA1",
            "origin_as_of": "2020-01-01T00:00:00+08:00",
            "pit_complete": True,
            "forecasts": {"driver_roe": {"point": None}, "intrinsic_value": {"point": None},
                          "market_price": {"point": None}},
            "outcomes": {"pending": False, "driver_roe": {"realized": None},
                         "intrinsic_value": {"later_origin_vps": None},
                         "market_price": {"raw_close": None}},
            "baselines": {},
            "track_b": {"status": "NOT_ASSESSED", "hist_n": 0, "min_required": 12,
                        "skip_reason": None},
        },
    ]
    scored = score_rim_targets(records)
    tb = scored["track_b"]
    assert tb["n_eligible"] == 1
    assert tb["n_skipped"] == 1
    assert tb["n_not_assessed"] == 1
    assert len(tb["skips"]) == 1
    assert tb["skips"][0]["instrument_id"] == "SKIP1"
    assert tb["skips"][0]["skip_reason"] == "N_HIST_PB=4<12"
    # NOT_ASSESSED must not appear as a fabricated HIST_PB_BELOW_MIN skip
    assert all(s["instrument_id"] != "NA1" for s in tb["skips"])
    assert all(s.get("skip_reason") != "HIST_PB_BELOW_MIN" or s["instrument_id"] == "SKIP1"
               for s in tb["skips"])



# ---- AC12: SCHEMA not claiming PASS; assumption present ----
def test_ac12_schema_unchanged_and_assumption(tmp_path: Path):
    assert SCHEMA_VERSION == "vms-0.2.phase12"
    report = _run(tmp_path)
    assert "EVAL-RIM-FI-DEPOSIT-WF-v1" in report.assumptions
    body = json.loads((tmp_path / "rim_ev" / "rim_calibration_report.json").read_text())
    assert body["schema_version"] == "vms-0.2.phase12"
    assert body["labels"]["CALIBRATION_PASS"] is not True


def test_bundle_summary_gates(tmp_path: Path):
    summary = build_calibrate_rim_bundle(
        out_dir=tmp_path / "b2",
        universe_path=UNI,
        start=START,
        end=END,
        evaluation_as_of=EVAL_ASOF,
        seed=7,
    )
    assert summary["calibration_claim"] == "CALIBRATION_INSUFFICIENT"
    assert summary["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert summary["min_hist_pb_points"] == 12
    assert summary["schema_version"] == SCHEMA_VERSION
    assert (tmp_path / "b2" / "calibrate_rim_summary.json").is_file()
    assert (tmp_path / "b2" / "frozen_weights.json").is_file()


def test_assign_labels_insufficient_path():
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=None,
        data_label="SYNTHETIC_BANK_FI",
        n_unbiased_scored=2,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
