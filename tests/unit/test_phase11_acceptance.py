"""VMS-0.2 Phase 11 acceptance (SPEC §20 Phase 11 / §17 / §21.3 / §24)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.evaluation import (
    RandomSplitProhibitedError,
    assert_weights_unchanged,
    freeze_weights_before_test,
    require_chronological,
    run_evaluation,
)
from vms.evaluation.labels import assign_labels
from vms.evaluation.metrics import crps_gaussian, pinball_loss, score_targets
from vms.reporting.phase11_bundle import (
    PHASE11_STATUS,
    SENSITIVITY_COVERAGE,
    build_phase11_bundle,
)
from vms.schemas.contracts import ClaimStatus

L = loaded_config()
TZ = ZoneInfo("Asia/Shanghai")
UNI = Path(__file__).resolve().parents[2] / "config" / "universe.synthetic.yaml"


# ---- AC1: Historical forecasts persisted before outcomes are read ----
def test_ac1_forecasts_persisted_before_outcomes(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    assert report.n_forecasts_persisted > 0
    files = list((tmp_path / "ev" / "forecasts").rglob("*.json"))
    assert files
    for f in files:
        body = json.loads(f.read_text())
        assert body.get("persisted_before_outcomes") is True
        assert "forecasts" in body and "baselines" in body
        # frozen weights hash recorded at persist time
        assert body.get("frozen_weights_hash")


# ---- AC2: No random row-level time-series split ----
def test_ac2_no_random_row_split():
    with pytest.raises(RandomSplitProhibitedError):
        require_chronological("random")
    with pytest.raises(RandomSplitProhibitedError):
        require_chronological("kfold")
    require_chronological("chronological")


def test_ac2_run_evaluation_rejects_random(tmp_path: Path):
    with pytest.raises(RandomSplitProhibitedError):
        run_evaluation(
            universe=UNI,
            loaded=L,
            start=date(2018, 1, 1),
            end=date(2022, 12, 31),
            out_dir=tmp_path / "bad",
            split_mode="random",
        )


# ---- AC3: Evaluation targets stated separately ----
def test_ac3_separate_evaluation_targets(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev3",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    s = report.scores_unbiased
    for key in (
        "operating_cash_flow",
        "intrinsic_value",
        "market_price",
        "total_shareholder_return",
    ):
        assert key in s
    assert s["evaluation_targets_declared"] == [
        "operating_cash_flow",
        "intrinsic_value",
        "market_price",
        "total_shareholder_return",
    ]
    assert "baseline_comparisons" in s
    assert "subgroups" in s


# ---- AC4: Future market price is not ground truth for intrinsic ----
def test_ac4_future_price_not_intrinsic_truth(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev4",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    iv = report.scores_unbiased["intrinsic_value"]
    assert iv["price_mae_forbidden"] is True
    assoc = iv["market_price_association_only"]
    assert assoc["label"] == "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH"


# ---- AC5: Calibration vs baselines + subgroup diagnostics ----
def test_ac5_baselines_and_subgroups(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev5",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    assert "central_dcf" in report.baselines_present
    assert "historical_median" in report.baselines_present
    assert "current_multiple_persistence" in report.baselines_present
    assert "no_regime" in report.baselines_present or "exit_multiple" in report.baselines_present
    sg = report.scores_unbiased["subgroups"]
    assert "by_profile" in sg
    assert "by_fundamental_regime" in sg
    # pinball / CRPS helpers exist (may be n=0 when quantiles absent)
    empty = pinball_loss([1.0], [None], 0.1)
    assert empty["n"] == 0
    cr = crps_gaussian([1.0], [0.0], [1.0])
    assert cr["n"] == 1 and cr["mean_crps"] is not None


# ---- AC6: Inadequate data → CALIBRATION_INSUFFICIENT ----
def test_ac6_calibration_insufficient_not_inferred_success(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev6",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    assert report.labels["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert report.labels["ENSEMBLE_CALIBRATED"] is False
    # Synthetic panel typically has few unbiased origins → INSUFFICIENT
    if report.scores_unbiased["n_records"] < 5:
        assert report.labels["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
        assert report.labels["CALIBRATION_PASS"] is not True
        assert report.release_gates[ClaimStatus.CALIBRATION_INSUFFICIENT.value] is True
    lab = assign_labels(
        engineering_ok=True,
        data_quality_ok=True,
        calibration_ok=None,
        data_label="SYNTHETIC",
        n_unbiased_scored=2,
    )
    assert lab["CALIBRATION_CLAIM"] == ClaimStatus.CALIBRATION_INSUFFICIENT.value
    assert lab["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value


def test_ac6_release_gates_present(tmp_path: Path):
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "ev6b",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    gates = report.release_gates
    for key in (
        ClaimStatus.ENGINEERING_PASS.value,
        ClaimStatus.DATA_QUALITY_PASS.value,
        ClaimStatus.CALIBRATION_PASS.value,
        ClaimStatus.CALIBRATION_INSUFFICIENT.value,
        ClaimStatus.ENSEMBLE_CALIBRATED.value,
        ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value,
    ):
        assert key in gates
    assert gates[ClaimStatus.ENSEMBLE_CALIBRATED.value] is False
    assert gates[ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value] is True


def test_weights_frozen_before_test(tmp_path: Path):
    freeze = freeze_weights_before_test(
        weights={"fcff_dcf": 0.6, "pe": 0.4},
        thresholds={"min_oos": 5},
        test_window_start=date(2020, 1, 1),
        out_dir=tmp_path / "freeze",
    )
    assert freeze["frozen_before_test"] is True
    assert (tmp_path / "freeze" / "frozen_weights.json").is_file()
    assert_weights_unchanged(freeze, {"fcff_dcf": 0.6, "pe": 0.4})
    with pytest.raises(ValueError, match="ENSEMBLE_WEIGHTS_MUTATED"):
        assert_weights_unchanged(freeze, {"fcff_dcf": 0.9, "pe": 0.1})


def test_phase11_bundle_writes_both_reports(tmp_path: Path):
    summary = build_phase11_bundle(
        out_dir=tmp_path / "p11",
        universe_path=UNI,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        seed=7,
        sensitivity_paths=15,
        sensitivity_years=3,
    )
    assert summary["status"] == PHASE11_STATUS
    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["implemented_phase"] == IMPLEMENTED_PHASE
    assert summary["investment_value"] == ClaimStatus.INVESTMENT_VALUE_NOT_ESTABLISHED.value
    assert summary["labels"]["ENSEMBLE_CALIBRATED"] is False
    assert (tmp_path / "p11" / "evaluation_report.json").is_file()
    assert (tmp_path / "p11" / "sensitivity_report.json").is_file()
    assert (tmp_path / "p11" / "frozen_weights.json").is_file()
    sens = json.loads((tmp_path / "p11" / "sensitivity_report.json").read_text())
    assert "section_16_2_coverage" in sens
    assert set(SENSITIVITY_COVERAGE["deferred"]) == set(sens["section_16_2_coverage"]["deferred"])
    ev = json.loads((tmp_path / "p11" / "evaluation_report.json").read_text())
    assert "release_gates" in ev
    assert ev["split_mode"] == "chronological"


def test_score_targets_empty_safe():
    out = score_targets([])
    assert out["n_records"] == 0
    assert out["intrinsic_value"]["price_mae_forbidden"] is True
