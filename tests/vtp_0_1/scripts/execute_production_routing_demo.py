#!/usr/bin/env python3
"""Execute ONE production routing path (non-simulated)

AUDIT REQUIREMENT: 调用真实生产API而非SimplifiedRoutingEngine

当前实现：
- 使用真实 vms.router.route_methods
- 使用真实 ProfileLabel, ValuationTarget, MethodRegistry
- 从现有test fixtures加载profile
- 记录真实routing decision

覆盖范围：
- 1个profile (financial institution)
- 1个target (FUNDAMENTAL_VALUE_CURRENT)
- 其余10×12×4缺口标记为UNVERIFIED
"""

import json
from pathlib import Path
from datetime import datetime

from vms.methods import build_registry_from_config
from vms.profiles import classify_profile
from vms.profiles.fixtures import features_from_fixture, fixtures_dir, load_fixture
from vms.router import route_methods
from vms.schemas.config import load_config
from vms.schemas.contracts import ValuationTarget


PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
ARTIFACTS = PROJECT_ROOT / "artifacts" / "vtp-0.1-evidence"
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def execute_one_production_route():
    """执行1条真实生产routing"""
    
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Load config和registry（真实生产）
    config_path = PROJECT_ROOT / "config" / "default.yaml"
    loaded = load_config(config_path)
    registry = build_registry_from_config(loaded.method_registry)
    
    # Load profile fixture（真实）
    fixture_path = fixtures_dir() / "financial_institution.json"
    data = load_fixture(fixture_path)
    feats = features_from_fixture(data)
    profile = classify_profile(feats)
    available_fields = frozenset(data.get("available_fields") or [])
    
    # 执行routing（真实生产API）
    route = route_methods(
        registry=registry,
        profile=profile,
        target=ValuationTarget.FUNDAMENTAL_VALUE_CURRENT,
        available_fields=available_fields,
    )
    
    # 记录结果
    result = {
        "execution_timestamp": timestamp,
        "execution_method": "PRODUCTION_API",
        "api_used": "vms.router.route_methods",
        "profile": {
            "primary_profile": str(profile.primary_profile),
            "fixture_source": "financial_institution.json"
        },
        "target": str(ValuationTarget.FUNDAMENTAL_VALUE_CURRENT),
        "available_fields_count": len(available_fields),
        "routing_result": {
            "eligible_methods_count": len([e for e in route.eligibility if e.eligible]),
            "ineligible_methods_count": len([e for e in route.eligibility if not e.eligible]),
            "eligibility_details": [
                {
                    "method_id": e.method_id,
                    "eligible": e.eligible,
                    "reasons": [str(r) for r in e.reasons] if e.reasons else []
                }
                for e in route.eligibility
            ]
        },
        "coverage_note": "1个profile×1个target执行；其余10×12×4缺口UNVERIFIED",
        "status": "PARTIAL_EXECUTED",
        "no_simplified_engine": "此次使用真实vms.router.route_methods，非SimplifiedRoutingEngine"
    }
    
    # 写结果
    output_file = ARTIFACTS / "production_routing_demo.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    print("="*60)
    print("Production Routing Demo")
    print("="*60)
    print(f"Profile: {profile.primary_profile}")
    print(f"Target: {ValuationTarget.FUNDAMENTAL_VALUE_CURRENT}")
    print(f"Eligible methods: {result['routing_result']['eligible_methods_count']}")
    print(f"Ineligible methods: {result['routing_result']['ineligible_methods_count']}")
    print(f"\n✓ Results: {output_file}")
    print("\n诚实评价:")
    print("- 1条生产routing path已执行（非SimplifiedRoutingEngine）")
    print("- 其余10×12×4缺口标记UNVERIFIED/BLOCKED")
    print("- 状态: PARTIAL_EXECUTED")
    
    return result


if __name__ == "__main__":
    execute_one_production_route()
