"""SPEC §21.2: fixed future-price/distribution paths ⇒ higher P0 cannot improve pathwise return."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.company import company, loaded_config
from tests.factories import INST
from vms.market_pricing import estimate_market_pricing_state, generate_exit_prices
from vms.pipeline import run_path_projection
from vms.returns.track_b import (
    build_return_distributions_from_exit_prices,
    pathwise_returns_improve_at_lower_price_track_b,
)

L = loaded_config()


def _bundle():
    load, as_of = company(years=tuple(range(2016, 2025)), growth=0.05)
    run = run_path_projection(
        load, instrument_id=INST, as_of=as_of, loaded=L, seed=3, n_paths=20, n_years=3,
        policy_id="historical_continuation",
    )
    post = estimate_market_pricing_state(use_fallback_when_unavailable=True)
    exits = generate_exit_prices(
        run.financial_paths, market_posterior=post, horizons_years=[1, 3], metric_id="ev_ebitda", seed=5,
    )
    return run.financial_paths, exits


_FIN, _EXIT = _bundle()


@given(
    rel=st.lists(st.floats(min_value=0.5, max_value=1.8, allow_nan=False, allow_infinity=False), min_size=2, max_size=5, unique=True)
)
@settings(max_examples=25, deadline=None)
def test_property_higher_entry_cannot_improve_pathwise_track_b(rel):
    rel = sorted(rel)
    bundle = build_return_distributions_from_exit_prices(
        exit_prices=_EXIT,
        spot_price=10.0,
        loaded=L,
        financial=_FIN,
        relative_to_spot=rel,
        horizons_years=[1, 3],
    )
    assert pathwise_returns_improve_at_lower_price_track_b(bundle.path_returns)
