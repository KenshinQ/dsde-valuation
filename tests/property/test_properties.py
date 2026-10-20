"""Property-based tests (SPEC §19) applicable at Phase 0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from vms.data import synthetic
from vms.reporting.metadata import hash_models
from vms.schemas import ValuationRequest
from vms.seeding import stream_rng

seeds = st.integers(min_value=0, max_value=2**63 - 1)


@given(seed=seeds, name=st.text(min_size=1, max_size=20))
def test_fixed_seed_reproduces_stream(seed, name):
    assert np.array_equal(stream_rng(seed, name).random(4), stream_rng(seed, name).random(4))


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(min_value=0, max_value=10_000))
def test_fixed_seed_reproduces_synthetic_data(seed):
    a = synthetic.generate(seed, n_quarters=4)
    b = synthetic.generate(seed, n_quarters=4)
    assert hash_models([*a[0], *a[1]]) == hash_models([*b[0], *b[1]])


@given(h=st.lists(st.integers(min_value=-50, max_value=50), min_size=1, max_size=6),
       paths=st.integers(min_value=-5, max_value=10**6))
def test_request_accepts_iff_valid(h, paths):
    valid = all(x > 0 for x in h) and len(set(h)) == len(h) and paths > 0
    kw = dict(instrument_id="X", as_of=datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=8))),
              spot_price=1.0, horizons_years=h, monte_carlo_paths=paths, random_seed=0,
              configuration_version="v")
    try:
        r = ValuationRequest(**kw)
        assert valid and r.horizons_years == sorted(h)
    except ValidationError:
        assert not valid
