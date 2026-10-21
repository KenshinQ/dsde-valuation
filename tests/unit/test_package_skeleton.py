"""§17 package layout exists; unimplemented modules don't pretend to work."""

import importlib

import pytest

SPEC_MODULES = [
    "schemas", "data", "pit", "quality", "drivers", "regimes", "sampling", "statements",
    "capital_allocation", "valuation", "equity_bridge", "ensemble", "returns", "diagnostics",
    "evaluation", "reporting", "cli", "adapters", "providers",
]
UNIMPLEMENTED = []


@pytest.mark.parametrize("m", SPEC_MODULES)
def test_module_importable(m):
    importlib.import_module(f"vms.{m}")


def test_phase8_core_modules_importable_without_future_stubs():
    """Phase 8 ships ensemble; exit-price estimator deferred to Phase 9."""
    import importlib
    for m in ("vms.schemas.contracts", "vms.reporting.phase0_bundle", "vms.reporting.phase3_bundle",
              "vms.profiles", "vms.methods", "vms.router", "vms.market_pricing", "vms.ensemble",
              "vms.drivers", "vms.regimes", "vms.sampling", "vms.statements",
              "vms.capital_allocation", "vms.methods.cash_flow", "vms.methods.multiples",
              "vms.methods.rim", "vms.methods.nav", "vms.methods.sotp", "vms.methods.asset_based",
              "vms.reporting.phase4_bundle", "vms.reporting.phase5_bundle",
              "vms.reporting.phase6_bundle", "vms.reporting.phase7_bundle",
              "vms.reporting.phase8_bundle",
              "vms.router.suitability", "vms.router.compatibility", "vms.router.compare"):
        importlib.import_module(m)


def test_schema_version_is_phase8_contract():
    from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
    assert SCHEMA_VERSION == "vms-0.2.phase8"
    assert IMPLEMENTED_PHASE == "PHASE_8"
    assert __version__ == "0.2.0a0"
