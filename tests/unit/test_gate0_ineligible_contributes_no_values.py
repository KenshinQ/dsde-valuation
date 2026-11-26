"""Gate0-only ineligibility must not contribute portfolio values.

The older detector ``test_property_ineligible_method_contributes_no_values``
uses holding.json, where fcff_dcf / fcfe_dcf / ddm already fail profile or
required-fields gates. A production mutation that forces ``impl_ok = True`` in
``evaluate_hard_gates()`` can therefore still look ineligible there.

These tests use mature_operating + FUNDAMENTAL_VALUE_CURRENT, where gates 1–4
pass for fcff_dcf. When the method is not IMPLEMENTED, or ``enabled=False``,
only Gate0 fails. Assertions call production interfaces only and do not change
production logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.ensemble.mixture import filter_eligible_components, method_distribution_from_result
from vms.methods import build_registry_from_config
from vms.methods.cash_flow import run_eligible_cashflow_methods
from vms.methods.cash_flow.fcff_plugin import FcffDcfMethod
from vms.methods.eligibility import evaluate_hard_gates
from vms.methods.protocol import MethodConfig, ValuationContext
from vms.pipeline import run_path_projection
from vms.pit.asof import parse_as_of
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    MethodImplementationStatus,
    MethodRegistryEntry,
    OutputBasis,
    ValuationTarget,
)

FCFF_ID = "fcff_dcf"
_OTHER_HARD_GATES = (
    "TARGET_SUPPORTED",
    "PROFILE_ELIGIBLE",
    "REQUIRED_FIELDS_PRESENT",
    "DATA_QUALITY_NOT_BLOCKED",
)


@pytest.fixture
def loaded(repo: Path):
    return load_config(repo / "config" / "default.yaml")


@pytest.fixture
def fixture_data():
    return load_fixture(fixtures_dir() / "mature_operating.json")


@pytest.fixture
def profile(fixture_data):
    feats = features_from_fixture(fixture_data).model_copy(
        update={"instrument_id": synthetic.SYNTHETIC_INSTRUMENT, "as_of": "2025-06-30"}
    )
    return classify_profile(feats)


@pytest.fixture
def context(profile, fixture_data, loaded):
    return ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(fixture_data["available_fields"]),
        loaded=loaded,
        data_quality_blocked=False,
    )


@pytest.fixture
def fcff_entry(loaded) -> MethodRegistryEntry:
    entry = next(e for e in loaded.method_registry.methods if e.method_id == FCFF_ID)
    assert entry.implementation_status is MethodImplementationStatus.IMPLEMENTED
    assert entry.enabled is True
    return entry


@pytest.fixture
def financial_paths(tmp_path: Path, loaded):
    fin, mkt, actions = synthetic.generate(7)
    write_directory(
        tmp_path / "data",
        fin,
        mkt,
        actions,
        synthetic.source_descriptors(),
        classifications=synthetic.classifications(),
    )
    load = load_directory(tmp_path / "data")
    as_of, _ = parse_as_of("2025-06-30")
    run = run_path_projection(
        load,
        instrument_id=synthetic.SYNTHETIC_INSTRUMENT,
        as_of=as_of,
        loaded=loaded,
        seed=7,
        n_paths=15,
        n_years=3,
    )
    assert run.financial_paths is not None
    return run.financial_paths


def _only_gate0_failed(result) -> None:
    by_code = {r.code: r for r in result.reasons}
    assert "METHOD_IMPLEMENTED_AND_ENABLED" in by_code
    assert by_code["METHOD_IMPLEMENTED_AND_ENABLED"].passed is False
    for code in _OTHER_HARD_GATES:
        assert code in by_code, f"missing hard-gate reason {code}"
        assert by_code[code].passed is True, f"{code} must pass so this is a Gate0-only failure"
    assert result.eligible is False
    assert result.status is MethodEligibilityStatus.INELIGIBLE


def _equity_samples(result) -> tuple[float, ...]:
    raw = (result.values or {}).get("equity_value")
    if raw is None:
        return ()
    if isinstance(raw, dict):
        for key in ("mean", "median", "p50"):
            if raw.get(key) is not None:
                return (float(raw[key]),)
        return ()
    return (float(raw),)


def _components_from_bundle(bundle):
    comps = []
    for result in bundle.results:
        samples = _equity_samples(result)
        eligible = (
            result.status in {MethodEligibilityStatus.VALID, MethodEligibilityStatus.LOW_CONFIDENCE}
            and bool(result.values)
            and bool(samples)
        )
        comps.append(
            method_distribution_from_result(
                result,
                samples=samples,
                target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
                output_basis=OutputBasis.EQUITY,
                eligible=eligible,
            )
        )
    return comps


def test_baseline_fcff_passes_all_hard_gates(fcff_entry, context):
    """Control: the fixture is not vacuous — gates 1–4 and Gate0 all pass when enabled."""
    result = evaluate_hard_gates(fcff_entry, context)
    assert result.eligible is True
    assert result.status is MethodEligibilityStatus.VALID
    by_code = {r.code: r for r in result.reasons}
    assert by_code["METHOD_IMPLEMENTED_AND_ENABLED"].passed is True
    for code in _OTHER_HARD_GATES:
        assert by_code[code].passed is True


def test_evaluate_hard_gates_ineligible_when_only_gate0_not_implemented(fcff_entry, context):
    entry = fcff_entry.model_copy(
        update={
            "implementation_status": MethodImplementationStatus.NOT_IMPLEMENTED,
            "enabled": False,
        }
    )
    result = evaluate_hard_gates(entry, context)
    _only_gate0_failed(result)


def test_evaluate_hard_gates_ineligible_when_only_gate0_disabled(fcff_entry, context):
    entry = fcff_entry.model_copy(update={"enabled": False})
    assert entry.implementation_status is MethodImplementationStatus.IMPLEMENTED
    result = evaluate_hard_gates(entry, context)
    _only_gate0_failed(result)


def test_disabled_fcff_plugin_value_paths_contributes_no_values(
    fcff_entry, context, financial_paths,
):
    """Direct production plugin: enabled method has values; enabled=False contributes none.

    Instantiates ``FcffDcfMethod`` with the disabled entry so the check is the
    plugin's call to ``evaluate_hard_gates()``, not registry stub substitution.
    A mutation that forces ``impl_ok = True`` would make this test fail once
    other gates pass and the DCF emits values.
    """
    cfg = MethodConfig(method_id=FCFF_ID)
    baseline = FcffDcfMethod(fcff_entry).value_paths(context, financial_paths, cfg)
    assert baseline.status is MethodEligibilityStatus.VALID
    assert baseline.values
    assert (baseline.values.get("n_valid") or 0) > 0

    disabled_entry = fcff_entry.model_copy(update={"enabled": False})
    refused = FcffDcfMethod(disabled_entry).value_paths(context, financial_paths, cfg)
    assert refused.status is MethodEligibilityStatus.INELIGIBLE
    assert refused.values == {}
    assert "METHOD_IMPLEMENTED_AND_ENABLED" in (refused.reason_codes or [])


def test_disabled_fcff_not_in_eligible_run_or_ensemble(
    loaded, fcff_entry, profile, fixture_data, financial_paths,
):
    """Production registry + run_eligible_cashflow_methods + filter_eligible_components.

    Baseline (enabled) must include fcff_dcf in eligible_run. After only Gate0
    is failed via enabled=False, fcff_dcf must not appear in eligible_run, must
    contribute empty values, and must not survive filter_eligible_components.
    Other methods that still pass their gates may continue to contribute.
    """
    target = ValuationTarget.FUNDAMENTAL_VALUE_CURRENT
    fields = frozenset(fixture_data["available_fields"])

    baseline_registry = build_registry_from_config(loaded.method_registry)
    baseline = run_eligible_cashflow_methods(
        registry=baseline_registry,
        profile=profile,
        target=target,
        financial_paths=financial_paths,
        loaded=loaded,
        available_fields=fields,
    )
    assert FCFF_ID in baseline.eligible_run
    baseline_fcff = next(r for r in baseline.results if r.method_id == FCFF_ID)
    assert baseline_fcff.status is MethodEligibilityStatus.VALID
    assert baseline_fcff.values

    disabled_methods = [
        (e.model_copy(update={"enabled": False}) if e.method_id == FCFF_ID else e)
        for e in loaded.method_registry.methods
    ]
    disabled_registry = build_registry_from_config(
        loaded.method_registry.model_copy(update={"methods": disabled_methods})
    )
    disabled = run_eligible_cashflow_methods(
        registry=disabled_registry,
        profile=profile,
        target=target,
        financial_paths=financial_paths,
        loaded=loaded,
        available_fields=fields,
    )
    disabled_fcff = next(r for r in disabled.results if r.method_id == FCFF_ID)
    assert FCFF_ID not in disabled.eligible_run
    assert disabled_fcff.status is MethodEligibilityStatus.INELIGIBLE
    assert disabled_fcff.values == {}
    assert "METHOD_IMPLEMENTED_AND_ENABLED" in (disabled_fcff.reason_codes or [])
    # Pipeline still runs other eligible cash-flow methods.
    assert disabled.eligible_run
    assert FCFF_ID not in disabled.eligible_run

    kept = filter_eligible_components(_components_from_bundle(disabled))
    assert FCFF_ID not in {c.method_id for c in kept}
    assert kept, "other eligible methods should still enter the mixture filter"
