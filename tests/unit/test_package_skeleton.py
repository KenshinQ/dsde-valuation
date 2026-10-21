"""§17 package layout exists; unimplemented modules don't pretend to work."""

import importlib

import pytest

SPEC_MODULES = [
    "schemas", "data", "pit", "quality", "drivers", "regimes", "sampling", "statements",
    "capital_allocation", "valuation", "equity_bridge", "returns", "diagnostics",
    "evaluation", "reporting", "cli", "adapters", "providers",
]
UNIMPLEMENTED = []


@pytest.mark.parametrize("m", SPEC_MODULES)
def test_module_importable(m):
    importlib.import_module(f"vms.{m}")


def test_phase5_core_modules_importable_without_future_stubs():
    """Phase 5 ships multiples + cash-flow; ensemble/estimator deferred."""
    import importlib
    for m in ("vms.schemas.contracts", "vms.reporting.phase0_bundle", "vms.reporting.phase3_bundle",
              "vms.profiles", "vms.methods", "vms.router", "vms.market_pricing",
              "vms.drivers", "vms.regimes", "vms.sampling", "vms.statements",
              "vms.capital_allocation", "vms.methods.cash_flow", "vms.methods.multiples",
              "vms.reporting.phase4_bundle", "vms.reporting.phase5_bundle"):
        importlib.import_module(m)
    # Ensemble and exit-price *estimator* remain Phase 8/9 — package may exist for schemas only
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("vms.ensemble")


def test_schema_version_is_phase5_contract():
    from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
    assert SCHEMA_VERSION == "vms-0.2.phase5"
    assert IMPLEMENTED_PHASE == "PHASE_5"
    assert __version__ == "0.2.0a0"
