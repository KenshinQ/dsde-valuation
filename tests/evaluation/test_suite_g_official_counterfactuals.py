"""Official VTP-0.1 Suite G close tests — production market-pricing / exit-price APIs.

These tests call production generate_exit_prices / run_convergence_scenario /
run_path_projection (via suite_g_production_counterfactuals). They do not use
SimpleValuationModel, skipped placeholders, or historic 2026-11-07 junit as PASS.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.company import loaded_config
from tests.evaluation.suite_g_production_counterfactuals import (
    CONV_BLEND,
    CONV_RATE,
    SENTINEL_IV,
    run_official_suite_g,
)
from vms.evaluation import run_evaluation
from vms.market_pricing import MARKET_PRICING_STATES
from vms.schemas.config import FUNDAMENTAL_STATES

TZ = ZoneInfo("Asia/Shanghai")
UNI = Path("config/universe.synthetic.yaml")
L = loaded_config()


@pytest.fixture(scope="module")
def suite_g() -> dict:
    return run_official_suite_g()


def test_g01_no_implicit_convergence(suite_g: dict) -> None:
    """G-01: fixed financial/intrinsic distribution; vary market regime; no silent IV copy."""
    rec = suite_g["G-01"]
    assert rec["status"] == "PASS"
    c, e = rec["compressed"], rec["expanded"]
    assert c["n_valid_horizon"] > 0 and e["n_valid_horizon"] > 0
    assert c["mean"] is not None and e["mean"] is not None
    assert c["mean"] != e["mean"]
    assert c["p50"] != e["p50"]
    assert rec["silent_copy_of_sentinel"] == []
    assert rec["any_intrinsic_value_used_on_default"] is False
    assert c["default_forbids_intrinsic_copy"] is True
    assert c["scenario_kind"] == "TERMINAL_MULTIPLE_DEFAULT"
    # Exit means must not collapse to the sentinel intrinsic.
    assert abs(c["mean"] - SENTINEL_IV) > 1.0
    assert abs(e["mean"] - SENTINEL_IV) > 1.0


def test_g02_intrinsic_value_held_fixed(suite_g: dict) -> None:
    """G-02: financial-path content held fixed while the terminal multiple regime changes."""
    rec = suite_g["G-02"]
    assert rec["status"] == "PASS"
    assert rec["financial_path_unchanged"] is True
    assert rec["financial_path_hash_before"] == rec["financial_path_hash_after"]
    assert rec["exit_mean_compressed"] != rec["exit_mean_expanded"]


def test_g03_market_multiple_held_fixed(suite_g: dict) -> None:
    """G-03: market posterior/config/seed fixed; financial paths change; lineage attributes source."""
    rec = suite_g["G-03"]
    assert rec["status"] == "PASS"
    a, b = rec["paths_A"], rec["paths_B"]
    assert a["n_valid_horizon"] > 0 and b["n_valid_horizon"] > 0
    assert a["mean"] != b["mean"]
    sample = rec["attribution_sample"]
    assert sample["denominator_field"]
    assert sample["denominator_value"] is not None
    assert sample["terminal_multiple"] is not None
    assert "denominator_field" in sample["lineage_keys"]
    assert "terminal_multiple" in sample["lineage_keys"]


def test_g04_fundamental_market_regime_independence(suite_g: dict) -> None:
    """G-04: market-only and fundamental-only interventions are independent; coupling is opt-in."""
    rec = suite_g["G-04"]
    assert rec["status"] == "PASS"
    assert rec["default_dependence"] == "NONE"
    assert rec["configured_dependence_opt_in"] == "CONFIGURED"
    assert "CONFIGURED_FUNDAMENTAL_DEPENDENCE" in rec["configured_dependence_flags"]
    assert rec["market_only"]["financial_path_hash_unchanged"] is True
    assert rec["market_only"]["exit_distribution_changed"] is True
    assert rec["fundamental_only"]["path_hashes_differ"] is True
    assert rec["fundamental_only"]["exit_distribution_changed_through_projected_metrics"] is True
    assert set(MARKET_PRICING_STATES).isdisjoint(set(FUNDAMENTAL_STATES))


def test_g05_explicit_convergence_scenario(suite_g: dict) -> None:
    """G-05: convergence is labeled, uncertain, parameterized, and not the default path."""
    rec = suite_g["G-05"]
    assert rec["status"] == "PASS"
    assert rec["default_scenario_kind"] == "TERMINAL_MULTIPLE_DEFAULT"
    assert rec["convergence_scenario_kind"] == "CONVERGENCE_TO_INTRINSIC"
    assert "EXPLICIT_CONVERGENCE_SCENARIO" in rec["convergence_flags"]
    assert rec["config_convergence_enabled_by_default"] is False
    assert 0.0 < rec["stochastic_rate"] < 1.0
    assert 0.0 < rec["blend_weight"] < 1.0
    assert rec["stochastic_rate"] == CONV_RATE
    assert rec["blend_weight"] == CONV_BLEND
    assert rec["n_fired"] > 0
    assert rec["n_not_fired"] > 0
    assert rec["stats"]["n_valid_horizon"] > 0


def test_g06_no_future_price_as_intrinsic_ground_truth(tmp_path: Path, suite_g: dict) -> None:
    """G-06: reports must not label observed future price as intrinsic-value ground truth."""
    # Bundle-level: production exit prices are labeled as future market exits, not IV.
    labels = suite_g["G-06_bundle_labels"]
    assert labels["exit_bundle_label"] == "FUTURE_MARKET_EXIT_PRICES"
    assert labels["exit_is_not_labeled_intrinsic"] is True

    # Evaluation-report-level: production run_evaluation forbids price MAE as IV truth
    # and labels any IV↔price association as not-ground-truth (EVAL-IV-NOT-PRICE-TRUTH-v1).
    report = run_evaluation(
        universe=UNI,
        loaded=L,
        start=date(2018, 1, 1),
        end=date(2022, 12, 31),
        out_dir=tmp_path / "g06_eval",
        evaluation_as_of=datetime(2025, 6, 30, 15, tzinfo=TZ),
    )
    iv = report.scores_unbiased["intrinsic_value"]
    assert iv.get("price_mae_forbidden") is True
    assoc = iv["market_price_association_only"]
    assert assoc["label"] == "MARKET_PRICE_ASSOCIATION_NOT_INTRINSIC_GROUND_TRUTH"
