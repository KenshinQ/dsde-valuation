from __future__ import annotations

import numpy as np
import pytest

from vms import SCHEMA_VERSION
from vms.reporting.metadata import canonical_json, code_version, hash_models, sha256_of
from vms.schemas import FinancialObservation
from vms.seeding import make_rng, stream_rng


def test_make_rng_deterministic():
    assert np.array_equal(make_rng(7).random(10), make_rng(7).random(10))
    assert not np.array_equal(make_rng(7).random(10), make_rng(8).random(10))
    assert isinstance(make_rng(1), np.random.Generator)


def test_streams_independent_and_stable():
    a = stream_rng(42, "synthetic_data").random(5)
    b = stream_rng(42, "driver_paths").random(5)
    assert not np.array_equal(a, b)
    assert np.array_equal(a, stream_rng(42, "synthetic_data").random(5))


def test_stream_values_pinned():
    # Guards against silent changes to the seeding scheme (would break reproducibility of old runs).
    v = stream_rng(42, "phase0_smoke").standard_normal(2)
    assert v.round(9).tolist() == [-1.856823778, 0.282044263]


@pytest.mark.parametrize("bad,exc", [(-1, ValueError), (True, TypeError), (1.5, TypeError), ("1", TypeError)])
def test_bad_seed(bad, exc):
    with pytest.raises(exc):
        make_rng(bad)
    with pytest.raises(exc):
        stream_rng(bad, "x")


def test_canonical_hash_key_order_independent():
    assert sha256_of({"a": 1, "b": 2}) == sha256_of({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_hash_models_order_independent(fin_kwargs):
    a = FinancialObservation(**fin_kwargs)
    b = FinancialObservation(**{**fin_kwargs, "field_name": "ebit", "value": 1.0})
    assert hash_models([a, b]) == hash_models([b, a])
    assert hash_models([a]) != hash_models([b])


def test_code_version_shape():
    cv = code_version()
    assert set(cv) == {"package_version", "git_sha", "src_dirty"}
    assert SCHEMA_VERSION.startswith("vms-0.1")
