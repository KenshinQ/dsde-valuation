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


def test_phase0_core_modules_importable_without_method_stubs():
    """Phase 0 must not invent empty methods/router packages to look complete (SPEC §22/§24)."""
    import importlib
    for m in ("vms.schemas.contracts", "vms.reporting.phase0_bundle"):
        importlib.import_module(m)
    for m in ("vms.methods", "vms.router", "vms.profiles", "vms.ensemble", "vms.market_pricing"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(m)


def test_schema_version_is_phase0_contract():
    from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
    assert SCHEMA_VERSION == "vms-0.2.phase0"
    assert IMPLEMENTED_PHASE == "PHASE_0"
    assert __version__ == "0.2.0a0"
