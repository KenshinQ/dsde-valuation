"""VMS-0.2 Phase 2: method plugin contract + hard gates (SPEC §11 / §20)."""

from __future__ import annotations

import pytest

from vms.methods import (
    MethodConfig,
    build_registry_from_config,
    evaluate_hard_gates,
    refuse_unimplemented_run,
)
from vms.methods.protocol import FinancialPathBundle, ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.router import route_methods
from vms.schemas.config import load_config, load_method_registry
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    MethodImplementationStatus,
    MethodRegistryEntry,
    OutputBasis,
    ValuationTarget,
)
from pydantic import ValidationError


def test_every_registered_method_declares_targets_units_fields_failure_codes(repo):
    reg = load_method_registry(repo / "config/method_registry.yaml")
    assert len(reg.methods) >= 8
    assert reg.enabled_methods == []
    for m in reg.methods:
        assert m.version
        assert m.supported_targets, m.method_id
        assert m.output_basis, m.method_id
        assert all(isinstance(b, OutputBasis) for b in m.output_basis)
        assert m.failure_codes, m.method_id
        assert m.implementation_status is MethodImplementationStatus.NOT_IMPLEMENTED
        assert m.enabled is False
        # required_fields may be empty for some methods but must be declared (list present)
        assert isinstance(m.required_fields, list)


def test_enabled_not_implemented_still_rejected():
    with pytest.raises(ValidationError):
        MethodRegistryEntry(
            method_id="fcff_dcf",
            version="1",
            implementation_status=MethodImplementationStatus.NOT_IMPLEMENTED,
            enabled=True,
            supported_targets=[ValuationTarget.FUNDAMENTAL_VALUE_CURRENT],
            output_basis=[OutputBasis.EV],
            failure_codes=["X"],
        )


def test_no_method_runs_before_hard_eligibility_gates(repo):
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    report = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(data["available_fields"]),
        attempt_value_paths=True,
    )
    assert report.coverage_status == "INSUFFICIENT_METHOD_COVERAGE"
    assert sum(1 for e in report.eligibility if e.eligible) == 0
    assert report.attempted_runs
    for run in report.attempted_runs:
        assert run.status is MethodEligibilityStatus.INELIGIBLE
        assert "METHOD_NOT_IMPLEMENTED" in run.reason_codes or run.values == {}
        assert run.values == {}
    # No silent default DCF
    assert not any(r.method_id == "fcff_dcf" and r.status is MethodEligibilityStatus.VALID
                   for r in report.method_status)


def test_bank_fixture_excludes_industrial_fcff_on_profile_gate(repo):
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "bank.json")
    profile = classify_profile(features_from_fixture(data))
    assert profile.primary_profile.value == "FINANCIAL_INSTITUTION"
    entry = registry.get("fcff_dcf")
    assert entry is not None
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data["available_fields"]),
    )
    elig = evaluate_hard_gates(entry, ctx)
    assert elig.eligible is False
    codes = {r.code for r in elig.reasons if not r.passed}
    assert "METHOD_IMPLEMENTED_AND_ENABLED" in codes
    # Profile exclusion also recorded when evaluated
    assert any(r.code in {"PROFILE_ELIGIBLE", "PROFILE_EXCLUSION"} and not r.passed for r in elig.reasons)


def test_refuse_unimplemented_does_not_fabricate_value(repo):
    loaded = load_config(repo / "config/default.yaml")
    entry = loaded.method_registry.methods[0]
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    ctx = ValuationContext(
        instrument_id=profile.instrument_id, as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT, profile=profile,
        available_fields=frozenset(data["available_fields"]),
    )
    result = refuse_unimplemented_run(entry, ctx, financial_paths=FinancialPathBundle(),
                                      config=MethodConfig(method_id=entry.method_id))
    assert result.values == {}
    assert result.status is MethodEligibilityStatus.INELIGIBLE


def test_holding_coverage_gap_not_default_dcf(repo):
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "holding.json")
    profile = classify_profile(features_from_fixture(data))
    report = route_methods(
        registry=registry, profile=profile, target=ValuationTarget.ASSET_NAV,
        available_fields=frozenset(data["available_fields"]),
    )
    assert report.coverage_status == "INSUFFICIENT_METHOD_COVERAGE"
    assert "not defaulting to DCF" in report.notes
