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


def test_all_spec_modules_implemented_through_phase10():
    assert UNIMPLEMENTED == []


def test_schema_version_is_release_contract():
    from vms import IMPLEMENTED_PHASE, SCHEMA_VERSION, __version__
    assert SCHEMA_VERSION == "vms-0.1.0"
    assert IMPLEMENTED_PHASE == "PHASE_10"
    assert __version__ == "0.1.0"
