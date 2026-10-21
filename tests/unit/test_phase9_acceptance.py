"""VMS-0.2 Phase 9 acceptance (SPEC §20 Phase 9 / §14 / §21.2 / §24)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tests.company import company, loaded_config
from tests.factories import INST
from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION
from vms.market_pricing import (
    apply_configured_dependence,
    compare_persistence_vs_mean_reversion,
    constant_state_persistence,
    estimate_market_pricing_state,
    generate_exit_prices,
    run_convergence_scenario,
    unavailable_market_pricing,
)
from vms.market_pricing.config import MarketPricingConfig, default_market_pricing_config
from vms.pipeline import run_path_projection
from vms.market_pricing import MARKET_PRICING_STATES
from vms.schemas.config import FUNDAMENTAL_STATES


L = loaded_config()


@pytest.fixture(scope="module")
def path_bundle():
    load, as_of = company(years=tuple(range(2016, 2025)), growth=0.06)
    run = run_path_projection(
        load,
        instrument_id=INST,
        as_of=as_of,
        loaded=L,
        seed=42,
        n_paths=24,
        n_years=3,
        policy_id="historical_continuation",
    )
    assert run.financial_paths is not None
    return run.financial_paths


# ---- AC1: Fundamental and market pricing states evolve independently ----
def test_ac1_market_estimator_ignores_fundamentals():
    assert set(MARKET_PRICING_STATES).isdisjoint(set(FUNDAMENTAL_STATES))
    post = estimate_market_pricing_state(
        current_multiple=10.0,
        historical_multiples=[8, 9, 10, 11, 9.5, 8.5, 10.5, 9, 8.8, 10.2, 9.1, 9.7],
        config=default_market_pricing_config().model_copy(
            update={"min_history_obs_for_estimation": 8}
        ),
    )
    assert post.kind == "MARKET_PRICING"
    assert post.dependence_on_fundamentals == "NONE"
    assert post.status == "AVAILABLE"
    # No fundamental labels in states
    assert set(post.states).isdisjoint(set(FUNDAMENTAL_STATES))


def test_ac1_configured_dependence_is_opt_in(path_bundle):
    post = estimate_market_pricing_state(
        current_multiple=None, historical_multiples=[], use_fallback_when_unavailable=True
    )
    assert post.dependence_on_fundamentals == "NONE"
    tilted = apply_configured_dependence(
        post,
        fundamental_state="GROWTH",
        tilt={"GROWTH": {"EXPANDED": 2.0, "COMPRESSED": 0.5}},
    )
    assert tilted.dependence_on_fundamentals == "CONFIGURED"
    assert "CONFIGURED_FUNDAMENTAL_DEPENDENCE" in tilted.flags
    # Default exit bundle reports NONE when using untilted posterior
    b = generate_exit_prices(
        path_bundle,
        market_posterior=post,
        horizons_years=[1],
        metric_id="ev_ebitda",
        seed=1,
    )
    assert b.dependence_on_fundamentals == "NONE"


# ---- AC2: Constant-state baseline runs even when MR estimation unsupported ----
def test_ac2_persistence_baseline_when_mr_unsupported(path_bundle):
    cfg = default_market_pricing_config()
    assert cfg.mean_reversion.estimation_status == "UNSUPPORTED"
    assert cfg.mean_reversion.enabled is False
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    report, bundles = compare_persistence_vs_mean_reversion(
        path_bundle,
        market_posterior=post,
        config=cfg,
        horizons_years=[1, 3],
        metric_id="ev_ebitda",
        seed=42,
    )
    assert report.baseline_model_id == "CONSTANT_STATE_PERSISTENCE"
    assert "CONSTANT_STATE_PERSISTENCE" in bundles
    assert bundles["CONSTANT_STATE_PERSISTENCE"].n_valid > 0
    assert report.mean_reversion_estimation_status == "UNSUPPORTED"
    assert "PERSISTENCE_BASELINE_ALWAYS_RUN" in report.flags


# ---- AC3: Current intrinsic value is not silently copied to future market price ----
def test_ac3_no_silent_intrinsic_to_exit_copy(path_bundle):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    # Fabricate an intrinsic map equal to a sentinel that would be detectable if copied
    sentinel = 123456.789
    intrinsic = {}
    # Pre-generate with no intrinsic to get path ids
    probe = generate_exit_prices(
        path_bundle, market_posterior=post, horizons_years=[1], metric_id="ev_ebitda", seed=3
    )
    for p in probe.paths:
        intrinsic[(p.path_id, p.horizon_years)] = sentinel

    default = generate_exit_prices(
        path_bundle,
        market_posterior=post,
        horizons_years=[1],
        metric_id="ev_ebitda",
        seed=3,
        scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
        intrinsic_by_path_horizon=intrinsic,  # must be IGNORED
    )
    assert default.default_forbids_intrinsic_copy is True
    assert default.scenario_kind == "TERMINAL_MULTIPLE_DEFAULT"
    for p in default.paths:
        if not p.valid:
            continue
        assert p.intrinsic_value_used is False
        assert p.exit_price_per_share != pytest.approx(sentinel)
        assert "NO_SILENT_INTRINSIC_COPY" in p.reason_codes or "INTRINSIC_MAP_IGNORED_IN_DEFAULT_SCENARIO" in p.flags


def test_ac3_explicit_convergence_is_labeled(path_bundle):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    base = generate_exit_prices(
        path_bundle, market_posterior=post, horizons_years=[1], metric_id="ev_ebitda", seed=5
    )
    intrinsic = {
        (p.path_id, p.horizon_years): (p.exit_price_per_share or 1.0) * 2.0
        for p in base.paths
        if p.valid
    }
    conv = run_convergence_scenario(
        path_bundle,
        market_posterior=post,
        intrinsic_by_path_horizon=intrinsic,
        horizons_years=[1],
        metric_id="ev_ebitda",
        seed=5,
        stochastic_rate=1.0,  # always fire
        blend_weight=1.0,  # full intrinsic when fired
    )
    assert conv.scenario_kind == "CONVERGENCE_TO_INTRINSIC"
    assert "EXPLICIT_CONVERGENCE_SCENARIO" in conv.flags
    fired = [p for p in conv.paths if p.valid and p.intrinsic_value_used]
    assert fired, "stochastic_rate=1.0 must fire convergence"
    for p in fired:
        assert p.scenario_kind == "CONVERGENCE_TO_INTRINSIC"
        assert "CONVERGENCE_BLEND_APPLIED" in p.reason_codes


# ---- AC4: Exit-price paths preserve metric/multiple/bridge/share-count lineage ----
def test_ac4_lineage_preserved(path_bundle):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    b = generate_exit_prices(
        path_bundle,
        market_posterior=post,
        horizons_years=[1, 3],
        metric_id="ev_ebitda",
        seed=42,
        transition_model=constant_state_persistence(),
    )
    assert b.n_valid > 0
    for p in b.paths:
        if not p.valid:
            continue
        assert p.metric_id == "ev_ebitda"
        assert p.terminal_multiple is not None and p.terminal_multiple > 0
        assert p.denominator_field == "ebitda"
        assert p.denominator_value is not None
        assert p.diluted_shares is not None and p.diluted_shares > 0
        assert p.claim_object == "EV"
        assert p.bridge is not None  # EV metric applies bridge once
        assert p.lineage.get("terminal_multiple") == p.terminal_multiple
        assert p.lineage.get("diluted_shares") == p.diluted_shares
        assert p.lineage.get("metric_id") == "ev_ebitda"
        assert p.exit_price_per_share is not None and math.isfinite(p.exit_price_per_share)


def test_ac4_equity_metric_no_ev_bridge(path_bundle):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    b = generate_exit_prices(
        path_bundle, market_posterior=post, horizons_years=[1], metric_id="pe", seed=11
    )
    for p in b.paths:
        if not p.valid:
            continue
        assert p.claim_object == "EQUITY"
        assert p.bridge is None
        assert p.enterprise_value is None
        assert p.lineage.get("applies_ev_bridge") is False


# ---- AC5: Persistence versus mean-reversion sensitivity is reported ----
def test_ac5_persistence_vs_mr_sensitivity_reported(path_bundle):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    report, bundles = compare_persistence_vs_mean_reversion(
        path_bundle,
        market_posterior=post,
        horizons_years=[1, 3],
        metric_id="ev_ebitda",
        seed=42,
    )
    assert set(report.models_compared) >= {
        "CONSTANT_STATE_PERSISTENCE",
        "CONFIGURED_SLOW_MEAN_REVERSION",
        "CONFIGURED_FAST_MEAN_REVERSION",
    }
    assert "CONFIGURED_SLOW_MEAN_REVERSION" in report.delta_median_vs_baseline
    assert "CONFIGURED_FAST_MEAN_REVERSION" in report.delta_median_vs_baseline
    # All three bundles produced
    assert all(b.n_input_paths == path_bundle.n_valid or b.n_input_paths > 0 for b in bundles.values())


def test_schema_version_phase9_contract():
    assert SCHEMA_VERSION == "vms-0.2.phase9"
    assert IMPLEMENTED_PHASE == "PHASE_9"


def test_unavailable_helper_phase9():
    u = unavailable_market_pricing()
    assert u.estimator_phase == "PHASE_9"
    assert u.status == "UNAVAILABLE"
    assert u.dependence_on_fundamentals == "NONE"
