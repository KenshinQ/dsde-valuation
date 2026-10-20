"""§17 package layout exists; unimplemented modules don't pretend to work."""

import importlib

import pytest

SPEC_MODULES = ["schemas", "data", "pit", "quality", "drivers", "regimes", "sampling", "statements",
                "capital_allocation", "valuation", "equity_bridge", "returns", "diagnostics",
                "evaluation", "reporting", "cli"]
UNIMPLEMENTED = ["pit", "quality", "drivers", "regimes", "sampling", "statements", "capital_allocation",
                 "valuation", "equity_bridge", "returns", "diagnostics", "evaluation"]


@pytest.mark.parametrize("m", SPEC_MODULES)
def test_module_importable(m):
    importlib.import_module(f"vms.{m}")


@pytest.mark.parametrize("m", UNIMPLEMENTED)
def test_unimplemented_modules_are_labeled_and_empty(m):
    mod = importlib.import_module(f"vms.{m}")
    assert "NOT IMPLEMENTED" in (mod.__doc__ or "")
    public = [n for n in vars(mod) if not n.startswith("_")]
    assert public == [], f"vms.{m} exposes {public} but is not implemented"
