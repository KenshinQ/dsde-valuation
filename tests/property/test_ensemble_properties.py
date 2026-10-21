"""Property tests for ensemble weights (SPEC §21.2)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vms.ensemble import (
    MethodDistribution,
    WeightValidationError,
    equal_prior_weights,
    mix_distributions,
    samples_from_point,
    validate_weight_map,
)
from vms.schemas.contracts import MethodEligibilityStatus, OutputBasis, ValuationTarget

TARGET = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT


@given(
    raw=st.lists(
        st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        min_size=2,
        max_size=6,
    )
)
@settings(max_examples=40, deadline=None)
def test_normalized_weights_nonneg_sum_to_one(raw):
    total = sum(raw)
    if total <= 0:
        # all zeros — invalid
        with pytest.raises(WeightValidationError):
            validate_weight_map({f"m{i}": w for i, w in enumerate(raw)})
        return
    weights = {f"m{i}": w / total for i, w in enumerate(raw)}
    cleaned = validate_weight_map(weights)
    assert all(w >= 0 and math.isfinite(w) for w in cleaned.values())
    assert abs(sum(cleaned.values()) - 1.0) < 1e-9


@given(n=st.integers(min_value=1, max_value=8))
@settings(max_examples=20, deadline=None)
def test_equal_prior_sums_to_one(n):
    ids = [f"m{i}" for i in range(n)]
    art = equal_prior_weights(ids, target=TARGET)
    assert abs(sum(art.weights.values()) - 1.0) < 1e-9
    assert art.protocol.is_prior_only


def test_ineligible_never_in_mixture_property():
    eligible = [
        MethodDistribution(
            method_id="ok_a",
            samples=samples_from_point(100.0, n=20, seed=1),
            status=MethodEligibilityStatus.VALID,
            target=TARGET,
            output_basis=OutputBasis.EQUITY,
        ),
        MethodDistribution(
            method_id="ok_b",
            samples=samples_from_point(110.0, n=20, seed=2),
            status=MethodEligibilityStatus.VALID,
            target=TARGET,
            output_basis=OutputBasis.EQUITY,
        ),
    ]
    ineligible = MethodDistribution(
        method_id="bad",
        samples=samples_from_point(999.0, n=20, seed=3),
        status=MethodEligibilityStatus.FAILED,
        target=TARGET,
        output_basis=OutputBasis.EQUITY,
        eligible=False,
    )
    art = equal_prior_weights(["ok_a", "ok_b"], target=TARGET)
    mix = mix_distributions(eligible + [ineligible], art, n_draws=100, seed=0)
    assert "bad" not in mix.component_method_ids
    assert set(mix.weights) == {"ok_a", "ok_b"}

    art_bad = equal_prior_weights(["ok_a", "ok_b", "bad"], target=TARGET)
    with pytest.raises(WeightValidationError):
        mix_distributions(eligible + [ineligible], art_bad, n_draws=50, seed=0)
