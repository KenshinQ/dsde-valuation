"""Phase 4 follow-up decisions: coupled bootstrap, invalid-path gate, no coverage autoswitch."""

from __future__ import annotations

import pytest

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.pipeline import run_simulation
from vms.sampling import SamplingGateError, simulate_paths

L = loaded_config()


def test_coupled_bootstrap_indices_equal_within_path():
    load, as_of = cyclical_company()
    r = run_simulation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=21, n_paths=30, n_years=2)
    for p in r.bundle.paths:
        idxs = {i for i in p.parameter_draw_index.values() if i is not None}
        assert len(idxs) == 1
    assert "PARAM-BOOTSTRAP-COUPLED-v1" in r.bundle.assumptions
    assert "DEP-BLOCK-BOOTSTRAP-DEFER-v1" in r.bundle.assumptions
    assert "COVERAGE-MISCAL-NO-AUTOSWITCH-v1" in r.bundle.assumptions


def test_invalid_path_fraction_blocks_production(monkeypatch):
    load, as_of = cyclical_company()
    import vms.sampling.simulate as sim
    from vms.sampling.schemas import InvalidPathSummary

    def boom(path_i, **kw):
        return InvalidPathSummary(path_id=f"mc:{path_i}", reason="BOUND_VIOLATION", year_index=1, detail="forced")

    monkeypatch.setattr(sim, "_one_path", boom)
    with pytest.raises(SamplingGateError, match="invalid path fraction"):
        run_simulation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=20, n_years=2,
                       mode="production")
    r = run_simulation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=1, n_paths=20, n_years=2,
                       mode="exploratory", override_reason="unit-test forced rejects")
    assert r.bundle.diagnostics.n_paths_valid == 0
    assert "INVALID_PATH_FRACTION_OVERRIDDEN" in r.bundle.flags
    assert r.bundle.provenance["invalid_path_fraction_override"] == "unit-test forced rejects"


def test_coverage_miscal_does_not_force_persistence():
    load, as_of = cyclical_company()
    from vms.pipeline import run_estimation
    r = run_estimation(load, instrument_id=INST, as_of=as_of, loaded=L, seed=2)
    # Drivers flagged COVERAGE_MISCALIBRATED may still be non-persistence if pinball prefers another
    mis = [n for n, d in r.distributions.drivers.items() if "COVERAGE_MISCALIBRATED" in d.flags]
    assert mis  # fixture has constant ratios
    # Selection rule unchanged
    for d in r.distributions.drivers.values():
        assert "MODEL-SELECTION-WF-v2" in d.selection["rule"] or "default spec" in d.selection["rule"]
