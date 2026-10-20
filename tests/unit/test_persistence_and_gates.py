"""persistence_t candidate + LOW_EVAL_SUPPORT / COVERAGE_MISCALIBRATED (MODEL-SELECTION-WF-v2)."""

from __future__ import annotations

import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.drivers.distributions import SPECS
from vms.pipeline import run_estimation

L = loaded_config()


def test_persistence_t_is_selectable_candidate():
    assert "persistence_t" in SPECS
    load, as_of = cyclical_company()
    r = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=2)
    # At least some constant-ratio drivers should prefer persistence_t over pooled/regime
    selected = {k: v.selected_spec for k, v in r.distributions.drivers.items()}
    assert "persistence_t" in selected.values(), selected
    for name, dd in r.distributions.drivers.items():
        assert "persistence_t" in dd.specs
        assert dd.specs["persistence_t"].family == "student_t"
        pb = dd.selection["walk_forward"]["mean_pinball"]
        assert "persistence_t" in pb and "naive_last" in pb


def test_low_eval_support_when_too_few_origins():
    load, as_of = cyclical_company(first_year=2018, n_years=4)
    r = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=2)
    d = r.distributions.drivers["ebit_margin"]
    assert {"SELECTION_DEFAULT_INSUFFICIENT_ORIGINS", "LOW_EVAL_SUPPORT"} <= set(d.flags)
    assert d.low_confidence


def test_coverage_tolerance_config_present():
    assert L.config.estimation.walk_forward.coverage_tolerance == 0.15
