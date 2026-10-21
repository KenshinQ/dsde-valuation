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
    enabled_ids = {m.method_id for m in reg.enabled_methods}
    assert enabled_ids == {"fcff_dcf", "fcfe_dcf", "ddm", "residual_income", "pe", "pb", "ev_ebit", "ev_ebitda", "ev_sales", "nav", "sotp"}
    for m in reg.methods:
        assert m.version
        assert m.supported_targets, m.method_id
        assert m.output_basis, m.method_id
        assert all(isinstance(b, OutputBasis) for b in m.output_basis)
        assert m.failure_codes, m.method_id
        assert isinstance(m.required_fields, list)
        if m.method_id in enabled_ids:
            assert m.implementation_status is MethodImplementationStatus.IMPLEMENTED
            assert m.enabled is True
        else:
            assert m.implementation_status is MethodImplementationStatus.NOT_IMPLEMENTED
            assert m.enabled is False


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
    """Hard gates still gate computation; empty path shell must not fabricate values."""
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    # Missing required fields → ineligible; no fabricated values
    report = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(),
        attempt_value_paths=True,
    )
    assert report.coverage_status == "INSUFFICIENT_METHOD_COVERAGE"
    assert sum(1 for e in report.eligibility if e.eligible) == 0
    assert report.attempted_runs
    for run in report.attempted_runs:
        assert run.values == {}
        assert run.status is not MethodEligibilityStatus.VALID or not run.values
    # With fields but placeholder paths: eligible may be true, but no statement bundle → no values
    report2 = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=frozenset(data["available_fields"]),
        attempt_value_paths=True,
    )
    assert sum(1 for e in report2.eligibility if e.eligible) >= 1
    for run in report2.attempted_runs:
        if run.method_id in {"fcff_dcf", "fcfe_dcf", "ddm"}:
            # Placeholder FinancialPathBundle must not unlock fabricated values
            assert run.values == {} or "PATH_BUNDLE_REQUIRED" in run.reason_codes
            if run.values:
                raise AssertionError("fabricated values without statement paths")
            assert run.status in {
                MethodEligibilityStatus.INELIGIBLE,
                MethodEligibilityStatus.FAILED,
            }


def test_bank_fixture_excludes_industrial_fcff_on_profile_gate(repo):
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "financial_institution.json")
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
    # Phase 4: fcff is implemented — profile exclusion is the hard fail for banks
    assert "PROFILE_ELIGIBLE" in codes or "PROFILE_EXCLUSION" in codes
    assert any(r.code in {"PROFILE_ELIGIBLE", "PROFILE_EXCLUSION"} and not r.passed for r in elig.reasons)


def test_rim_without_assessable_inputs_does_not_fabricate_value(repo):
    """Phase 6: residual_income is implemented but refuses fabricated values without CS inputs."""
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    plugin = registry.plugin("residual_income")
    assert plugin is not None
    data = load_fixture(fixtures_dir() / "financial_institution.json")
    profile = classify_profile(features_from_fixture(data))
    ctx = ValuationContext(
        instrument_id=profile.instrument_id, as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT, profile=profile,
        available_fields=frozenset(data["available_fields"]),
        loaded=loaded,
        # book present but no NI forecast / CS auxiliaries
        rim_inputs={"book_equity_0": 100.0},
        subject_metrics={"total_equity": 100.0},
    )
    result = plugin.value_paths(ctx, FinancialPathBundle(), MethodConfig(method_id="residual_income"))
    assert result.values == {}
    assert result.status is MethodEligibilityStatus.INELIGIBLE
    assert any(
        c in result.reason_codes
        for c in ("MISSING_NET_INCOME_FORECAST", "CLEAN_SURPLUS_UNASSESSABLE", "MISSING_BOOK_EQUITY")
    )


def test_holding_without_schedules_is_data_gap_not_default_dcf(repo):
    """Phase 6: NAV/SOTP may be hard-gate eligible, but missing schedules ⇒ data-gap (not DCF)."""
    loaded = load_config(repo / "config/default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    data = load_fixture(fixtures_dir() / "holding.json")
    profile = classify_profile(features_from_fixture(data))
    report = route_methods(
        registry=registry, profile=profile, target=ValuationTarget.ASSET_NAV,
        available_fields=frozenset(data["available_fields"]),
    )
    # NAV/SOTP implemented → coverage may be METHODS_ELIGIBLE; must not invent DCF
    assert "defaulting to DCF" not in report.notes.lower() or "not defaulting" in report.notes
    assert all(e.method_id != "fcff_dcf" or not e.eligible for e in report.eligibility)
    from vms.methods.asset_based import run_eligible_phase6_methods
    run = run_eligible_phase6_methods(
        registry=registry, profile=profile, target=ValuationTarget.ASSET_NAV,
        loaded=loaded, available_fields=frozenset(data["available_fields"]),
        nav_inputs={"total_assets": 1.0, "total_liabilities": 0.5},
        sotp_inputs={},
    )
    assert run.ensemble is None
    assert "nav" not in run.eligible_run and "sotp" not in run.eligible_run
    for r in run.results:
        assert r.values == {}
        assert r.diagnostics.get("unsupported") is True or "MISSING_" in ",".join(r.reason_codes)
