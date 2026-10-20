"""SPEC §19 property: holding future-value paths fixed, raising entry price cannot improve pathwise return (when X>0)."""

from __future__ import annotations

from tests.company import cyclical_company, loaded_config
from tests.factories import INST
from vms.pipeline import run_returns
from vms.returns import pathwise_returns_improve_at_lower_price

L = loaded_config()


def test_lower_entry_improves_pathwise_return_property():
    load, as_of = cyclical_company()
    run = run_returns(load, instrument_id=INST, as_of=as_of, loaded=L, seed=11, n_paths=35, n_years=3,
                      horizons_years=[1, 3])
    assert pathwise_returns_improve_at_lower_price(run.returns.path_returns)
