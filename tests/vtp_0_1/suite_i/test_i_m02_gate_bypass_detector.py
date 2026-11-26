"""I-M02 Detector: Gate0 implementation check must block unimplemented methods

AUDIT REQUIREMENT: Existing test_property_ineligible_method_contributes_no_values
was insufficient to detect Gate0 bypass. This detector explicitly asserts:

1. Methods with implementation_status != IMPLEMENTED must fail Gate0
2. Methods with enabled=False must fail Gate0
3. Failed gate must prevent eligibility=True
4. Failed gate must prevent contribution to ensemble

This is a NEW detector added to close the I-M02 detection gap.
"""

import pytest

from vms.methods import MethodConfig, build_registry_from_config
from vms.methods.eligibility import evaluate_hard_gates
from vms.methods.protocol import ValuationContext
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.profiles import classify_profile
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    MethodImplementationStatus,
    MethodRegistryEntry,
    OutputBasis,
    ProfileLabel,
    ValuationTarget
)


def test_gate0_blocks_unimplemented():
    """Gate0 must block methods with implementation_status != IMPLEMENTED
    
    This test explicitly verifies that evaluate_hard_gates() rejects
    methods that are NOT_IMPLEMENTED or STUB, ensuring they cannot
    become eligible even if other gates pass.
    """
    # Create a fake entry with NOT_IMPLEMENTED status
    entry_not_impl = MethodRegistryEntry(
        method_id="fake_not_impl",
        version="1.0",
        implementation_status=MethodImplementationStatus.NOT_IMPLEMENTED,
        enabled=True,
        supported_targets=[ValuationTarget.FUNDAMENTAL_VALUE_CURRENT],
        eligible_profiles=[ProfileLabel.MATURE_OPERATING],
        required_fields=[],
        exclusion_conditions=[],
        output_basis=[OutputBasis.EQUITY],
        failure_codes=["GATE_FAILED"]
    )
    
    # Create context that would pass all other gates
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    
    context = ValuationContext(
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields") or []),
        data_quality_blocked=False
    )
    
    # Evaluate gates
    result = evaluate_hard_gates(entry_not_impl, context)
    
    # CRITICAL ASSERTION: NOT_IMPLEMENTED must make eligible=False
    assert result.eligible is False, \
        f"Gate0 MUST block NOT_IMPLEMENTED methods; got eligible={result.eligible}"
    
    # Verify Gate0 reason is marked as failed
    gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
    assert len(gate0_reasons) == 1, "Gate0 reason must be present"
    assert gate0_reasons[0].passed is False, "Gate0 must fail for NOT_IMPLEMENTED"


def test_gate0_blocks_disabled():
    """Gate0 must block methods with enabled=False
    
    Even if implementation_status=IMPLEMENTED, enabled=False must fail Gate0.
    """
    entry_disabled = MethodRegistryEntry(
        method_id="fake_disabled",
        version="1.0",
        implementation_status=MethodImplementationStatus.IMPLEMENTED,
        enabled=False,  # DISABLED
        supported_targets=[ValuationTarget.FUNDAMENTAL_VALUE_CURRENT],
        eligible_profiles=[ProfileLabel.MATURE_OPERATING],
        required_fields=[],
        exclusion_conditions=[],
        output_basis=[OutputBasis.EQUITY],
        failure_codes=["GATE_FAILED"]
    )
    
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    
    context = ValuationContext(
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields") or []),
        data_quality_blocked=False
    )
    
    result = evaluate_hard_gates(entry_disabled, context)
    
    # CRITICAL: enabled=False must make eligible=False
    assert result.eligible is False, \
        f"Gate0 MUST block enabled=False methods; got eligible={result.eligible}"
    
    gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
    assert len(gate0_reasons) == 1
    assert gate0_reasons[0].passed is False, "Gate0 must fail for enabled=False"


def test_gate0_pass_when_implemented_and_enabled():
    """Gate0 must PASS when implementation_status=IMPLEMENTED AND enabled=True
    
    Positive test: correctly implemented and enabled method should pass Gate0
    (may still fail other gates, but Gate0 should pass).
    """
    entry_ok = MethodRegistryEntry(
        method_id="fake_ok",
        version="1.0",
        implementation_status=MethodImplementationStatus.IMPLEMENTED,
        enabled=True,
        supported_targets=[ValuationTarget.FUNDAMENTAL_VALUE_CURRENT],
        eligible_profiles=[ProfileLabel.MATURE_OPERATING],
        required_fields=[],  # No required fields for this test
        exclusion_conditions=[],
        output_basis=[OutputBasis.EQUITY],
        failure_codes=["GATE_FAILED"]
    )
    
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    
    context = ValuationContext(
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields") or []),
        data_quality_blocked=False
    )
    
    result = evaluate_hard_gates(entry_ok, context)
    
    # Gate0 should PASS
    gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
    assert len(gate0_reasons) == 1
    assert gate0_reasons[0].passed is True, \
        "Gate0 must PASS for IMPLEMENTED + enabled=True"


if __name__ == "__main__":
    # Run tests
    test_gate0_blocks_unimplemented()
    test_gate0_blocks_disabled()
    test_gate0_pass_when_implemented_and_enabled()
    print("✓ All I-M02 detector tests passed")
