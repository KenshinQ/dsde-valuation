"""I-M02 Simplified Detector: Gate0 implementation check

Simplified version that works with existing test infrastructure.
"""

import pytest
from pathlib import Path

from vms.methods import build_registry_from_config
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget


def test_i_m02_gate0_blocks_not_implemented_in_real_registry():
    """Test that NOT_IMPLEMENTED methods in registry are not eligible
    
    This detector verifies that methods marked NOT_IMPLEMENTED
    in the actual registry do not become eligible.
    """
    repo = Path(__file__).resolve().parents[4]
    loaded = load_config(repo / "config" / "default.yaml")
    registry = build_registry_from_config(loaded.method_registry)
    
    # Load a real profile
    data = load_fixture(fixtures_dir() / "mature_operating.json")
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    
    from vms.methods.protocol import ValuationContext
    from datetime import datetime, timezone
    
    context = ValuationContext(
        instrument_id="TEST001",
        as_of=datetime.now(timezone.utc),
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        profile=profile,
        available_fields=frozenset(data.get("available_fields") or []),
        data_quality_blocked=False
    )
    
    # Get eligibility for all methods
    eligibility = registry.eligibility(context)
    
    # CRITICAL: Any method with NOT_IMPLEMENTED status must not be eligible
    for e in eligibility:
        entry = next((m for m in registry.entries if m.method_id == e.method_id), None)
        if entry and entry.implementation_status.value == "NOT_IMPLEMENTED":
            assert e.eligible is False, \
                f"Method {e.method_id} is NOT_IMPLEMENTED but eligible={e.eligible}"


if __name__ == "__main__":
    test_i_m02_gate0_blocks_not_implemented_in_real_registry()
    print("✓ I-M02 detector passed")
