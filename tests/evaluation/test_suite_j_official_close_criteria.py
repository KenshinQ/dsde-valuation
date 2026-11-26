"""Official VTP-0.1 Suite J close criteria (historical walk-forward).

Suite J in /workspace/vtp-0.1-input/VTP-0.1.md is *Historical walk-forward
evaluation* (J-01 frozen protocol, J-02 no random row split, J-03 separate
forecast targets, J-04 baselines, J-05 proper scoring and calibration,
J-06 claim discipline). It is not a "distribution unit-test coverage" suite.

These tests encode the official close bar so that:
- 19 synthetic evaluation-code greens cannot be relabeled as historical PASS;
- a real lean-slice run with n_unbiased_pit_complete == 0, missing official
  targets/baselines, or MAE-only research scores under PIT_ASSUMED cannot be
  written up as J-01..J-05 PASS;
- a predeclared R7 protocol file is recognized as a *slice* protocol, not as
  a full official Suite J close.

No production logic is changed. DuckDB is not required for this module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
UNI_R7 = REPO / "config" / "universe.fi_deposit_lean_real.yaml"
PROTOCOL_DOC = REPO / "docs" / "calibration_protocol.md"

# Official VTP-0.1.md § Suite J — J-03 / J-04 required lists.
OFFICIAL_J03_TARGETS = (
    "operating_forecasts_revenue_ebit_roe_fcf",
    "peer_multiple_behavior",
    "future_market_price_distribution",
    "total_return_and_event_probabilities",
    "ensemble_calibration_declared_target",
)

OFFICIAL_J04_BASELINES = (
    "historical_driver_mean_or_median",
    "deterministic_central_case_dcf_eligible_profiles",
    "simple_multiple",
    "no_regime",
    "current_multiple_persistence_exit",
    "profile_appropriate_benchmark",
)

# R7 lean slice maps onto only a subset of the official lists.
R7_DECLARED_TARGETS = ("driver_roe", "intrinsic_value", "market_price")
R7_PRESENT_BASELINES = ("central_rim", "fi_note", "historical_roe_median")


def official_item_status(report: dict[str, Any]) -> dict[str, str]:
    """Fail-closed official J-01..J-05 labels for a walk-forward report.

    A slice report may be useful evidence and still be not-PASS. PASS requires
    the official checklist, a positive PIT-complete unbiased sample, and
    non-vacuous proper scores. This helper never upgrades CALIBRATION_INSUFFICIENT
    or n_unbiased_pit_complete==0 into PASS.
    """
    labels = report.get("labels") or {}
    scores = report.get("scores") or {}
    n_unbiased = int(report.get("n_unbiased_pit_complete") or 0)
    declared = tuple(scores.get("evaluation_targets_declared") or report.get("evaluation_targets_declared") or ())
    baselines = tuple(report.get("baselines_present") or [])
    split_mode = report.get("split_mode")
    flags = set(report.get("flags") or [])
    all_pit_assumed = (
        n_unbiased == 0
        and int(report.get("n_pit_assumed") or 0) > 0
        and "PIT_ASSUMED_VENDOR_LATEST" in flags
    )

    def _j01() -> str:
        # Protocol completeness is mostly outside the report; the report alone
        # cannot close official J-01. A missing frozen-weight record is enough
        # to keep it from PASS.
        fw = report.get("frozen_weights") or {}
        if not fw or not fw.get("frozen_before_test"):
            return "BLOCKED"
        # Lean-slice execution ≠ full official protocol.
        if declared != OFFICIAL_J03_TARGETS and set(declared) <= set(R7_DECLARED_TARGETS):
            return "PARTIAL"
        return "PARTIAL"

    def _j02() -> str:
        if split_mode != "chronological":
            return "BLOCKED"
        if all_pit_assumed:
            # Chronological and no random split may hold, but "fitted only on
            # permitted past data" is not proven under PIT_ASSUMED / LATEST_ONLY.
            return "PARTIAL"
        return "PARTIAL"

    def _j03() -> str:
        have = set(declared)
        official_hit = set()
        if "driver_roe" in have:
            official_hit.add("operating_forecasts_revenue_ebit_roe_fcf")  # ROE only
        if "market_price" in have:
            official_hit.add("future_market_price_distribution")
        missing = [t for t in OFFICIAL_J03_TARGETS if t not in official_hit]
        # ROE-only is not the full operating-forecast target; treat as missing remainder.
        if "operating_forecasts_revenue_ebit_roe_fcf" in official_hit and not {
            "revenue",
            "ebit",
            "fcf",
            "operating_cash_flow",
        }.intersection({x.lower() for x in have}):
            missing.append("operating_forecasts_revenue_ebit_fcf")
        if missing or "peer_multiple_behavior" not in official_hit:
            return "PARTIAL" if have else "BLOCKED"
        return "PASS"

    def _j04() -> str:
        have = set(baselines)
        if "historical_roe_median" in have or "historical_median" in have:
            pass
        else:
            return "BLOCKED" if not have else "PARTIAL"
        # Official list is broader than the R7 FI slice.
        if "simple_multiple" not in have and "current_multiple_persistence" not in have:
            return "PARTIAL"
        return "PARTIAL"

    def _j05() -> str:
        if n_unbiased <= 0:
            return "BLOCKED"
        if labels.get("CALIBRATION_CLAIM") == "CALIBRATION_INSUFFICIENT":
            return "BLOCKED"
        blob = json.dumps(scores)
        has_mae = "mae" in blob or "rmse" in blob
        has_pinball_or_crps = "pinball" in blob.lower() or "crps" in blob.lower()
        has_brier = "brier" in blob.lower()
        subgroups = scores.get("subgroups") or {}
        if not has_mae and not has_pinball_or_crps:
            return "BLOCKED"
        if not has_brier or not subgroups:
            return "PARTIAL"
        return "PASS"

    status = {
        "J-01": _j01(),
        "J-02": _j02(),
        "J-03": _j03(),
        "J-04": _j04(),
        "J-05": _j05(),
    }
    if any(v == "BLOCKED" for v in status.values()) or any(v == "PARTIAL" for v in status.values()):
        status["suite_j_official"] = "BLOCKED"
    else:
        status["suite_j_official"] = "PASS"
    # Never let a zero-unbiased pack close the suite.
    if n_unbiased <= 0:
        status["suite_j_official"] = "BLOCKED"
        status["J-05"] = "BLOCKED"
    return status


def _r7_like_report(**overrides: Any) -> dict[str, Any]:
    report = {
        "n_unbiased_pit_complete": 0,
        "n_pit_assumed": 15,
        "n_scored": 15,
        "split_mode": "chronological",
        "baselines_present": list(R7_PRESENT_BASELINES),
        "evaluation_targets_declared": list(R7_DECLARED_TARGETS),
        "flags": [
            "CALIBRATION_INSUFFICIENT_PIT_ASSUMED",
            "PIT_ASSUMED_IN_RESEARCH_SCORES",
            "PIT_ASSUMED_VENDOR_LATEST",
        ],
        "frozen_weights": {"frozen_before_test": True, "test_window_start": "2016-01-01"},
        "labels": {
            "CALIBRATION_CLAIM": "CALIBRATION_INSUFFICIENT",
            "CALIBRATION_PASS": None,
            "ENSEMBLE_CALIBRATED": False,
            "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
        },
        "scores": {
            "evaluation_targets_declared": list(R7_DECLARED_TARGETS),
            "driver_roe": {"errors": {"mae": 0.01, "rmse": 0.02, "n": 14}},
            "market_price": {"errors": {"mae": 4.3, "rmse": 7.0, "n": 15}},
            "subgroups": {"by_profile": {"FINANCIAL_INSTITUTION": {"n": 15, "tsr_point_errors": {"n": 0}}}},
        },
    }
    report.update(overrides)
    return report


def test_official_suite_j_is_historical_walk_forward_not_distribution_checks():
    """Backlog/verdicts 'Distribution Checks' is a mislabel of official Suite J."""
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "walk-forward" in lowered
    assert "random row-level" in lowered or "no random" in lowered
    # Official close is historical evaluation, not src/vms/drivers unit coverage.
    status = official_item_status(_r7_like_report())
    assert status["suite_j_official"] == "BLOCKED"
    assert status["J-05"] == "BLOCKED"


def test_synthetic_evaluation_code_regression_is_not_historical_pass():
    """19 synthetic evaluation tests exercise APIs; they are not J-01..J-05 PASS."""
    # An empty / synthetic-only pack must stay blocked.
    synthetic = {
        "n_unbiased_pit_complete": 0,
        "n_pit_assumed": 0,
        "n_scored": 0,
        "data_label": "SYNTHETIC",
        "split_mode": "chronological",
        "labels": {"CALIBRATION_CLAIM": "CALIBRATION_INSUFFICIENT"},
        "scores": {},
    }
    status = official_item_status(synthetic)
    assert status["suite_j_official"] == "BLOCKED"
    assert status["J-05"] == "BLOCKED"
    assert status["J-01"] == "BLOCKED"
    assert status["J-03"] == "BLOCKED"


def test_j05_blocked_when_unbiased_pit_complete_is_zero():
    status = official_item_status(_r7_like_report(n_unbiased_pit_complete=0))
    assert status["J-05"] == "BLOCKED"
    assert status["suite_j_official"] == "BLOCKED"


def test_j05_stays_blocked_under_calibration_insufficient_even_with_positive_n():
    """Plumbing must not turn CALIBRATION_INSUFFICIENT into J-05 PASS."""
    status = official_item_status(
        _r7_like_report(
            n_unbiased_pit_complete=15,
            n_pit_assumed=0,
            flags=[],
            labels={
                "CALIBRATION_CLAIM": "CALIBRATION_INSUFFICIENT",
                "investment_value": "INVESTMENT_VALUE_NOT_ESTABLISHED",
            },
        )
    )
    assert status["J-05"] == "BLOCKED"
    assert status["suite_j_official"] == "BLOCKED"


def test_j03_not_pass_when_official_targets_are_only_partially_declared():
    status = official_item_status(_r7_like_report())
    assert status["J-03"] in {"PARTIAL", "BLOCKED"}
    assert status["J-03"] != "PASS"


def test_j04_not_pass_when_official_baselines_are_only_partially_present():
    status = official_item_status(_r7_like_report())
    assert status["J-04"] == "PARTIAL"
    assert status["J-04"] != "PASS"


def test_j02_partial_when_chronological_but_all_origins_pit_assumed():
    status = official_item_status(_r7_like_report())
    assert status["J-02"] == "PARTIAL"
    blocked = official_item_status(_r7_like_report(split_mode="random_row"))
    assert blocked["J-02"] == "BLOCKED"


def test_r7_universe_yaml_predeclares_core_slice_protocol_fields():
    """J-01 *slice* predeclaration exists; this is not a full official J-01 PASS."""
    uni = yaml.safe_load(UNI_R7.read_text(encoding="utf-8"))
    assert uni["universe_id"] == "fi_deposit_lean_r7_v1"
    assert "SYNTHETIC" not in str(uni["data_label"]).upper()
    assert uni["split_mode"] == "chronological"
    assert uni["forbid_random_splits"] is True
    assert uni["horizons_years"] == [1]
    assert uni["min_history_years"] == 3
    assert {i["instrument_id"] for i in uni["instruments"]} == {
        "000001.SZ",
        "600036.SH",
        "601398.SH",
    }
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")
    assert "EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1" in doc
    assert "CALIBRATION_INSUFFICIENT" in doc
    assert "INVESTMENT_VALUE_NOT_ESTABLISHED" in doc


def test_claim_discipline_forbids_investment_value_or_calibration_pass_on_r7_like_pack():
    labels = _r7_like_report()["labels"]
    assert labels["CALIBRATION_CLAIM"] == "CALIBRATION_INSUFFICIENT"
    assert labels["investment_value"] == "INVESTMENT_VALUE_NOT_ESTABLISHED"
    assert labels["ENSEMBLE_CALIBRATED"] is False
    status = official_item_status(_r7_like_report())
    assert status["suite_j_official"] != "PASS"


def test_optional_evidence_dir_cannot_be_labeled_pass_if_incomplete(tmp_path: Path):
    """If SUITE_J_EVIDENCE_DIR (or a copied report) is provided, still fail-closed."""
    report = _r7_like_report()
    path = tmp_path / "rim_calibration_report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    status = official_item_status(loaded)
    assert status["J-05"] == "BLOCKED"
    assert status["suite_j_official"] == "BLOCKED"


@pytest.mark.skipif(
    not (
        Path("/workspace/data/hithink_fundamentals.duckdb").is_file()
        and Path("/workspace/data/market.duckdb").is_file()
    ),
    reason="local HiThink/market duckdb not mounted (CI may skip)",
)
def test_local_duckdb_presence_is_not_official_suite_j_pass():
    """Data availability unblocks execution of a slice; it does not close Suite J."""
    status = official_item_status(_r7_like_report())
    assert Path("/workspace/data/hithink_fundamentals.duckdb").is_file()
    assert Path("/workspace/data/market.duckdb").is_file()
    assert status["suite_j_official"] == "BLOCKED"
