"""Property tests for Phase 9 exit prices (SPEC §21.2)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.company import company, loaded_config
from tests.factories import INST
from vms.market_pricing import estimate_market_pricing_state, generate_exit_prices
from vms.pipeline import run_path_projection

L = loaded_config()


@pytest.fixture(scope="module")
def small_paths():
    load, as_of = company(years=tuple(range(2016, 2025)), growth=0.05)
    run = run_path_projection(
        load, instrument_id=INST, as_of=as_of, loaded=L, seed=7, n_paths=12, n_years=3,
        policy_id="historical_continuation",
    )
    assert run.financial_paths is not None
    return run.financial_paths


def test_property_fundamental_value_cannot_silently_become_exit(small_paths):
    """SPEC §21.2: A current fundamental value cannot become the exit price without an explicit rule."""
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    fake_iv = 99999.0
    intrinsic = {(p.path_id, 1): fake_iv for p in small_paths.paths}
    bundle = generate_exit_prices(
        small_paths,
        market_posterior=post,
        horizons_years=[1],
        metric_id="ev_ebitda",
        seed=99,
        scenario_kind="TERMINAL_MULTIPLE_DEFAULT",
        intrinsic_by_path_horizon=intrinsic,
    )
    for p in bundle.paths:
        if not p.valid:
            continue
        assert p.intrinsic_value_used is False
        assert p.exit_price_per_share != pytest.approx(fake_iv)
        assert p.scenario_kind == "TERMINAL_MULTIPLE_DEFAULT"


@given(seed=st.integers(min_value=0, max_value=10_000))
@settings(max_examples=15, deadline=None)
def test_property_seed_reproducible_exit_summaries(seed, small_paths):
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    a = generate_exit_prices(
        small_paths, market_posterior=post, horizons_years=[1], metric_id="ev_ebitda", seed=seed
    )
    b = generate_exit_prices(
        small_paths, market_posterior=post, horizons_years=[1], metric_id="ev_ebitda", seed=seed
    )
    assert a.summaries == b.summaries
    assert [p.exit_price_per_share for p in a.paths] == [p.exit_price_per_share for p in b.paths]


def test_property_more_shares_cannot_increase_vps_holding_equity(small_paths):
    """Holding equity value fixed, more diluted shares cannot increase VPS (bridge discipline)."""
    from vms.equity_bridge.bridge import bridge_ev_to_equity

    eq = 1000.0
    v1 = bridge_ev_to_equity(
        enterprise_value=eq, cash=0, debt=0, lease_debt_like=0,
        minority_interest_book=0, other_senior_claims=0, diluted_shares=100,
    )
    v2 = bridge_ev_to_equity(
        enterprise_value=eq, cash=0, debt=0, lease_debt_like=0,
        minority_interest_book=0, other_senior_claims=0, diluted_shares=200,
    )
    assert v1.valid and v2.valid
    assert v2.value_per_share < v1.value_per_share
