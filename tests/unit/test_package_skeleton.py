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


def test_phase2_core_modules_importable_without_future_stubs():
    """Phase 2 ships profiles/methods/router; later phases must not be empty stubs (SPEC §22/§24)."""
    import importlib
    for m in ("vms.schemas.contracts", "vms.reporting.phase0_bundle",
              "vms.profiles", "vms.methods", "vms.router"):
        importlib.import_module(m)
    for m in ("vms.ensemble", "vms.market_pricing"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(m)


def test_schema_version_is_phase2_contract():
    from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
    assert SCHEMA_VERSION == "vms-0.2.phase2"
    assert IMPLEMENTED_PHASE == "PHASE_2"
    assert __version__ == "0.2.0a0"
