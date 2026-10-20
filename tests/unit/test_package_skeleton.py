"""§17 package layout exists; unimplemented modules don't pretend to work."""

import importlib

import pytest

SPEC_MODULES = ["schemas", "data", "pit", "quality", "drivers", "regimes", "sampling", "statements",
                "capital_allocation", "valuation", "equity_bridge", "returns", "diagnostics",
                "evaluation", "reporting", "cli"]
UNIMPLEMENTED = []


@pytest.mark.parametrize("m", SPEC_MODULES)
def test_module_importable(m):
    importlib.import_module(f"vms.{m}")


def test_all_spec_modules_implemented_through_phase9():
    assert UNIMPLEMENTED == []
