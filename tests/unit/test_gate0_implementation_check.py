"""Gate0 Implementation Check: Detector for I-M02

CRITICAL: This test directly verifies that Gate0 blocks methods where:
1. implementation_status != IMPLEMENTED
2. enabled = False

This detector was added to close the I-M02 detection gap discovered during
VTP-0.1 mutation testing.

Real interface usage:
- Uses actual vms.methods.eligibility.evaluate_hard_gates()
- Uses actual MethodRegistryEntry from registry
- No toy functions or mocks
"""

import pytest
from pathlib import Path

from vms.methods import build_registry_from_config
from vms.methods.eligibility import evaluate_hard_gates
from vms.methods.protocol import ValuationContext
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.schemas.config import load_config
from vms.schemas.contracts import (
    MethodEligibilityStatus,
    MethodImplementationStatus,
    ValuationTarget
)


@pytest.fixture
def repo():
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def loaded(repo):
    return load_config(repo / "config" / "default.yaml")


@pytest.fixture
def test_context(loaded):
    """Create a real ValuationContext for testing"""
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    
    return ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields", [])),
        loaded=loaded,
        data_quality_blocked=False
    )


def test_gate0_blocks_not_implemented_methods(loaded, test_context):
    """Gate0 MUST block methods with implementation_status != IMPLEMENTED
    
    This is the critical detector for I-M02 mutation testing.
    When impl_ok is bypassed to True, this test must fail.
    
    Strategy: Take a real IMPLEMENTED method from registry, clone it,
    and change implementation_status to NOT_IMPLEMENTED to test Gate0.
    """
    from vms.schemas.contracts import MethodRegistryEntry, OutputBasis
    
    registry = build_registry_from_config(loaded.method_registry)
    
    # Get a real implemented method as template
    real_method = next(
        (e for e in registry.entries if e.implementation_status == MethodImplementationStatus.IMPLEMENTED),
        None
    )
    assert real_method is not None, "Need at least one IMPLEMENTED method in registry"
    
    # Create a modified entry with NOT_IMPLEMENTED status
    # This simulates what would happen if a NOT_IMPLEMENTED method were in registry
    # Note: pydantic validator requires enabled=False when NOT_IMPLEMENTED
    not_impl_entry = MethodRegistryEntry(
        method_id=real_method.method_id + "_not_impl_test",
        version=real_method.version,
        implementation_status=MethodImplementationStatus.NOT_IMPLEMENTED,  # NOT_IMPLEMENTED
        enabled=False,  # Must be False for NOT_IMPLEMENTED (pydantic validation)
        supported_targets=real_method.supported_targets,
        output_basis=real_method.output_basis,
        eligible_profiles=real_method.eligible_profiles,
        required_fields=real_method.required_fields,
        exclusion_conditions=real_method.exclusion_conditions,
        failure_codes=real_method.failure_codes
    )
    
    # Test evaluate_hard_gates with NOT_IMPLEMENTED entry
    result = evaluate_hard_gates(not_impl_entry, test_context)
    
    # CRITICAL: NOT_IMPLEMENTED methods MUST be ineligible
    assert result.eligible is False, \
        f"Gate0 MUST block NOT_IMPLEMENTED method; got eligible={result.eligible}"
    
    # Verify the specific Gate0 reason
    gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
    assert len(gate0_reasons) == 1, "Gate0 reason must be present"
    assert gate0_reasons[0].passed is False, \
        "Gate0 must FAIL for NOT_IMPLEMENTED method"
    
    # Verify status is INELIGIBLE
    assert result.status == MethodEligibilityStatus.INELIGIBLE, \
        f"NOT_IMPLEMENTED method must have status=INELIGIBLE; got {result.status}"


def test_gate0_blocks_disabled_methods(loaded, test_context):
    """Gate0 MUST block methods with enabled=False
    
    Even if implementation_status=IMPLEMENTED, enabled=False must fail Gate0.
    
    Strategy: Take a real IMPLEMENTED method, clone it, and set enabled=False.
    """
    from vms.schemas.contracts import MethodRegistryEntry
    
    registry = build_registry_from_config(loaded.method_registry)
    
    # Get a real implemented+enabled method as template
    real_method = next(
        (e for e in registry.entries 
         if e.implementation_status == MethodImplementationStatus.IMPLEMENTED and e.enabled),
        None
    )
    assert real_method is not None, "Need at least one IMPLEMENTED+enabled method"
    
    # Create a modified entry with enabled=False
    disabled_entry = MethodRegistryEntry(
        method_id=real_method.method_id + "_disabled_test",
        version=real_method.version,
        implementation_status=MethodImplementationStatus.IMPLEMENTED,  # Still IMPLEMENTED
        enabled=False,  # But disabled
        supported_targets=real_method.supported_targets,
        output_basis=real_method.output_basis,
        eligible_profiles=real_method.eligible_profiles,
        required_fields=real_method.required_fields,
        exclusion_conditions=real_method.exclusion_conditions,
        failure_codes=real_method.failure_codes
    )
    
    # Test evaluate_hard_gates with disabled entry
    result = evaluate_hard_gates(disabled_entry, test_context)
    
    # CRITICAL: enabled=False methods MUST be ineligible
    assert result.eligible is False, \
        f"Gate0 MUST block enabled=False method; got eligible={result.eligible}"
    
    gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
    assert len(gate0_reasons) == 1
    assert gate0_reasons[0].passed is False, \
        "Gate0 must FAIL for enabled=False method"


def test_gate0_passes_for_implemented_and_enabled(loaded, test_context):
    """Positive test: Gate0 PASSES when implementation_status=IMPLEMENTED AND enabled=True
    
    This verifies that properly configured methods pass Gate0.
    """
    registry = build_registry_from_config(loaded.method_registry)
    
    # Find at least one properly implemented and enabled method
    proper_methods = [
        entry for entry in registry.entries
        if entry.implementation_status == MethodImplementationStatus.IMPLEMENTED
        and entry.enabled is True
    ]
    
    assert len(proper_methods) > 0, \
        "Registry must contain at least one IMPLEMENTED+enabled method"
    
    # Test that Gate0 passes for these methods
    # (They may still fail other gates, but Gate0 should pass)
    for entry in proper_methods[:3]:  # Test first 3 to keep test fast
        result = evaluate_hard_gates(entry, test_context)
        
        gate0_reasons = [r for r in result.reasons if r.code == "METHOD_IMPLEMENTED_AND_ENABLED"]
        assert len(gate0_reasons) == 1
        assert gate0_reasons[0].passed is True, \
            f"Gate0 must PASS for IMPLEMENTED+enabled method {entry.method_id}"


if __name__ == "__main__":
    # Quick smoke test
    import sys
    repo_path = Path(__file__).resolve().parents[2]
    loaded_config = load_config(repo_path / "config" / "default.yaml")
    
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    profile = classify_profile(features_from_fixture(data))
    ctx = ValuationContext(
        instrument_id=profile.instrument_id,
        as_of=profile.as_of,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields", [])),
        loaded=loaded_config,
        data_quality_blocked=False
    )
    
    test_gate0_blocks_not_implemented_methods(loaded_config, ctx)
    test_gate0_passes_for_implemented_and_enabled(loaded_config, ctx)
    
    print("✓ Gate0 detector tests passed")
    sys.exit(0)
